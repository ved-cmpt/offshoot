"""Job handlers for the plan and the module lifecycle (Blueprint Section 6.1, Stages 3 to 6).

PLAN: the agent proposes services and risks; the server adds the order and the estimate.
MIGRATE: the agent writes C#; the sandbox builds and tests it; failures go through the
bounded repair loop; a built artifact is queued for verification.
REPAIR: a person asks for a repair of a blocked or failed module; same loop.
VERIFY: the harness runs legacy and modern on the same cases, then the gates decide.
MUTATE: Stryker.NET again on the current artifact, with the latest run's cases.
"""

import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import CodeArtifact, Job, Module, Project, VerificationRun
from app.services import audit, gates, modules
from app.services.agent.context import (
    ContextViolation,
    MigrationContext,
    ProgramNotFound,
    load_migration_context,
    load_plan_context,
)
from app.services.agent.provider import AgentError, AgentProvider, get_agent_provider
from app.services.agent.workflow_prompts import (
    migration_block,
    render_migration_request,
    render_plan_request,
    render_repair_request,
)
from app.services.facade_codec import ENDPOINTS, request_for
from app.services.harness.recorded import recorded_inputs
from app.services.harness.verify import VerificationError, prepare_cases, run_mutation, run_verification
from app.services.jobs import queue
from app.services.jobs.common import JobFailed, analyze_input_hash, attempts_allowed, record_attempts, set_stage
from app.services.plan import PlanInvalid, migration_order, persist_plan, risk_signals
from app.services.promotion import roll_back_on_failure, shadow_status
from app.services.sandbox.client import ModernBuilder, SandboxError, get_legacy_runner, get_modern_builder

MODULE_JOB_KINDS = ("MIGRATE", "REPAIR", "VERIFY", "MUTATE")
HTTP_OK = 200
ROUTE_WAIT_SECONDS = 30


def _module(db: Session, job: Job) -> Module:
    module = modules.lock_module(db, _module_id(job))
    if module is None or module.project_id != job.project_id:
        raise JobFailed("MODULE_NOT_FOUND")
    return module


def _module_id(job: Job) -> uuid.UUID:
    try:
        return uuid.UUID(str(job.payload.get("module_id")))
    except ValueError:
        raise JobFailed("MODULE_NOT_FOUND") from None


def settle_failed_module(db: Session, job: Job, code: str) -> None:
    """A module job that failed must not leave its module looking busy."""
    if job.kind not in MODULE_JOB_KINDS:
        return
    module = db.get(Module, _module_id(job))
    if module is None:
        return
    if module.state == "MIGRATING":
        modules.set_state(module, "BUILD_FAILED", code)
    elif module.state == "VERIFYING":
        modules.set_state(module, "BLOCKED", code)


# --- PLAN ---


def run_plan(db: Session, job: Job, settings: Settings) -> dict[str, Any]:
    provider = get_agent_provider(settings)
    try:
        context = load_plan_context(db, job.project_id)
    except ProgramNotFound:
        raise JobFailed("NOT_ANALYZED") from None
    order = migration_order(db, job.project_id)
    signals = risk_signals(context)
    request = render_plan_request(context, signals)
    max_attempts = attempts_allowed(db, job, provider, settings, request)
    set_stage(db, job, "calling the agent")
    try:
        result = provider.propose_plan(request, max_attempts)
    except AgentError as exc:
        raise JobFailed(exc.code, exc.attempts, request) from None
    set_stage(db, job, "validating")
    model_id = result.attempts[-1].model_id if result.attempts else None
    try:
        plan = persist_plan(db, job, result.output, context, order, signals, request.prompt_version, model_id)
    except PlanInvalid as exc:
        raise JobFailed(exc.code, result.attempts, request) from None
    record_attempts(db, job.id, provider.mode, request, result.attempts)
    return {
        "stage": "done",
        "plan_id": str(plan.id),
        "plan_version": plan.version,
        "services": len(plan.services),
        "risks": len(plan.risks),
        "ai_calls": len(result.attempts),
    }


