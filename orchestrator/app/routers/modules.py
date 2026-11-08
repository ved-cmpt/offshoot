"""Modules: read their code, builds and verification runs; start migration, repair,
verification and mutation jobs; record gate exceptions.

Every precondition is checked here before a job is queued, and checked again by the job,
so a stale page cannot push a module through a step it is not ready for.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import ALL_ROLES, ARCHITECT_ONLY, ENGINEER_PLUS, AppSettings, DbSession, require_roles
from app.core.errors import ApiError, not_found
from app.db.models import (
    Approval,
    CodeArtifact,
    Job,
    Module,
    Plan,
    Project,
    Rule,
    ShadowMismatch,
    User,
    VerificationRun,
)
from app.routers.inventory import JobOut, get_project_or_404, parse_uuid, to_job_out
from app.services import gates, modules, promotion
from app.services.agent.provider import get_agent_provider
from app.services.harness.verify import EXECUTABLE_MODULES
from app.services.jobs import queue
from app.services.jobs.module_handlers import migrate_input_hash, verify_input_hash

router = APIRouter(tags=["modules"])
RequireViewer = Depends(require_roles(ALL_ROLES))
Engineer = Annotated[User, Depends(require_roles(ENGINEER_PLUS))]
Architect = Annotated[User, Depends(require_roles(ARCHITECT_ONLY))]
ACTIVE_KINDS = ("MIGRATE", "REPAIR", "VERIFY", "MUTATE", "SHADOW")


class RunSummary(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    seed: int
    cases: int
    passed: int
    failed: int
    coverage_pct: float | None
    mutation_score: float | None
    artifact_id: uuid.UUID | None
    artifact_version: int | None
    job_id: uuid.UUID | None
    created_at: datetime


class ArtifactSummary(BaseModel):
    id: uuid.UUID
    version: int
    kind: str
    attempt: int
    build_status: str
    sha256: str
    files: list[str]
    rule_ids: list[str]
    notes: str | None
    model_id: str | None
    prompt_version: str | None
    created_at: datetime


class ModuleSummary(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    program: str
    target_service: str | None
    order_index: int
    state: str
    state_reason: str | None
    facade_mode: str
    version: int
    current_artifact: ArtifactSummary | None
    latest_run: RunSummary | None
    repairs_used: int
    repairs_remaining: int
    migratable: bool
    active_job: JobOut | None
    updated_at: datetime


class ShadowOut(BaseModel):
    compared: int
    mismatches: int
    sample: int
    ready: bool
    since: datetime | None


class DecisionOut(BaseModel):
    decision: str
    reason: str | None
    by: str | None
    at: datetime


class ModuleDetail(ModuleSummary):
    gates: list[dict[str, Any]]
    thresholds: dict[str, Any]
    verified_rules: int
    shadow: ShadowOut
    decision: DecisionOut | None
    approvable: bool


class ArtifactDetail(ArtifactSummary):
    module_id: uuid.UUID
    parent_id: uuid.UUID | None
    file_contents: list[dict[str, str]]
    build_report: dict[str, Any]


class RunDetail(RunSummary):
    report: dict[str, Any]
    gates: list[dict[str, Any]]
    base_run_id: uuid.UUID | None


def _artifact_summary(artifact: CodeArtifact) -> ArtifactSummary:
    return ArtifactSummary(
        id=artifact.id,
        version=artifact.version,
        kind=artifact.kind,
        attempt=artifact.attempt,
        build_status=artifact.build_status,
        sha256=artifact.sha256,
        files=[item["path"] for item in artifact.files],
        rule_ids=artifact.rule_ids,
        notes=artifact.notes,
        model_id=artifact.model_id,
        prompt_version=artifact.prompt_version,
        created_at=artifact.created_at,
    )


def _run_summary(run: VerificationRun, versions: dict[uuid.UUID, int]) -> RunSummary:
    return RunSummary(
        id=run.id,
        kind=run.kind,
        status=run.status,
        seed=run.seed,
        cases=run.cases,
        passed=run.passed,
        failed=run.failed,
        coverage_pct=run.coverage_pct,
        mutation_score=run.mutation_score,
        artifact_id=run.artifact_id,
        artifact_version=versions.get(run.artifact_id) if run.artifact_id else None,
        job_id=run.job_id,
        created_at=run.created_at,
    )


def _active_job(db: Session, module: Module) -> Job | None:
    return db.scalar(
        select(Job)
        .where(
            Job.project_id == module.project_id,
            Job.kind.in_(ACTIVE_KINDS),
            Job.status.in_(("QUEUED", "RUNNING")),
            Job.payload["module_id"].astext == str(module.id),
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    )


def _summary(db: Session, module: Module, settings: AppSettings) -> ModuleSummary:
    artifact = db.get(CodeArtifact, module.current_artifact_id) if module.current_artifact_id else None
    run = modules.latest_run(db, module.id)
    versions = {artifact.id: artifact.version} if artifact else {}
    if run is not None and run.artifact_id and run.artifact_id not in versions:
        other = db.get(CodeArtifact, run.artifact_id)
        if other is not None:
            versions[other.id] = other.version
    used = modules.lineage_repairs(db, module)
    active = _active_job(db, module)
    return ModuleSummary(
        id=module.id,
        project_id=module.project_id,
        program=module.program,
        target_service=module.target_service,
        order_index=module.order_index,
        state=module.state,
        state_reason=module.state_reason,
        facade_mode=module.facade_mode,
        version=module.version,
        current_artifact=_artifact_summary(artifact) if artifact else None,
        latest_run=_run_summary(run, versions) if run else None,
        repairs_used=used,
        repairs_remaining=max(settings.repair_max_attempts - used, 0),
        migratable=module.program in EXECUTABLE_MODULES,
        active_job=to_job_out(active) if active else None,
        updated_at=module.updated_at,
    )


def _detail(db: Session, module: Module, settings: AppSettings) -> ModuleDetail:
    summary = _summary(db, module, settings)
    limits = gates.thresholds(db, module.id, settings)
    run = modules.latest_run(db, module.id)
    verified = (
        db.scalar(
            select(func.count())
            .select_from(Rule)
            .where(Rule.project_id == module.project_id, Rule.program == module.program, Rule.state == "VERIFIED")
        )
        or 0
    )
    status = promotion.shadow_status(db, module, settings)
    approval = db.scalar(
        select(Approval)
        .where(Approval.entity_type == "MODULE", Approval.entity_id == module.id)
        .order_by(Approval.created_at.desc())
        .limit(1)
    )
    decider = db.get(User, approval.actor_id) if approval else None
    return ModuleDetail(
        **summary.model_dump(),
        gates=current_gates(db, module, run, settings) if run else [],
        thresholds={"coverage": limits.coverage, "mutation": limits.mutation, "exceptions": limits.exceptions},
        verified_rules=verified,
        shadow=ShadowOut(
            compared=status.compared,
            mismatches=status.mismatches,
            sample=status.sample,
            ready=status.ready,
            since=status.since,
        ),
        decision=DecisionOut(
            decision=approval.decision,
            reason=approval.reason,
            by=decider.display_name if decider else None,
            at=approval.created_at,
        )
        if approval and module.state in ("APPROVED", "REJECTED")
        else None,
        approvable=module.state == "VERIFIED" and promotion.passing_verification(db, module, settings),
    )


def current_gates(db: Session, module: Module, run: VerificationRun, settings: AppSettings) -> list[dict[str, Any]]:
    """The latest run's gates under today's thresholds, which an exception may have lowered."""
    artifact = db.get(CodeArtifact, run.artifact_id) if run.artifact_id else None
    if artifact is None:
        return list(run.gates)
    limits = gates.thresholds(db, module.id, settings)
    return gates.evaluate(artifact, run.cases, run.failed, run.coverage_pct, run.mutation_score, limits)


def _versions(db: Session, module_id: uuid.UUID) -> dict[uuid.UUID, int]:
    query = select(CodeArtifact.id, CodeArtifact.version).where(CodeArtifact.module_id == module_id)
    return {row[0]: row[1] for row in db.execute(query)}


def load_module(db: Session, module_id: str, lock: bool = False) -> Module:
    parsed = parse_uuid(module_id, "Module not found.")
    module = modules.lock_module(db, parsed) if lock else db.get(Module, parsed)
    if module is None:
        raise not_found("Module not found.")
    return module


@router.get("/projects/{project_id}/modules", dependencies=[RequireViewer])
def list_modules(project_id: str, db: DbSession, settings: AppSettings) -> list[ModuleSummary]:
    project = get_project_or_404(db, project_id)
    query = select(Module).where(Module.project_id == project.id).order_by(Module.order_index, Module.program)
    rows = db.scalars(query)
    return [_summary(db, module, settings) for module in rows]


@router.get("/modules/{module_id}", dependencies=[RequireViewer])
def get_module(module_id: str, db: DbSession, settings: AppSettings) -> ModuleDetail:
    return _detail(db, load_module(db, module_id), settings)


@router.get("/modules/{module_id}/artifacts", dependencies=[RequireViewer])
def list_artifacts(module_id: str, db: DbSession) -> list[ArtifactSummary]:
    module = load_module(db, module_id)
    rows = db.scalars(
        select(CodeArtifact).where(CodeArtifact.module_id == module.id).order_by(CodeArtifact.version.desc()).limit(50)
    )
    return [_artifact_summary(row) for row in rows]


@router.get("/modules/{module_id}/artifacts/{version}", dependencies=[RequireViewer])
def get_artifact(module_id: str, version: int, db: DbSession) -> ArtifactDetail:
    module = load_module(db, module_id)
    artifact = db.scalar(
        select(CodeArtifact).where(CodeArtifact.module_id == module.id, CodeArtifact.version == version)
    )
    if artifact is None:
        raise not_found("Artifact not found.")
    return ArtifactDetail(
        **_artifact_summary(artifact).model_dump(),
        module_id=module.id,
        parent_id=artifact.parent_id,
        file_contents=artifact.files,
        build_report=artifact.build_report,
    )


@router.get("/modules/{module_id}/runs", dependencies=[RequireViewer])
def list_runs(module_id: str, db: DbSession) -> list[RunSummary]:
    module = load_module(db, module_id)
    rows = list(
        db.scalars(
            select(VerificationRun)
            .where(VerificationRun.module_id == module.id)
            .order_by(VerificationRun.created_at.desc(), VerificationRun.id.desc())
            .limit(50)
        )
    )
    versions = _versions(db, module.id)
    return [_run_summary(row, versions) for row in rows]


@router.get("/modules/{module_id}/runs/{run_id}", dependencies=[RequireViewer])
def get_run(module_id: str, run_id: str, db: DbSession) -> RunDetail:
    module = load_module(db, module_id)
    run = db.get(VerificationRun, parse_uuid(run_id, "Run not found."))
    if run is None or run.module_id != module.id:
        raise not_found("Run not found.")
    versions = _versions(db, module.id)
    return RunDetail(
        **_run_summary(run, versions).model_dump(), report=run.report, gates=run.gates, base_run_id=run.base_run_id
    )


# --- Starting jobs ---


def _executable(db: Session, module: Module) -> Project:
    project = db.get(Project, module.project_id)
    if project is None:
        raise not_found("Project not found.")
    if project.source_kind != "BUNDLED":
        raise ApiError(409, "UPLOAD_NOT_EXECUTABLE", "Uploaded sources are never executed, so they cannot be verified.")
    if module.program not in EXECUTABLE_MODULES:
        message = "The per-record harness has no entry for this program, so it cannot be verified."
        raise ApiError(409, "MODULE_NOT_SUPPORTED", message)
    approved = db.scalar(select(Plan.id).where(Plan.id == module.plan_id, Plan.state == "APPROVED"))
    if approved is None:
        raise ApiError(409, "PLAN_NOT_APPROVED", "The plan that holds this module is not approved.")
    return project


def _enqueue(db: Session, module: Module, kind: str, input_hash: str, user: User, extra: dict[str, Any]) -> JobOut:
    payload = {"module_id": str(module.id), "program": module.program, **extra}
    job, created = queue.enqueue(db, module.project_id, kind, input_hash, payload, user.id, reuse_finished=False)
    return to_job_out(job, deduplicated=not created)


@router.post("/modules/{module_id}/migrate", status_code=status.HTTP_202_ACCEPTED)
def start_migration(module_id: str, db: DbSession, user: Engineer, settings: AppSettings) -> JobOut:
    module = load_module(db, module_id)
    _executable(db, module)
    if module.state not in modules.MIGRATABLE_STATES:
        raise ApiError(409, "INVALID_STATE", f"A module that is {module.state.lower()} cannot be migrated again.")
    rules = (
        db.scalar(
            select(func.count())
            .select_from(Rule)
            .where(Rule.project_id == module.project_id, Rule.program == module.program, Rule.state == "VERIFIED")
        )
        or 0
    )
    if not rules:
        raise ApiError(409, "NO_VERIFIED_RULES", "Verify at least one rule of this program before migrating it.")
    input_hash = migrate_input_hash(db, module, get_agent_provider(settings))
    return _enqueue(db, module, "MIGRATE", input_hash, user, {})


@router.post("/modules/{module_id}/repair", status_code=status.HTTP_202_ACCEPTED)
def start_repair(module_id: str, db: DbSession, user: Engineer, settings: AppSettings) -> JobOut:
    module = load_module(db, module_id)
    _executable(db, module)
    if module.state not in modules.REPAIRABLE_STATES or module.current_artifact_id is None:
        raise ApiError(409, "INVALID_STATE", "Only a blocked module or a failed build can be repaired.")
    if modules.lineage_repairs(db, module) >= settings.repair_max_attempts:
        message = f"The repair budget of {settings.repair_max_attempts} attempts is spent. Migrate again."
        raise ApiError(409, "REPAIR_LIMIT", message)
    provider = get_agent_provider(settings)
    input_hash = queue.hash_inputs(
        "repair-v1", provider.identity(module.program, "repair-v1"), str(module.id), str(module.version)
    )
    return _enqueue(db, module, "REPAIR", input_hash, user, {})


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: int | None = Field(default=None, ge=0, le=2**62)


@router.post("/modules/{module_id}/verify", status_code=status.HTTP_202_ACCEPTED)
def start_verification(
    module_id: str, db: DbSession, user: Engineer, settings: AppSettings, body: VerifyRequest | None = None
) -> JobOut:
    module = load_module(db, module_id)
    _executable(db, module)
    artifact = db.get(CodeArtifact, module.current_artifact_id) if module.current_artifact_id else None
    allowed = ("VERIFIED", "BLOCKED", "VERIFYING", "APPROVED")
    if artifact is None or artifact.build_status != "BUILT" or module.state not in allowed:
        raise ApiError(409, "INVALID_STATE", "Only a module with a built artifact can be verified.")
    seed = body.seed if body and body.seed is not None else settings.equivalence_seed
    return _enqueue(db, module, "VERIFY", verify_input_hash(module, artifact, seed), user, {"seed": seed})


@router.post("/modules/{module_id}/mutate", status_code=status.HTTP_202_ACCEPTED)
def start_mutation(module_id: str, db: DbSession, user: Engineer) -> JobOut:
    module = load_module(db, module_id)
    _executable(db, module)
    run = modules.latest_run(db, module.id)
    if run is None or run.artifact_id != module.current_artifact_id or run.failed:
        raise ApiError(409, "EQUIVALENCE_NOT_PASSED", "Mutation testing needs a verification where every case matched.")
    input_hash = queue.hash_inputs("mutate", str(module.id), str(run.id))
    return _enqueue(db, module, "MUTATE", input_hash, user, {"base_run_id": str(run.id)})


class GateExceptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate: Literal["COVERAGE", "MUTATION"]
    threshold: float = Field(ge=0, le=100)
    reason: str = Field(min_length=1, max_length=2000)
    expected_version: int = Field(ge=1)


@router.post("/modules/{module_id}/gate-exceptions")
def add_gate_exception(
    module_id: str, body: GateExceptionRequest, db: DbSession, user: Architect, settings: AppSettings
) -> ModuleDetail:
    """Lower one module's coverage or mutation threshold, with a reason. Re-evaluates the latest run."""
    module = load_module(db, module_id, lock=True)
    modules.add_gate_exception(db, module, user, body.gate, body.threshold, body.reason, body.expected_version)
    run = modules.latest_run(db, module.id)
    if run is not None and run.artifact_id == module.current_artifact_id and module.state in ("VERIFIED", "BLOCKED"):
        evaluated = current_gates(db, module, run, settings)
        passed = gates.all_passed(evaluated)
        new_state = "VERIFIED" if passed else "BLOCKED"
        if new_state != module.state or module.state_reason != gates.first_failure(evaluated):
            modules.set_state(module, new_state, gates.first_failure(evaluated))
    db.commit()
    return _detail(db, module, settings)


