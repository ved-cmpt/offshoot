"""What each job kind does, and running a claimed job to a final state.

A failed job stores nothing but its error code and the record of its AI calls (Blueprint
Section 3.3). Errors are fixed codes: exception text never reaches the database. The
module job kinds (PLAN, MIGRATE, REPAIR, VERIFY, MUTATE) live in module_handlers.py.
"""

import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import Job, Project, SourceFile
from app.services import audit
from app.services.agent.context import ContextViolation, ProgramNotFound, load_program_context
from app.services.agent.prompts import render_rules_request
from app.services.agent.provider import AgentError, AgentProvider, get_agent_provider
from app.services.analysis.inventory import ANALYZER_VERSION, SourceInput, build_inventory
from app.services.analysis.store import inventory_summary, replace_inventory
from app.services.jobs import module_handlers, queue
from app.services.jobs.common import (
    LIVE_ATTEMPTS_PER_CALL,
    JobFailed,
    analyze_input_hash,
    attempts_allowed,
    record_attempts,
    set_stage,
)
from app.services.rules import persist_extraction

logger = logging.getLogger(__name__)
__all__ = ["LIVE_ATTEMPTS_PER_CALL", "JobFailed", "analyze_input_hash", "extract_input_hash", "run_job", "run_pending"]


def extract_input_hash(db: Session, project_id: uuid.UUID, program: str, provider: AgentProvider) -> str:
    return queue.hash_inputs(analyze_input_hash(db, project_id), "rules-v1", program, provider.identity(program))


def run_analyze(db: Session, job: Job, _settings: Settings) -> dict[str, Any]:
    project = db.get(Project, job.project_id)
    if project is None:
        raise JobFailed("PROJECT_NOT_FOUND")
    project.status = "ANALYZING"
    set_stage(db, job, "parsing")

    rows = db.scalars(
        select(SourceFile).where(SourceFile.project_id == job.project_id, SourceFile.kind.in_(("PROGRAM", "COPYBOOK")))
    ).all()
    if not any(row.kind == "PROGRAM" for row in rows):
        raise JobFailed("NO_PROGRAMS")
    inventory = build_inventory(SourceInput(row.path, row.kind, row.content) for row in rows)
    file_ids = {PurePosixPath(row.path).name: row.id for row in rows}
    stored = replace_inventory(db, job.project_id, inventory, file_ids)
    project.status = "ANALYZED"
    return {
        "stage": "done",
        "analyzer_version": ANALYZER_VERSION,
        "summary": inventory_summary(inventory),
        "stored": stored,
        "diagnostics": inventory.diagnostics[:50],
    }


def run_extract(db: Session, job: Job, settings: Settings) -> dict[str, Any]:
    provider = get_agent_provider(settings)
    program = str(job.payload.get("program", ""))
    try:
        context = load_program_context(db, job.project_id, program)
    except ProgramNotFound as exc:
        raise JobFailed("PROGRAM_NOT_FOUND") from exc
    except ContextViolation as exc:
        raise JobFailed("AGENT_CONTEXT_FORBIDDEN") from exc
    request = render_rules_request(context)
    max_attempts = attempts_allowed(db, job, provider, settings, request)

    set_stage(db, job, "calling the agent")
    try:
        result = provider.extract_rules(request, max_attempts)
    except AgentError as exc:
        raise JobFailed(exc.code, exc.attempts, request) from None

    set_stage(db, job, "validating")
    record_attempts(db, job.id, provider.mode, request, result.attempts)
    model_id = result.attempts[-1].model_id if result.attempts else None
    counts = persist_extraction(db, job, result.output.rules, context, settings, request.prompt_version, model_id)
    return {
        "stage": "done",
        "program": context.program,
        "mode": provider.mode,
        "rules_proposed": counts.proposed,
        "rules_flagged": counts.flagged,
        "rules_replaced": counts.replaced,
        "rules_kept_decided": counts.kept_decided,
        "duplicates_merged": counts.merged_duplicates,
        "ai_calls": len(result.attempts),
    }


HANDLERS: dict[str, Callable[[Session, Job, Settings], dict[str, Any]]] = {
    "ANALYZE": run_analyze,
    "EXTRACT": run_extract,
    **module_handlers.HANDLERS,
}


def _finish_failed(db: Session, job_id: uuid.UUID, failure: JobFailed, settings: Settings) -> None:
    db.rollback()
    job = db.get(Job, job_id)
    if job is None:
        return
    job.status = "FAILED"
    job.error_code = failure.code
    job.ended_at = datetime.now(UTC)
    job.metrics = {**job.metrics, "stage": "failed"}
    if job.kind == "ANALYZE":
        project = db.get(Project, job.project_id)
        if project is not None:
            project.status = "FAILED"
    module_handlers.settle_failed_module(db, job, failure.code)
    record_attempts(db, job.id, settings.ai_mode, failure.request, failure.attempts)
    audit.record(
        db,
        "job.failed",
        actor_id=job.requested_by,
        entity_type="job",
        entity_id=job.id,
        metadata={"kind": job.kind, "error_code": failure.code},
    )
    db.commit()


def run_job(session_factory: sessionmaker[Session], job_id: uuid.UUID, settings: Settings) -> None:
    """Run one claimed job to SUCCEEDED or FAILED. Never raises for a job's own failure."""
    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        started = time.monotonic()
        try:
            metrics = HANDLERS[job.kind](db, job, settings)
        except JobFailed as failure:
            _finish_failed(db, job_id, failure, settings)
            return
        except Exception as exc:  # noqa: BLE001 - The type is logged. The message may hold data.
            logger.error("Job %s failed unexpectedly: %s", job_id, type(exc).__name__)
            _finish_failed(db, job_id, JobFailed("INTERNAL_ERROR"), settings)
            return
        metrics["duration_ms"] = int((time.monotonic() - started) * 1000)
        job.metrics = metrics
        job.status = "SUCCEEDED"
        job.ended_at = datetime.now(UTC)
        audit.record(
            db,
            "job.succeeded",
            actor_id=job.requested_by,
            entity_type="job",
            entity_id=job.id,
            metadata={"kind": job.kind},
        )
        db.commit()


def run_pending(session_factory: sessionmaker[Session], settings: Settings, limit: int = 100) -> int:
    """Claim and run queued jobs until none are left. Used by the seed and by tests."""
    done = 0
    while done < limit:
        with session_factory() as db:
            job_id = queue.claim_next(db)
        if job_id is None:
            return done
        run_job(session_factory, job_id, settings)
        done += 1
    return done
