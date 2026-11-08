"""The overview dashboard and the assessment report (F10, Blueprint Sections 10 and 3.1).

Every number here is read from stored rows: modules, verification runs, rules, approvals,
jobs and AI calls. Nothing is estimated or copied from an example. Decisions made by the
seed are counted separately from human ones, because they are not reviews (ADR-024).
"""

import uuid
from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (
    AiCall,
    Approval,
    InventoryItem,
    Job,
    Module,
    Plan,
    Project,
    Rule,
    SourceFile,
    User,
)
from app.services import modules as module_service
from app.services import promotion

SEED_MARKER = "Demo seed decision"
ACTIVITY_LIMIT = 15


def _approvals(db: Session, project_id: uuid.UUID) -> list[tuple[Approval, str, str]]:
    """Approvals on this project's rules, plans and modules, with the entity's label."""
    labels: dict[uuid.UUID, tuple[str, str]] = {}
    for rule in db.scalars(select(Rule).where(Rule.project_id == project_id)):
        labels[rule.id] = ("rule", f"{rule.program}: {rule.title}")
    for plan in db.scalars(select(Plan).where(Plan.project_id == project_id)):
        labels[plan.id] = ("plan", f"plan version {plan.version}")
    for module in db.scalars(select(Module).where(Module.project_id == project_id)):
        labels[module.id] = ("module", module.program)
    if not labels:
        return []
    rows = db.scalars(select(Approval).where(Approval.entity_id.in_(labels)).order_by(Approval.created_at.desc()))
    return [(row, *labels[row.entity_id]) for row in rows]


def dashboard(db: Session, project: Project, settings: Settings) -> dict[str, Any]:
    modules = list(db.scalars(select(Module).where(Module.project_id == project.id).order_by(Module.order_index)))
    rule_states = Counter(
        dict(
            db.execute(select(Rule.state, func.count()).where(Rule.project_id == project.id).group_by(Rule.state)).all()
        )
    )
    total_rules = sum(rule_states.values())
    approvals = _approvals(db, project.id)
    rule_decisions = [row for row, kind, _ in approvals if kind == "rule"]
    seeded = sum(1 for row in rule_decisions if (row.reason or "").startswith(SEED_MARKER))

    rows = []
    for module in modules:
        run = module_service.latest_run(db, module.id)
        status = promotion.shadow_status(db, module, settings)
        rows.append(
            {
                "id": str(module.id),
                "program": module.program,
                "service": module.target_service,
                "state": module.state,
                "facade_mode": module.facade_mode,
                "cases": run.cases if run else None,
                "passed": run.passed if run else None,
                "failed": run.failed if run else None,
                "coverage_pct": run.coverage_pct if run else None,
                "mutation_score": run.mutation_score if run else None,
                "run_id": str(run.id) if run else None,
                "shadow_compared": status.compared,
                "shadow_mismatches": status.mismatches,
            }
        )
    with_runs = [row for row in rows if row["cases"]]
    calls = db.execute(
        select(AiCall.mode, AiCall.status, AiCall.tokens)
        .join(Job, Job.id == AiCall.job_id)
        .where(Job.project_id == project.id)
    ).all()
    tokens_in = sum(
        int((tokens or {}).get("input") or (tokens or {}).get("input_estimate") or 0) for _, _, tokens in calls
    )
    tokens_out = sum(int((tokens or {}).get("output") or 0) for _, _, tokens in calls)
    cost = sum(float((tokens or {}).get("cost_usd") or 0) for _, _, tokens in calls)
    return {
        "project": {"id": str(project.id), "name": project.name, "source_kind": project.source_kind},
        "modules": rows,
        "modules_by_state": dict(Counter(module.state for module in modules)),
        "facade_modes": dict(Counter(module.facade_mode for module in modules)),
        "rules": {
            "total": total_rules,
            "by_state": dict(rule_states),
            "verified": rule_states.get("VERIFIED", 0),
            "verified_pct": round(rule_states.get("VERIFIED", 0) * 100.0 / total_rules, 2) if total_rules else None,
            "decisions": len(rule_decisions),
            "seeded_decisions": seeded,
            "human_decisions": len(rule_decisions) - seeded,
        },
        "equivalence": {
            "modules_verified": len(with_runs),
            "cases": sum(row["cases"] for row in with_runs),
            "identical": sum(row["passed"] for row in with_runs),
        },
        "ai": {
            "calls": len(calls),
            "failed": sum(1 for _, status, _ in calls if status == "FAILED"),
            "by_mode": dict(Counter(mode for mode, _, _ in calls)),
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "estimated_cost_usd": round(cost, 4),
            "note": "Mock calls cost nothing; their input tokens are estimated from prompt length.",
        },
        "activity": activity(db, project.id, approvals),
    }


