"""Job table operations: idempotent enqueue, SKIP LOCKED claim, recovery of lost jobs."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Job
from app.services import audit

MAX_ATTEMPTS = 3
REUSABLE_STATUSES = ("QUEUED", "RUNNING", "SUCCEEDED")
ACTIVE_STATUSES = ("QUEUED", "RUNNING")


def hash_inputs(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def _find_reusable(
    db: Session, project_id: uuid.UUID, kind: str, input_hash: str, statuses: tuple[str, ...] = ()
) -> Job | None:
    return db.scalar(
        select(Job)
        .where(
            Job.project_id == project_id,
            Job.kind == kind,
            Job.input_hash == input_hash,
            Job.status.in_(statuses or REUSABLE_STATUSES),
        )
        .order_by(Job.created_at.desc(), Job.id)
        .limit(1)
    )


def enqueue(
    db: Session,
    project_id: uuid.UUID,
    kind: str,
    input_hash: str,
    payload: dict[str, Any],
    actor_id: uuid.UUID | None,
    reuse_finished: bool = True,
) -> tuple[Job, bool]:
    """Return (job, created). The same input returns its live or succeeded job; a failed one may retry.

    With `reuse_finished=False` only a queued or running job is reused, so a finished one can be
    run again on purpose (a re-verification), while two identical requests still cannot race.
    """
    statuses = REUSABLE_STATUSES if reuse_finished else ACTIVE_STATUSES
    existing = _find_reusable(db, project_id, kind, input_hash, statuses)
    if existing is not None:
        return existing, False
    job = Job(
        project_id=project_id,
        kind=kind,
        status="QUEUED",
        input_hash=input_hash,
        payload=payload,
        requested_by=actor_id,
    )
    db.add(job)
    try:
        db.flush()
    except IntegrityError:
        # Another request queued the same input between the check and the insert.
        db.rollback()
        winner = _find_reusable(db, project_id, kind, input_hash, statuses)
        if winner is None:
            raise
        return winner, False
    audit.record(
        db,
        "job.queued",
        actor_id=actor_id,
        entity_type="job",
        entity_id=job.id,
        metadata={"kind": kind, "payload": payload},
    )
    db.commit()
    return job, True


def claim_next(db: Session) -> uuid.UUID | None:
    """Claim the oldest queued job. Concurrent workers skip rows another worker has locked."""
    job = db.scalar(
        select(Job)
        .where(Job.status == "QUEUED")
        .order_by(Job.created_at, Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        db.rollback()
        return None
    job.status = "RUNNING"
    job.attempts += 1
    job.started_at = datetime.now(UTC)
    job_id = job.id
    db.commit()
    return job_id


def recover_abandoned(db: Session, lease_seconds: int) -> int:
    """A worker that died leaves a job RUNNING. Requeue it, or fail it after too many tries."""
    cutoff = datetime.now(UTC) - timedelta(seconds=lease_seconds)
    jobs = db.scalars(
        select(Job).where(Job.status == "RUNNING", Job.started_at < cutoff).with_for_update(skip_locked=True)
    ).all()
    for job in jobs:
        if job.attempts >= MAX_ATTEMPTS:
            job.status = "FAILED"
            job.error_code = "JOB_ABANDONED"
            job.ended_at = datetime.now(UTC)
            audit.record(
                db, "job.failed", entity_type="job", entity_id=job.id, metadata={"error_code": "JOB_ABANDONED"}
            )
        else:
            job.status = "QUEUED"
            audit.record(db, "job.requeued", entity_type="job", entity_id=job.id, metadata={"attempts": job.attempts})
    db.commit()
    return len(jobs)
