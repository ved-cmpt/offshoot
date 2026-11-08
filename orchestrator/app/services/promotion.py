"""Human approval and strangler-fig promotion (F09, Blueprint Sections 7.3 and 9).

- An architect approves or rejects a module. Approval needs a passing latest verification
  of the current artifact, evaluated again here under today's thresholds (409 otherwise).
- Facade modes: LEGACY, SHADOW (both run, the legacy answer is returned, differences are
  recorded) and MODERN. SHADOW needs an approved module. MODERN needs SHADOW and zero
  mismatches over at least SHADOW_SAMPLE_SIZE compared requests since entering SHADOW.
  LEGACY is always allowed: it is the rollback.
- The facade reads modes through an authenticated internal API and reports each shadow
  comparison back. The model has no route to any of this.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.db.models import Approval, CodeArtifact, Job, Module, Project, ShadowMismatch, User
from app.services import audit, gates, modules
from app.services.agent.context import load_migration_context
from app.services.agent.workflow_prompts import migration_block
from app.services.harness.records import compare, describe

ModuleDecision = Literal["APPROVED", "REJECTED"]
FacadeMode = Literal["LEGACY", "SHADOW", "MODERN"]
REJECTABLE_STATES = ("VERIFIED", "BLOCKED", "BUILD_FAILED")


def _stale(module: Module) -> ApiError:
    return ApiError(409, "STALE_VERSION", f"This module has changed. Reload it: it is now version {module.version}.")


def passing_verification(db: Session, module: Module, settings: Settings) -> bool:
    """The latest full run is of the current artifact and passes every gate today."""
    run = modules.latest_run(db, module.id)
    if run is None or module.current_artifact_id is None or run.artifact_id != module.current_artifact_id:
        return False
    artifact = db.get(CodeArtifact, run.artifact_id)
    if artifact is None:
        return False
    limits = gates.thresholds(db, module.id, settings)
    evaluated = gates.evaluate(artifact, run.cases, run.failed, run.coverage_pct, run.mutation_score, limits)
    return gates.all_passed(evaluated)


def _started_by(db: Session, module: Module) -> uuid.UUID | None:
    artifact = db.get(CodeArtifact, module.current_artifact_id) if module.current_artifact_id else None
    job = db.get(Job, artifact.produced_by_job) if artifact and artifact.produced_by_job else None
    return job.requested_by if job else None


def decide_module(
    db: Session,
    module: Module,
    actor: User,
    decision: ModuleDecision,
    reason: str | None,
    expected_version: int,
    settings: Settings,
    seeded: bool = False,
) -> None:
    if module.version != expected_version:
        raise _stale(module)
    if module.state in ("APPROVED", "REJECTED"):
        raise ApiError(409, "ALREADY_DECIDED", f"This module is already {module.state.lower()}.")
    if decision == "REJECTED":
        if not (reason and reason.strip()):
            raise ApiError(422, "REASON_REQUIRED", "A rejection needs a reason.")
        if module.state not in REJECTABLE_STATES:
            raise ApiError(409, "INVALID_STATE", "Only a module with migrated code can be rejected.")
    elif module.state != "VERIFIED" or not passing_verification(db, module, settings):
        raise ApiError(
            409,
            "VERIFICATION_REQUIRED",
            "A module can be approved only when its latest verification passed every gate.",
        )
    own = _started_by(db, module) == actor.id
    if own and not settings.allow_self_approval:
        other = db.scalar(select(User.id).where(User.role == "ARCHITECT", User.active, User.id != actor.id).limit(1))
        if other is not None:
            raise ApiError(403, "SELF_APPROVAL", "Another architect must decide on a migration you started.")
    from_state = module.state
    modules.set_state(module, decision)
    db.add(Approval(entity_type="MODULE", entity_id=module.id, decision=decision, reason=reason, actor_id=actor.id))
    metadata: dict[str, Any] = {
        "decision": decision,
        "from_state": from_state,
        "program": module.program,
        "artifact_id": str(module.current_artifact_id),
        "self_approval": own,
    }
    if seeded:
        metadata["seeded"] = True
    audit.record(db, "module.decision", actor_id=actor.id, entity_type="module", entity_id=module.id, metadata=metadata)


@dataclass(frozen=True)
class ShadowStatus:
    compared: int
    mismatches: int
    sample: int
    since: datetime | None

    @property
    def ready(self) -> bool:
        return self.compared >= self.sample and self.mismatches == 0


def shadow_status(db: Session, module: Module, settings: Settings) -> ShadowStatus:
    mismatches = 0
    if module.shadow_since is not None:
        mismatches = (
            db.scalar(
                select(func.count())
                .select_from(ShadowMismatch)
                .where(ShadowMismatch.module_id == module.id, ShadowMismatch.created_at >= module.shadow_since)
            )
            or 0
        )
    return ShadowStatus(module.shadow_compared, mismatches, settings.shadow_sample_size, module.shadow_since)


def set_facade_mode(
    db: Session,
    module: Module,
    actor: User,
    mode: FacadeMode,
    reason: str | None,
    expected_version: int,
    settings: Settings,
    seeded: bool = False,
) -> None:
    if module.version != expected_version:
        raise _stale(module)
    if mode == module.facade_mode:
        raise ApiError(409, "NO_CHANGE", f"The module already routes to {mode.lower()}.")
    status = shadow_status(db, module, settings)
    if mode in ("SHADOW", "MODERN") and module.state != "APPROVED":
        raise ApiError(409, "NOT_APPROVED", "Only an approved module can take traffic.")
    if mode == "MODERN":
        if module.facade_mode != "SHADOW":
            raise ApiError(409, "SHADOW_REQUIRED", "A module runs in shadow mode before it goes modern.")
        if not status.ready:
            raise ApiError(
                409,
                "SHADOW_GATE",
                f"Promotion needs {status.sample} compared requests with no mismatch; there are "
                f"{status.compared} compared and {status.mismatches} mismatched.",
            )
    previous = module.facade_mode
    module.facade_mode = mode
    if mode == "SHADOW":
        module.shadow_since = datetime.now(UTC)
        module.shadow_compared = 0
    module.version += 1
    module.updated_at = datetime.now(UTC)
    metadata: dict[str, Any] = {
        "from": previous,
        "to": mode,
        "program": module.program,
        "reason": (reason or "")[:500],
        "shadow_compared": status.compared,
        "shadow_mismatches": status.mismatches,
    }
    if seeded:
        metadata["seeded"] = True
    audit.record(db, "facade.mode", actor_id=actor.id, entity_type="module", entity_id=module.id, metadata=metadata)


def roll_back_on_failure(db: Session, module: Module) -> None:
    """An approved module whose re-verification fails stops taking modern traffic at once."""
    if module.facade_mode != "LEGACY":
        previous = module.facade_mode
        module.facade_mode = "LEGACY"
        audit.record(
            db,
            "facade.rollback",
            entity_type="module",
            entity_id=module.id,
            metadata={"from": previous, "to": "LEGACY", "program": module.program, "reason": "verification failed"},
        )


# --- The facade's side: route table and shadow reports ---


def facade_project(db: Session, settings: Settings) -> Project | None:
    return db.scalar(
        select(Project).where(Project.name == settings.facade_project, Project.source_kind == "BUNDLED").limit(1)
    )


def route_table(db: Session, settings: Settings) -> dict[str, Any]:
    """What the facade routes where. Modern code comes only from an approved module's artifact."""
    project = facade_project(db, settings)
    routes: dict[str, Any] = {}
    if project is not None:
        for module in db.scalars(select(Module).where(Module.project_id == project.id)):
            entry: dict[str, Any] = {"mode": module.facade_mode, "module_id": str(module.id)}
            artifact = db.get(CodeArtifact, module.current_artifact_id) if module.current_artifact_id else None
            if module.facade_mode != "LEGACY" and module.state == "APPROVED" and artifact is not None:
                entry["artifact"] = {"sha256": artifact.sha256, "version": artifact.version, "files": artifact.files}
            else:
                entry["mode"] = "LEGACY"
            routes[module.program] = entry
    digest = hashlib.sha256(
        repr(sorted((k, v["mode"], v.get("artifact", {}).get("sha256")) for k, v in routes.items())).encode()
    )
    return {"project": str(project.id) if project else None, "version": digest.hexdigest()[:16], "modules": routes}


def record_shadow(
    db: Session, settings: Settings, program: str, input_record: str, legacy: str, modern: str
) -> dict[str, Any]:
    """One shadow comparison, reported by the facade. The server decides whether it matched."""
    project = facade_project(db, settings)
    module = (
        db.scalar(select(Module).where(Module.project_id == project.id, Module.program == program).with_for_update())
        if project
        else None
    )
    if module is None:
        raise ApiError(404, "NOT_FOUND", "No such module.")
    if module.facade_mode != "SHADOW":
        raise ApiError(409, "NOT_IN_SHADOW", "This module is not in shadow mode.")
    block = migration_block(load_migration_context(db, module.project_id, module.program))
    diffs = compare(block, legacy, modern)
    module.shadow_compared += 1
    request_hash = hashlib.sha256(input_record.encode()).hexdigest()
    if diffs:
        db.add(
            ShadowMismatch(
                module_id=module.id,
                request_hash=request_hash,
                diff={
                    "input": input_record,
                    "input_fields": describe(block, input_record),
                    "legacy": legacy,
                    "modern": modern,
                    "diffs": [diff.to_json() for diff in diffs],
                },
            )
        )
    return {"match": not diffs, "compared": module.shadow_compared, "fields": [d.field for d in diffs]}
