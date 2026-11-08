"""Verification gates (Blueprint Section 7.2), evaluated on the server only.

A module is verifiable-pass only if: the build and analyzers succeed, the unit tests pass,
equivalence is 100% of the cases, legacy paragraph coverage is at or above its threshold,
and the mutation score is at or above its threshold. Thresholds come from settings, and an
architect may lower the coverage or mutation threshold of one module with a recorded reason
(a gate exception). Build, tests and equivalence can never be excepted.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import CodeArtifact, GateException, User

EXCEPTABLE = ("COVERAGE", "MUTATION")


@dataclass(frozen=True)
class Thresholds:
    coverage: float
    mutation: float
    exceptions: dict[str, dict[str, Any]]


def thresholds(db: Session, module_id: uuid.UUID, settings: Settings) -> Thresholds:
    """The defaults, lowered by the latest exception for each gate, if any."""
    rows = db.scalars(
        select(GateException)
        .where(GateException.module_id == module_id)
        .order_by(GateException.created_at.desc(), GateException.id)
    ).all()
    latest: dict[str, GateException] = {}
    for row in rows:
        latest.setdefault(row.gate, row)
    names = {}
    if latest:
        actor_ids = {row.actor_id for row in latest.values()}
        names = {row.id: row.display_name for row in db.scalars(select(User).where(User.id.in_(actor_ids)))}
    exceptions = {
        gate: {
            "threshold": row.threshold,
            "reason": row.reason,
            "by": names.get(row.actor_id),
            "at": row.created_at.isoformat() if row.created_at else None,
        }
        for gate, row in latest.items()
    }
    return Thresholds(
        coverage=latest["COVERAGE"].threshold if "COVERAGE" in latest else settings.coverage_threshold,
        mutation=latest["MUTATION"].threshold if "MUTATION" in latest else settings.mutation_threshold,
        exceptions=exceptions,
    )


def evaluate(
    artifact: CodeArtifact,
    cases: int,
    failed: int,
    coverage_pct: float | None,
    mutation_score: float | None,
    limits: Thresholds,
) -> list[dict[str, Any]]:
    report = artifact.build_report or {}
    build = report.get("build") or {}
    tests = report.get("tests") or {}
    equivalence = round((cases - failed) * 100.0 / cases, 2) if cases else 0.0
    gates = [
        {
            "gate": "BUILD",
            "label": "Build and analyzers",
            "passed": bool(build.get("ok")) and not build.get("errors") and artifact.build_status != "PENDING",
            "value": build.get("errors", 0),
            "threshold": 0,
            "unit": "errors",
        },
        {
            "gate": "UNIT_TESTS",
            "label": "Unit tests",
            "passed": bool(tests.get("ok")) and tests.get("failed", 1) == 0 and tests.get("total", 0) > 0,
            "value": tests.get("passed", 0),
            "threshold": tests.get("total", 0),
            "unit": "tests passed",
        },
        {
            "gate": "EQUIVALENCE",
            "label": "Equivalence",
            "passed": cases > 0 and failed == 0,
            "value": equivalence,
            "threshold": 100.0,
            "unit": "% of cases",
        },
        {
            "gate": "COVERAGE",
            "label": "Legacy paragraph coverage",
            "passed": coverage_pct is not None and coverage_pct >= limits.coverage,
            "value": coverage_pct,
            "threshold": limits.coverage,
            "unit": "%",
        },
        {
            "gate": "MUTATION",
            "label": "Mutation score",
            "passed": mutation_score is not None and mutation_score >= limits.mutation,
            "value": mutation_score,
            "threshold": limits.mutation,
            "unit": "%",
        },
    ]
    for gate in gates:
        exception = limits.exceptions.get(gate["gate"])
        if exception is not None:
            gate["exception"] = exception
    return gates


def all_passed(gates: list[dict[str, Any]]) -> bool:
    return bool(gates) and all(gate["passed"] for gate in gates)


def first_failure(gates: list[dict[str, Any]]) -> str | None:
    failed = next((gate for gate in gates if not gate["passed"]), None)
    return f"{failed['gate']}_FAILED" if failed else None