def activity(db: Session, project_id: uuid.UUID, approvals: list[tuple[Approval, str, str]]) -> list[dict[str, Any]]:
    jobs = db.scalars(
        select(Job).where(Job.project_id == project_id).order_by(Job.created_at.desc()).limit(ACTIVITY_LIMIT)
    ).all()
    actor_ids = {job.requested_by for job in jobs if job.requested_by} | {row.actor_id for row, _, _ in approvals}
    names = (
        dict(db.execute(select(User.id, User.display_name).where(User.id.in_(actor_ids))).all()) if actor_ids else {}
    )
    events: list[tuple[datetime, dict[str, Any]]] = []
    for job in jobs:
        program = job.payload.get("program")
        events.append(
            (
                job.ended_at or job.created_at,
                {
                    "kind": "job",
                    "what": f"{job.kind.lower()} {program}" if program else job.kind.lower(),
                    "outcome": job.status if not job.error_code else f"{job.status} ({job.error_code})",
                    "by": names.get(job.requested_by) if job.requested_by else None,
                    "at": (job.ended_at or job.created_at).isoformat(),
                },
            )
        )
    for row, kind, label in approvals[:ACTIVITY_LIMIT]:
        events.append(
            (
                row.created_at,
                {
                    "kind": "decision",
                    "what": f"{kind} {label}",
                    "outcome": row.decision,
                    "by": names.get(row.actor_id),
                    "seeded": (row.reason or "").startswith(SEED_MARKER),
                    "at": row.created_at.isoformat(),
                },
            )
        )
    events.sort(key=lambda item: item[0], reverse=True)
    return [event for _, event in events[:ACTIVITY_LIMIT]]


# --- The assessment report: As-Is, To-Be, Transition ---