# --- Approval and promotion (F09) ---


class ModuleDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["APPROVED", "REJECTED"]
    expected_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=2000)


@router.post("/modules/{module_id}/decision")
def decide_module(
    module_id: str, body: ModuleDecisionRequest, db: DbSession, user: Architect, settings: AppSettings
) -> ModuleDetail:
    module = load_module(db, module_id, lock=True)
    promotion.decide_module(db, module, user, body.decision, body.reason, body.expected_version, settings)
    db.commit()
    return _detail(db, module, settings)


class FacadeModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["LEGACY", "SHADOW", "MODERN"]
    expected_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=500)


@router.post("/modules/{module_id}/facade-mode")
def set_facade_mode(
    module_id: str, body: FacadeModeRequest, db: DbSession, user: Architect, settings: AppSettings
) -> ModuleDetail:
    module = load_module(db, module_id, lock=True)
    promotion.set_facade_mode(db, module, user, body.mode, body.reason, body.expected_version, settings)
    db.commit()
    return _detail(db, module, settings)


class ShadowReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int | None = Field(default=None, ge=1, le=500)


@router.post("/modules/{module_id}/shadow-replay", status_code=status.HTTP_202_ACCEPTED)
def start_shadow_replay(
    module_id: str, db: DbSession, user: Engineer, settings: AppSettings, body: ShadowReplayRequest | None = None
) -> JobOut:
    module = load_module(db, module_id)
    _executable(db, module)
    if module.facade_mode != "SHADOW":
        raise ApiError(
            409, "NOT_IN_SHADOW", "Recorded traffic can be replayed only while the module is in shadow mode."
        )
    count = body.count if body and body.count else settings.shadow_sample_size
    input_hash = queue.hash_inputs(
        "shadow", str(module.id), str(module.version), str(module.shadow_compared), str(count)
    )
    return _enqueue(db, module, "SHADOW", input_hash, user, {"count": count})


class ShadowMismatchOut(BaseModel):
    id: uuid.UUID
    request_hash: str
    diff: dict[str, Any]
    created_at: datetime


class ShadowView(BaseModel):
    status: ShadowOut
    mismatches: list[ShadowMismatchOut]


@router.get("/modules/{module_id}/shadow", dependencies=[RequireViewer])
def get_shadow(module_id: str, db: DbSession, settings: AppSettings) -> ShadowView:
    module = load_module(db, module_id)
    current = promotion.shadow_status(db, module, settings)
    rows = db.scalars(
        select(ShadowMismatch)
        .where(ShadowMismatch.module_id == module.id)
        .order_by(ShadowMismatch.created_at.desc())
        .limit(25)
    )
    return ShadowView(
        status=ShadowOut(
            compared=current.compared,
            mismatches=current.mismatches,
            sample=current.sample,
            ready=current.ready,
            since=current.since,
        ),
        mismatches=[
            ShadowMismatchOut(id=row.id, request_hash=row.request_hash, diff=row.diff, created_at=row.created_at)
            for row in rows
        ],
    )
