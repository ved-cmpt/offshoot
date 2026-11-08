"""The modernization plan (F06): the agent proposes services and risks, the server computes
the migration order from the call graph and the estimate from measured metrics, and an
architect approves or rejects it. Approval creates the modules.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.db.models import Approval, InventoryEdge, InventoryItem, Job, Module, Plan, User
from app.services import audit
from app.services.agent.context import PlanContext
from app.services.agent.contracts import PlanOutput

PlanDecisionValue = Literal["APPROVED", "REJECTED"]
ESTIMATE_METHOD = (
    "Relative effort points from measured metrics: code lines / 25, plus decisions / 4, plus 2 per "
    "PERFORM THRU, GO TO, ROUNDED, REDEFINES and date function, plus 1 per verified rule. "
    "Points compare modules with each other; they are not hours."
)


class PlanInvalid(Exception):
    """The model's proposal does not match the inventory. Nothing is stored."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def migration_order(db: Session, project_id: uuid.UUID) -> list[dict[str, Any]]:
    """Callees before callers, from the CALLS edges. Ties keep the order the caller calls them in."""
    programs = {
        item.id: item.name
        for item in db.scalars(
            select(InventoryItem).where(InventoryItem.project_id == project_id, InventoryItem.kind == "PROGRAM")
        )
    }
    paragraph_program = {
        item.id: str(item.attrs.get("program"))
        for item in db.scalars(
            select(InventoryItem).where(InventoryItem.project_id == project_id, InventoryItem.kind == "PARAGRAPH")
        )
    }
    callees: dict[str, set[str]] = {name: set() for name in programs.values()}
    first_call: dict[str, int] = {}
    for edge in db.scalars(
        select(InventoryEdge).where(InventoryEdge.project_id == project_id, InventoryEdge.kind == "CALLS")
    ):
        caller = paragraph_program.get(edge.from_item)
        callee = programs.get(edge.to_item)
        if caller is None or callee is None or caller == callee:
            continue
        callees.setdefault(caller, set()).add(callee)
        line = int(edge.attrs.get("line", 0))
        first_call[callee] = min(first_call.get(callee, line), line)

    order: list[dict[str, Any]] = []
    placed: set[str] = set()
    remaining = set(callees)
    while remaining:
        ready = [name for name in remaining if callees[name] <= placed]
        if not ready:  # A call cycle. Break it deterministically rather than fail.
            ready = [min(remaining)]
        ready.sort(key=lambda name: (first_call.get(name, 1_000_000), name))
        for name in ready:
            order.append(
                {
                    "position": len(order) + 1,
                    "program": name,
                    "depends_on": sorted(callees[name]),
                    "reason": (
                        f"Calls {', '.join(sorted(callees[name]))}, so it moves after them."
                        if callees[name]
                        else "Calls no other program."
                    ),
                }
            )
            placed.add(name)
            remaining.discard(name)
    return order


def risk_signals(context: PlanContext) -> list[dict[str, Any]]:
    """Facts from static analysis that the plan's risks should account for."""
    labels = {
        "performs_thru": "PERFORM THRU ranges",
        "go_tos": "GO TO statements",
        "dead_paragraphs": "dead paragraphs",
    }
    keyword_labels = {
        "ROUNDED": "COMPUTE ROUNDED sites",
        "REDEFINES": "REDEFINES overlays",
        "DATE_FUNCTIONS": "date intrinsic functions",
        "EDITED_PICTURES": "edited print pictures",
    }
    signals = []
    for program in context.programs:
        for key, label in labels.items():
            if program.metrics.get(key):
                signals.append({"program": program.name, "signal": label, "detail": f"{program.metrics[key]} found"})
        for key, label in keyword_labels.items():
            if program.keywords.get(key):
                signals.append({"program": program.name, "signal": label, "detail": f"{program.keywords[key]} found"})
        if program.rules_total and program.rules_verified < program.rules_total:
            signals.append(
                {
                    "program": program.name,
                    "signal": "rules not yet verified",
                    "detail": f"{program.rules_total - program.rules_verified} of {program.rules_total}",
                }
            )
    return signals


def estimate(context: PlanContext) -> dict[str, Any]:
    modules: list[dict[str, Any]] = []
    for program in context.programs:
        metrics, keywords = program.metrics, program.keywords
        traps = (
            metrics.get("performs_thru", 0)
            + metrics.get("go_tos", 0)
            + keywords.get("ROUNDED", 0)
            + keywords.get("REDEFINES", 0)
            + keywords.get("DATE_FUNCTIONS", 0)
        )
        points = round(metrics.get("code_lines", 0) / 25 + metrics.get("decisions", 0) / 4 + 2 * traps, 1)
        points = round(points + program.rules_verified, 1)
        modules.append(
            {
                "program": program.name,
                "code_lines": metrics.get("code_lines", 0),
                "decisions": metrics.get("decisions", 0),
                "traps": traps,
                "verified_rules": program.rules_verified,
                "points": points,
            }
        )
    return {
        "method": ESTIMATE_METHOD,
        "modules": modules,
        "total_points": round(sum(module["points"] for module in modules), 1),
    }