# --- MIGRATE and REPAIR ---


def _context(db: Session, module: Module) -> MigrationContext:
    try:
        context = load_migration_context(db, module.project_id, module.program)
    except ProgramNotFound:
        raise JobFailed("PROGRAM_NOT_FOUND") from None
    except ContextViolation:
        raise JobFailed("AGENT_CONTEXT_FORBIDDEN") from None
    if not context.rules:
        raise JobFailed("NO_VERIFIED_RULES")
    return context


def _fail_module(db: Session, module: Module, state: str, code: str, failure: JobFailed | None = None) -> JobFailed:
    modules.set_state(module, state, code)
    db.commit()
    return failure or JobFailed(code)


def _build_with_repairs(
    db: Session,
    job: Job,
    module: Module,
    context: MigrationContext,
    provider: AgentProvider,
    builder: ModernBuilder,
    settings: Settings,
    artifact: CodeArtifact,
) -> dict[str, Any]:
    """Build and test in the sandbox. A failed build goes back to the agent, at most N times."""
    repairs = 0
    while True:
        set_stage(db, job, f"building v{artifact.version} in the sandbox")
        try:
            result = builder.build(list(artifact.files))
        except SandboxError as exc:
            raise _fail_module(db, module, "BUILD_FAILED", exc.code) from None
        status = modules.store_build(artifact, result)
        module.current_artifact_id = artifact.id
        audit.record(
            db,
            "artifact.built",
            entity_type="artifact",
            entity_id=artifact.id,
            metadata={"module_id": str(module.id), "version": artifact.version, "build_status": status},
        )
        db.commit()
        if status == "BUILT":
            modules.set_state(module, "VERIFYING")
            db.commit()
            verify_job, _ = queue.enqueue(
                db,
                module.project_id,
                "VERIFY",
                verify_input_hash(module, artifact, settings.equivalence_seed),
                {"module_id": str(module.id), "program": module.program, "artifact_id": str(artifact.id)},
                job.requested_by,
                reuse_finished=False,
            )
            return {
                "stage": "done",
                "program": module.program,
                "artifact_version": artifact.version,
                "build_status": status,
                "repairs_in_this_job": repairs,
                "repairs_used": modules.lineage_repairs(db, module),
                "verify_job_id": str(verify_job.id),
            }
        code = modules.BUILD_FAILURES[status]
        if status in modules.TERMINAL_BUILD_STATUSES:
            raise _fail_module(db, module, "BUILD_FAILED", code)
        used = modules.lineage_repairs(db, module)
        if used >= settings.repair_max_attempts:
            raise _fail_module(db, module, "BUILD_FAILED", code)
        set_stage(db, job, f"repair attempt {used + 1} of {settings.repair_max_attempts}")
        artifact = _repair(
            db, job, module, context, provider, settings, artifact, modules.build_failure_report(artifact)
        )
        repairs += 1


def _repair(
    db: Session,
    job: Job,
    module: Module,
    context: MigrationContext,
    provider: AgentProvider,
    settings: Settings,
    previous: CodeArtifact,
    failure: dict[str, Any],
) -> CodeArtifact:
    attempt = modules.lineage_repairs(db, module) + 1
    rendered = render_repair_request(context, list(previous.files), failure, attempt)
    request = rendered.request
    max_attempts = attempts_allowed(db, job, provider, settings, request)
    try:
        result = provider.migrate(request, max_attempts)
    except AgentError as exc:
        failed = JobFailed(exc.code, exc.attempts, request)
        raise _fail_module(db, module, "BUILD_FAILED", exc.code, failed) from None
    model_id = result.attempts[-1].model_id if result.attempts else None
    try:
        artifact = modules.create_artifact(
            db,
            module,
            job,
            result.output,
            context,
            "REPAIR",
            previous.attempt + 1,
            previous,
            request.prompt_version,
            model_id,
        )
    except modules.ContractViolation:
        failed = JobFailed("AI_INVALID_OUTPUT", result.attempts, request)
        raise _fail_module(db, module, "BUILD_FAILED", "AI_INVALID_OUTPUT", failed) from None
    record_attempts(db, job.id, provider.mode, request, result.attempts)
    db.commit()
    return artifact