def _table(columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    return {"columns": columns, "rows": [["" if cell is None else str(cell) for cell in row] for row in rows]}


def report(db: Session, project: Project, settings: Settings) -> dict[str, Any]:
    data = dashboard(db, project, settings)
    programs = db.scalars(
        select(InventoryItem)
        .where(InventoryItem.project_id == project.id, InventoryItem.kind == "PROGRAM")
        .order_by(InventoryItem.name)
    ).all()
    files = db.scalar(select(func.count()).select_from(SourceFile).where(SourceFile.project_id == project.id)) or 0
    rules_by_program = dict(
        db.execute(
            select(Rule.program, func.count())
            .where(Rule.project_id == project.id, Rule.state == "VERIFIED")
            .group_by(Rule.program)
        ).all()
    )
    dead = db.scalars(
        select(InventoryItem.name).where(
            InventoryItem.project_id == project.id,
            InventoryItem.kind == "PARAGRAPH",
            InventoryItem.attrs["dead"].as_boolean(),
        )
    ).all()
    plan = promotion_plan(db, project.id)
    as_is = {
        "heading": "As-Is: the legacy application",
        "paragraphs": [
            f"{project.name}: {len(programs)} programs in {files} source files. "
            f"Rules: {data['rules']['total']} extracted, {data['rules']['verified']} verified "
            f"({data['rules']['seeded_decisions']} of the rule decisions are labelled demo seed decisions, "
            f"{data['rules']['human_decisions']} were made by people).",
            "Dead paragraphs: " + (", ".join(sorted(dead)) if dead else "none") + ".",
        ],
        "tables": [
            _table(
                ["Program", "Lines", "Paragraphs", "Decisions", "GO TO", "Verified rules"],
                [
                    [
                        item.name,
                        item.attrs.get("metrics", {}).get("lines"),
                        item.attrs.get("metrics", {}).get("working_paragraphs"),
                        item.attrs.get("metrics", {}).get("decisions"),
                        item.attrs.get("metrics", {}).get("go_tos"),
                        rules_by_program.get(item.name, 0),
                    ]
                    for item in programs
                ],
            )
        ],
    }
    to_be = {
        "heading": "To-Be: target services and verified modules",
        "paragraphs": [
            "Equivalence is decided by running the real legacy program and the generated module on the same "
            "seeded cases and comparing every output field exactly. The numbers below are the latest stored run "
            "of each module.",
        ],
        "tables": [
            _table(
                ["Service", "Programs"],
                [[service["name"], ", ".join(service["programs"])] for service in (plan.services if plan else [])],
            ),
            _table(
                ["Module", "State", "Identical cases", "Coverage", "Mutation score"],
                [
                    [
                        row["program"],
                        row["state"],
                        f"{row['passed']} of {row['cases']}" if row["cases"] else "not verified",
                        f"{row['coverage_pct']:.2f}%" if row["coverage_pct"] is not None else "",
                        f"{row['mutation_score']:.2f}%" if row["mutation_score"] is not None else "",
                    ]
                    for row in data["modules"]
                ],
            ),
        ],
    }
    blocked = [row for row in data["modules"] if row["state"] in ("BLOCKED", "BUILD_FAILED")]
    transition = {
        "heading": "Transition: order, routing and open items",
        "paragraphs": [
            "Modules move legacy, then shadow (both run, legacy answers, differences are recorded), then modern, "
            f"and only after zero mismatches over {settings.shadow_sample_size} compared requests.",
            "Open items: "
            + (
                "; ".join(f"{row['program']} is {row['state'].lower().replace('_', ' ')}" for row in blocked)
                if blocked
                else "no blocked modules"
            )
            + f"; {data['rules']['total'] - data['rules']['verified']} rules not verified.",
        ],
        "tables": [
            _table(
                ["Step", "Program", "Service", "Routing", "Shadow compared", "Shadow mismatches"],
                [
                    [
                        step["position"],
                        step["program"],
                        step["service"],
                        next((row["facade_mode"] for row in data["modules"] if row["program"] == step["program"]), ""),
                        next(
                            (row["shadow_compared"] for row in data["modules"] if row["program"] == step["program"]), ""
                        ),
                        next(
                            (row["shadow_mismatches"] for row in data["modules"] if row["program"] == step["program"]),
                            "",
                        ),
                    ]
                    for step in (plan.order if plan else [])
                ],
            ),
            _table(
                ["Risk", "Severity", "Programs"],
                [
                    [risk["title"], risk["severity"], ", ".join(risk["programs"])]
                    for risk in (plan.risks if plan else [])
                ],
            ),
        ],
    }
    sections = [as_is, to_be, transition]
    title = f"{project.name} modernization assessment"
    limits = (
        "Limits: equivalence is proven only over the tested inputs. In mock mode the C# comes from recorded "
        "fixtures, not a model, so these numbers measure the pipeline."
    )
    return {"title": title, "sections": sections, "limits": limits, "markdown": to_markdown(title, sections, limits)}


def promotion_plan(db: Session, project_id: uuid.UUID) -> Plan | None:
    return db.scalar(
        select(Plan)
        .where(Plan.project_id == project_id, Plan.state == "APPROVED")
        .order_by(Plan.version.desc())
        .limit(1)
    )


def _escape(cell: str) -> str:
    return cell.replace("|", "\\|").replace("\n", " ")


def to_markdown(title: str, sections: list[dict[str, Any]], limits: str) -> str:
    lines = [f"# {title}", ""]
    for section in sections:
        lines += [f"## {section['heading']}", ""]
        for paragraph in section["paragraphs"]:
            lines += [paragraph, ""]
        for table in section["tables"]:
            if not table["rows"]:
                continue
            lines.append("| " + " | ".join(table["columns"]) + " |")
            lines.append("|" + "---|" * len(table["columns"]))
            lines += ["| " + " | ".join(_escape(cell) for cell in row) + " |" for row in table["rows"]]
            lines.append("")
    lines += [f"_{limits}_", ""]
    return "\n".join(lines)