def validate_proposal(output: PlanOutput, context: PlanContext) -> None:
    known = {program.name for program in context.programs}
    assigned = [program.upper() for service in output.services for program in service.programs]
    names = [service.name for service in output.services]
    if len(set(names)) != len(names):
        raise PlanInvalid("PLAN_DUPLICATE_SERVICE")
    if set(assigned) - known:
        raise PlanInvalid("PLAN_UNKNOWN_PROGRAM")
    if len(assigned) != len(set(assigned)) or set(assigned) != known:
        raise PlanInvalid("PLAN_PROGRAMS_MISMATCH")
    for risk in output.risks:
        if {program.upper() for program in risk.programs} - known:
            raise PlanInvalid("PLAN_UNKNOWN_PROGRAM")


def persist_plan(
    db: Session,
    job: Job,
    output: PlanOutput,
    context: PlanContext,
    order: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    prompt_version: str,
    model_id: str | None,
) -> Plan:
    validate_proposal(output, context)
    service_of = {program.upper(): service.name for service in output.services for program in service.programs}
    latest = db.scalar(select(func.max(Plan.version)).where(Plan.project_id == job.project_id)) or 0
    plan = Plan(
        project_id=job.project_id,
        version=latest + 1,
        services=[
            {"name": s.name, "description": s.description, "programs": [p.upper() for p in s.programs]}
            for s in output.services
        ],
        order=[{**step, "service": service_of[step["program"]]} for step in order],
        risks=[risk.model_dump() for risk in output.risks],
        estimate=estimate(context),
        state="PROPOSED",
        job_id=job.id,
        prompt_version=prompt_version,
        model_id=model_id,
        model_output=output.model_dump(),
        signals={"risk_signals": signals, "notes": output.notes},
    )
    db.add(plan)
    db.flush()
    audit.record(
        db,
        "plan.proposed",
        entity_type="plan",
        entity_id=plan.id,
        metadata={"job_id": str(job.id), "version": plan.version, "model_id": model_id},
    )
    return plan


def latest_plan(db: Session, project_id: uuid.UUID, lock: bool = False) -> Plan | None:
    query = select(Plan).where(Plan.project_id == project_id).order_by(Plan.version.desc()).limit(1)
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def decide_plan(
    db: Session,
    project_id: uuid.UUID,
    actor: User,
    decision: PlanDecisionValue,
    reason: str | None,
    expected_version: int,
    settings: Settings,
    seeded: bool = False,
) -> Plan:
    plan = latest_plan(db, project_id, lock=True)
    if plan is None:
        raise ApiError(404, "NOT_FOUND", "There is no plan to decide on yet.")
    if plan.version != expected_version:
        raise ApiError(409, "STALE_VERSION", f"The plan has changed. Reload it: the latest is version {plan.version}.")
    if plan.state != "PROPOSED":
        raise ApiError(409, "ALREADY_DECIDED", f"This plan is already {plan.state.lower()}.")
    if decision == "REJECTED" and not (reason and reason.strip()):
        raise ApiError(422, "REASON_REQUIRED", "A rejection needs a reason.")
    del settings  # Plans have no proposal edits, so there is no self-approval case to refuse.

    plan.state = decision
    plan.decided_at = datetime.now(UTC)
    plan.approved_by = actor.id if decision == "APPROVED" else None
    db.add(Approval(entity_type="PLAN", entity_id=plan.id, decision=decision, reason=reason, actor_id=actor.id))
    created = _create_modules(db, plan) if decision == "APPROVED" else []
    metadata: dict[str, Any] = {"decision": decision, "version": plan.version, "modules_created": created}
    if seeded:
        metadata["seeded"] = True
    audit.record(db, "plan.decision", actor_id=actor.id, entity_type="plan", entity_id=plan.id, metadata=metadata)
    return plan


def _create_modules(db: Session, plan: Plan) -> list[str]:
    """One module per program, in plan order. An existing module keeps its state and history."""
    existing = {
        module.program: module for module in db.scalars(select(Module).where(Module.project_id == plan.project_id))
    }
    created = []
    for step in plan.order:
        module = existing.get(step["program"])
        if module is None:
            module = Module(project_id=plan.project_id, program=step["program"], state="PENDING", facade_mode="LEGACY")
            db.add(module)
            created.append(step["program"])
        module.target_service = step["service"]
        module.order_index = step["position"]
        module.plan_id = plan.id
    db.flush()
    return created
