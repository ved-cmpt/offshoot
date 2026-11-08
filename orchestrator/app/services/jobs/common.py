"""Pieces every job handler shares: the failure type, progress stages and AI call records."""

import json
import uuid
from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import AiCall, Job, SourceFile
from app.services.agent.prompts import AgentRequest
from app.services.agent.provider import AI_BUDGET_EXCEEDED, AgentProvider, Attempt
from app.services.analysis.inventory import ANALYZER_VERSION
from app.services.jobs import queue

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


def set_stage(db: Session, job: Job, stage: str) -> None:
    job.metrics = {**job.metrics, "stage": stage}
    db.commit()


def live_calls_used(db: Session, project_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(AiCall)
            .join(Job, Job.id == AiCall.job_id)
            .where(Job.project_id == project_id, AiCall.mode == "gemini")
        )
        or 0
    )


def attempts_allowed(db: Session, job: Job, provider: AgentProvider, settings: Settings, request: AgentRequest) -> int:
    """Mock calls are free. Live calls count against the project's budget (ADR-026)."""
    if provider.mode == "mock":
        return LIVE_ATTEMPTS_PER_CALL
    remaining = settings.ai_project_call_budget - live_calls_used(db, job.project_id)
    if remaining <= 0:
        raise JobFailed(AI_BUDGET_EXCEEDED, request=request)
    return min(LIVE_ATTEMPTS_PER_CALL, remaining)


def record_attempts(
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