def run_migrate(db: Session, job: Job, settings: Settings) -> dict[str, Any]:
    module = _module(db, job)
    if module.state not in modules.MIGRATABLE_STATES:
        raise JobFailed("INVALID_STATE")
    context = _context(db, module)
    provider = get_agent_provider(settings)
    builder = get_modern_builder(settings)
    modules.set_state(module, "MIGRATING")
    set_stage(db, job, "calling the agent")

    rendered = render_migration_request(context)
    request = rendered.request
    max_attempts = attempts_allowed(db, job, provider, settings, request)
    try:
        result = provider.migrate(request, max_attempts)
    except AgentError as exc:
        raise _fail_module(db, module, "BUILD_FAILED", exc.code, JobFailed(exc.code, exc.attempts, request)) from None
    model_id = result.attempts[-1].model_id if result.attempts else None
    try:
        artifact = modules.create_artifact(
            db, module, job, result.output, context, "MIGRATION", 1, None, request.prompt_version, model_id
        )
    except modules.ContractViolation:
        failed = JobFailed("AI_INVALID_OUTPUT", result.attempts, request)
        raise _fail_module(db, module, "BUILD_FAILED", "AI_INVALID_OUTPUT", failed) from None
    record_attempts(db, job.id, provider.mode, request, result.attempts)
    db.commit()
    return _build_with_repairs(db, job, module, context, provider, builder, settings, artifact)


def run_repair(db: Session, job: Job, settings: Settings) -> dict[str, Any]:
    module = _module(db, job)
    if module.state not in modules.REPAIRABLE_STATES or module.current_artifact_id is None:
        raise JobFailed("INVALID_STATE")
    if modules.lineage_repairs(db, module) >= settings.repair_max_attempts:
        raise JobFailed("REPAIR_LIMIT")
    current = db.get(CodeArtifact, module.current_artifact_id)
    if current is None:
        raise JobFailed("NO_ARTIFACT")
    run = modules.latest_run(db, module.id)
    if module.state == "BLOCKED" and run is not None and run.artifact_id == current.id:
        failure = modules.run_failure_report(run)
    else:
        failure = modules.build_failure_report(current)
    context = _context(db, module)
    provider = get_agent_provider(settings)
    builder = get_modern_builder(settings)
    modules.set_state(module, "MIGRATING")
    set_stage(db, job, "calling the agent")
    artifact = _repair(db, job, module, context, provider, settings, current, failure)
    return _build_with_repairs(db, job, module, context, provider, builder, settings, artifact)


# --- VERIFY and MUTATE ---


def migrate_input_hash(db: Session, module: Module, provider: AgentProvider) -> str:
    return queue.hash_inputs(
        analyze_input_hash(db, module.project_id),
        "migrate-v1",
        provider.identity(module.program, "migrate-v1"),
        str(module.id),
        str(module.version),
    )


def verify_input_hash(module: Module, artifact: CodeArtifact, seed: int) -> str:
    return queue.hash_inputs("verify", str(module.id), artifact.sha256, str(seed))


