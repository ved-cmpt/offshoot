"""What each job kind does, and running a claimed job to a final state.

A failed job stores nothing but its error code and the record of its AI calls (Blueprint
Section 3.3). Errors are fixed codes: exception text never reaches the database.
"""

import json
import logging
import time
import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import AiCall, Job, Project, SourceFile
from app.services import audit
from app.services.agent.context import ContextViolation, ProgramNotFound, load_program_context
from app.services.agent.prompts import AgentRequest, render_rules_request
from app.services.agent.provider import (
    AI_BUDGET_EXCEEDED,
    AgentError,
    AgentProvider,
    Attempt,
    get_agent_provider,
)
from app.services.analysis.inventory import ANALYZER_VERSION, SourceInput, build_inventory
from app.services.analysis.store import inventory_summary, replace_inventory
from app.services.jobs import queue
from app.services.rules import persist_extraction

logger = logging.getLogger(__name__)
LIVE_ATTEMPTS_PER_CALL = 2


class JobFailed(Exception):
    def __init__(self, code: str, attempts: Iterable[Attempt] = (), request: AgentRequest | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.attempts = list(attempts)
        self.request = request


def analyze_input_hash(db: Session, project_id: uuid.UUID) -> str:
    rows = db.execute(
        select(SourceFile.path, SourceFile.sha256).where(SourceFile.project_id == project_id).order_by(SourceFile.path)
    ).all()
    return queue.hash_inputs(ANALYZER_VERSION, *[f"{path}:{sha}" for path, sha in rows])


def extract_input_hash(db: Session, project_id: uuid.UUID, program: str, provider: AgentProvider) -> str:
    return queue.hash_inputs(analyze_input_hash(db, project_id), "rules-v1", program, provider.identity(program))


def _set_stage(db: Session, job: Job, stage: str) -> None:
    job.metrics = {**job.metrics, "stage": stage}
    db.commit()


def run_analyze(db: Session, job: Job, _settings: Settings) -> dict[str, Any]:
    project = db.get(Project, job.project_id)
    if project is None:
        raise JobFailed("PROJECT_NOT_FOUND")
    project.status = "ANALYZING"
    _set_stage(db, job, "parsing")

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


def _live_calls_used(db: Session, project_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(AiCall)
            .join(Job, Job.id == AiCall.job_id)
            .where(Job.project_id == project_id, AiCall.mode == "gemini")
        )
        or 0
    )


def _record_attempts(
    db: Session, job_id: uuid.UUID, mode: str, request: AgentRequest | None, attempts: Iterable[Attempt]
) -> None:
    summary = None
    if request is not None:
        # A summary, not the prompt: which files went in and how much, so the log stays bounded.
        summary = json.dumps(
            {
                "program": request.program,
                "files": list(request.context_files),
                "prompt_chars": len(request.system_instructions) + len(request.user_prompt),
            }
        )
    for attempt in attempts:
        db.add(
            AiCall(
                job_id=job_id,
                mode=mode,
                model_id=attempt.model_id,
                prompt_version=request.prompt_version if request else "rules-v1",
                tokens=attempt.tokens,
                latency_ms=attempt.latency_ms,
                status=attempt.status,
                error_code=attempt.error_code,
                redacted_input=summary,
            )
        )


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

    max_attempts = LIVE_ATTEMPTS_PER_CALL
    if provider.mode != "mock":
        remaining = settings.ai_project_call_budget - _live_calls_used(db, job.project_id)
        if remaining <= 0:
            raise JobFailed(AI_BUDGET_EXCEEDED, request=request)
        max_attempts = min(LIVE_ATTEMPTS_PER_CALL, remaining)

    _set_stage(db, job, "calling the agent")
    try:
        result = provider.extract_rules(request, max_attempts)
    except AgentError as exc:
        raise JobFailed(exc.code, exc.attempts, request) from None

    _set_stage(db, job, "validating")
    _record_attempts(db, job.id, provider.mode, request, result.attempts)
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
    _record_attempts(db, job.id, settings.ai_mode, failure.request, failure.attempts)
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