def run_verify(db: Session, job: Job, settings: Settings) -> dict[str, Any]:
    module = _module(db, job)
    artifact = db.get(CodeArtifact, module.current_artifact_id) if module.current_artifact_id else None
    if artifact is None or artifact.build_status != "BUILT":
        raise JobFailed("NO_BUILT_ARTIFACT")
    if module.state not in ("VERIFYING", "VERIFIED", "BLOCKED", "APPROVED"):
        raise JobFailed("INVALID_STATE")
    was_approved = module.state == "APPROVED"
    modules.set_state(module, "VERIFYING")
    set_stage(db, job, "generating inputs")
    seed = int(job.payload.get("seed", settings.equivalence_seed))
    try:
        outcome = run_verification(
            db,
            module,
            artifact,
            settings,
            get_legacy_runner(settings),
            get_modern_builder(settings),
            seed,
            stage=lambda text: set_stage(db, job, text),
        )
    except (VerificationError, SandboxError) as exc:
        if was_approved:
            roll_back_on_failure(db, module)
        raise _fail_module(db, module, "BLOCKED", exc.code) from None

    limits = gates.thresholds(db, module.id, settings)
    evaluated = gates.evaluate(
        artifact, outcome.cases, outcome.failed, outcome.coverage_pct, outcome.mutation_score, limits
    )
    passed = gates.all_passed(evaluated)
    run = VerificationRun(
        module_id=module.id,
        artifact_id=artifact.id,
        job_id=job.id,
        kind="FULL",
        seed=seed,
        cases=outcome.cases,
        passed=outcome.passed,
        failed=outcome.failed,
        coverage_pct=outcome.coverage_pct,
        mutation_score=outcome.mutation_score,
        report=outcome.report,
        gates=evaluated,
        status="PASSED" if passed else "FAILED",
    )
    db.add(run)
    db.flush()
    if passed:
        # A passing re-verification of an approved module keeps its approval.
        modules.set_state(module, "APPROVED" if was_approved else "VERIFIED")
    else:
        modules.set_state(module, "BLOCKED", gates.first_failure(evaluated))
        if was_approved:
            roll_back_on_failure(db, module)
    audit.record(
        db,
        "verification.recorded",
        actor_id=job.requested_by,
        entity_type="module",
        entity_id=module.id,
        metadata={
            "run_id": str(run.id),
            "program": module.program,
            "artifact_version": artifact.version,
            "cases": outcome.cases,
            "failed": outcome.failed,
            "status": run.status,
            "state": module.state,
        },
    )
    return {
        "stage": "done",
        "program": module.program,
        "run_id": str(run.id),
        "status": run.status,
        "cases": outcome.cases,
        "passed": outcome.passed,
        "failed": outcome.failed,
        "coverage_pct": outcome.coverage_pct,
        "mutation_score": outcome.mutation_score,
        "module_state": module.state,
        **outcome.metrics,
    }


def run_mutate(db: Session, job: Job, settings: Settings) -> dict[str, Any]:
    module = _module(db, job)
    artifact = db.get(CodeArtifact, module.current_artifact_id) if module.current_artifact_id else None
    base = modules.latest_run(db, module.id)
    if artifact is None or artifact.build_status != "BUILT" or base is None or base.artifact_id != artifact.id:
        raise JobFailed("NO_VERIFIED_ARTIFACT")
    if base.failed:
        raise JobFailed("EQUIVALENCE_NOT_PASSED")
    project = db.get(Project, module.project_id)
    if project is None:
        raise JobFailed("PROJECT_NOT_FOUND")
    legacy = get_legacy_runner(settings)
    set_stage(db, job, "generating inputs")
    try:
        _block, cases, _rules = prepare_cases(db, module, project, settings, legacy, base.seed, base.cases)
        records = [case.record for case in cases]
        outputs = legacy.call(module.program, records).outputs
    except (VerificationError, SandboxError) as exc:
        raise JobFailed(exc.code) from None
    set_stage(db, job, "mutation testing")
    mutation = run_mutation(get_modern_builder(settings), list(artifact.files), records, outputs)
    score = mutation.get("score")
    limits = gates.thresholds(db, module.id, settings)
    gate = {
        "gate": "MUTATION",
        "label": "Mutation score",
        "passed": score is not None and score >= limits.mutation,
        "value": score,
        "threshold": limits.mutation,
        "unit": "%",
    }
    run = VerificationRun(
        module_id=module.id,
        artifact_id=artifact.id,
        job_id=job.id,
        kind="MUTATION",
        base_run_id=base.id,
        seed=base.seed,
        cases=len(records),
        passed=base.passed,
        failed=base.failed,
        coverage_pct=None,
        mutation_score=score,
        report={"mutation": mutation, "base_run_id": str(base.id), "seed": base.seed},
        gates=[gate],
        status="PASSED" if gate["passed"] else "FAILED",
    )
    db.add(run)
    db.flush()
    audit.record(
        db,
        "mutation.recorded",
        actor_id=job.requested_by,
        entity_type="module",
        entity_id=module.id,
        metadata={"run_id": str(run.id), "score": score, "base_run_id": str(base.id)},
    )
    return {"stage": "done", "run_id": str(run.id), "mutation_score": score, "program": module.program}


# --- SHADOW: replay recorded traffic through the facade ---


def _wait_for_shadow_route(client: httpx.Client, program: str) -> None:
    """The facade reads its route table every few seconds. Until it routes this module through
    shadow, requests would skip the comparison, so wait for it."""
    for _ in range(ROUTE_WAIT_SECONDS):
        try:
            if client.get("/routes").json().get("modules", {}).get(program) == "SHADOW":
                return
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(1)
    raise JobFailed("FACADE_NOT_ROUTING")


def facade_client(settings: Settings) -> httpx.Client:
    """The public facade API, as any client sees it. The first modern call can build the artifact."""
    return httpx.Client(base_url=settings.facade_url, timeout=180)


def run_shadow(db: Session, job: Job, settings: Settings) -> dict[str, Any]:
    """Send recorded BillRite requests through the real facade while the module is in shadow mode.

    The facade runs legacy and modern for each one, answers with legacy, and reports the
    comparison back to the internal API, which records it. This job only sends the traffic,
    and holds no lock on the module while it does, because those reports update it.
    """
    module = db.get(Module, _module_id(job))
    if module is None or module.project_id != job.project_id:
        raise JobFailed("MODULE_NOT_FOUND")
    if module.facade_mode != "SHADOW":
        raise JobFailed("NOT_IN_SHADOW")
    project = db.get(Project, module.project_id)
    if project is None or project.source_kind != "BUNDLED":
        raise JobFailed("UPLOAD_NOT_EXECUTABLE")
    count = int(job.payload.get("count", settings.shadow_sample_size))
    set_stage(db, job, "reading recorded traffic")
    try:
        block = migration_block(load_migration_context(db, module.project_id, module.program))
        billfile = get_legacy_runner(settings).billrun()
    except SandboxError as exc:
        raise JobFailed(exc.code) from None
    recorded = recorded_inputs(module.program, block, Path(settings.billrite_path), billfile)
    requests = [body for body in (request_for(module.program, record) for record in recorded) if body is not None]
    if not requests:
        raise JobFailed("NO_RECORDED_TRAFFIC")
    start = module.shadow_compared % len(requests)
    chosen = [requests[(start + index) % len(requests)] for index in range(count)]
    program, path = module.program, ENDPOINTS[module.program]
    db.commit()
    answered = 0
    routes: dict[str, int] = {}
    with facade_client(settings) as client:
        set_stage(db, job, "waiting for the facade to route through shadow")
        _wait_for_shadow_route(client, program)
        set_stage(db, job, f"sending {count} requests through the facade")
        for body in chosen:
            try:
                response = client.post(path, json=body)
            except httpx.HTTPError:
                raise JobFailed("FACADE_UNAVAILABLE") from None
            route = response.headers.get("X-Offshoot-Route", "unknown")
            routes[route] = routes.get(route, 0) + 1
            if response.status_code == HTTP_OK:
                answered += 1
    db.expire_all()
    module = db.get(Module, module.id)
    if module is None:
        raise JobFailed("MODULE_NOT_FOUND")
    status = shadow_status(db, module, settings)
    return {
        "stage": "done",
        "program": program,
        "sent": count,
        "answered": answered,
        "routes": routes,
        "shadow_compared": status.compared,
        "shadow_mismatches": status.mismatches,
        "shadow_ready": status.ready,
    }


HANDLERS = {
    "SHADOW": run_shadow,
    "PLAN": run_plan,
    "MIGRATE": run_migrate,
    "REPAIR": run_repair,
    "VERIFY": run_verify,
    "MUTATE": run_mutate,
}
