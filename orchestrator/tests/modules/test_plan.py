"""The plan (F06): the model proposes services and risks, the call graph decides the order,
and only an architect approves, with expected_version and an audit entry.
"""

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AiCall, Approval, AuditLog, Module, Plan
from app.services.agent.contracts import PlanOutput
from app.services.agent.mock import FIXTURES, MockAgent
from app.services.jobs import module_handlers
from tests.agent.helpers import analyze, make_project, run_jobs
from tests.conftest import UserFactory
from tests.modules.helpers import Actors, approve_plan, propose_plan

ORDER = ["MTRVAL", "RATECALC", "LATEFEE", "STMTGEN", "BILLRUN"]


@pytest.fixture
def actors(client: TestClient, make_user: UserFactory) -> Actors:
    return Actors(client, make_user)


@pytest.fixture
def analyzed(client: TestClient, db: Session, actors: Actors) -> uuid.UUID:
    project = make_project(db, "BUNDLED")
    analyze(client, actors.engineer, project.id)
    return project.id


def test_the_order_comes_from_the_call_graph(client: TestClient, actors: Actors, analyzed: uuid.UUID) -> None:
    plan = propose_plan(client, actors, analyzed)
    assert [step["program"] for step in plan["order"]] == ORDER
    assert [step["position"] for step in plan["order"]] == [1, 2, 3, 4, 5]
    assert plan["order"][-1]["depends_on"] == ["LATEFEE", "MTRVAL", "RATECALC", "STMTGEN"]
    assert {step["service"] for step in plan["order"]} == {"meter-service", "billing-service", "statement-service"}
    assert plan["state"] == "PROPOSED"
    assert plan["version"] == 1
    assert plan["prompt_version"] == "plan-v1"


def test_the_estimate_and_signals_are_measured_not_proposed(
    client: TestClient, actors: Actors, analyzed: uuid.UUID
) -> None:
    plan = propose_plan(client, actors, analyzed)
    fixture = json.loads((FIXTURES / "plan_v1" / "plan.json").read_text())
    assert "estimate" not in fixture and "order" not in fixture
    modules = {row["program"]: row for row in plan["estimate"]["modules"]}
    assert set(modules) == set(ORDER)
    assert modules["RATECALC"]["traps"] > 0
    assert plan["estimate"]["total_points"] == round(sum(row["points"] for row in modules.values()), 1)
    signals = {(item["program"], item["signal"]) for item in plan["signals"]["risk_signals"]}
    assert ("RATECALC", "COMPUTE ROUNDED sites") in signals
    assert ("LATEFEE", "date intrinsic functions") in signals
    assert ("BILLRUN", "GO TO statements") in signals


def test_a_model_cannot_set_the_order() -> None:
    proposal = json.loads((FIXTURES / "plan_v1" / "plan.json").read_text())
    with pytest.raises(ValueError, match="Extra inputs"):
        PlanOutput.model_validate({**proposal, "order": ["STMTGEN", "MTRVAL"]})


def _plan_root(tmp_path: Path, change: dict[str, Any]) -> Path:
    root = tmp_path / "workflow"
    shutil.copytree(FIXTURES, root)
    path = root / "plan_v1" / "plan.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), **change}))
    return root


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (
            {"services": [{"name": "everything", "description": "One service for all of it.", "programs": ["MTRVAL"]}]},
            "PLAN_PROGRAMS_MISMATCH",
        ),
        (
            {
                "services": [
                    {"name": "a-service", "description": "Has an invented program.", "programs": ["MTRVAL", "PAYROLL"]},
                    {
                        "name": "b-service",
                        "description": "The rest of the programs.",
                        "programs": ["RATECALC", "LATEFEE", "STMTGEN", "BILLRUN"],
                    },
                ]
            },
            "PLAN_UNKNOWN_PROGRAM",
        ),
        ({"approved": True}, "AI_INVALID_OUTPUT"),
    ],
)
def test_an_invalid_proposal_fails_the_job_and_stores_nothing(
    client: TestClient,
    db: Session,
    actors: Actors,
    analyzed: uuid.UUID,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: dict[str, Any],
    code: str,
) -> None:
    root = _plan_root(tmp_path, change)
    monkeypatch.setattr(module_handlers, "get_agent_provider", lambda _settings: MockAgent(workflow_root=root))
    response = client.post(f"/api/v1/projects/{analyzed}/plan", headers=actors.engineer)
    run_jobs()
    job = client.get(f"/api/v1/jobs/{response.json()['id']}", headers=actors.viewer).json()
    assert (job["status"], job["error_code"]) == ("FAILED", code)
    assert db.scalar(select(func.count()).select_from(Plan).where(Plan.project_id == analyzed)) == 0
    calls = db.scalars(select(AiCall).where(AiCall.job_id == uuid.UUID(job["id"]))).all()
    assert [call.prompt_version for call in calls] == ["plan-v1"]


def test_a_plan_needs_an_analysis(client: TestClient, db: Session, actors: Actors) -> None:
    project = make_project(db, "BUNDLED")
    response = client.post(f"/api/v1/projects/{project.id}/plan", headers=actors.engineer)
    assert (response.status_code, response.json()["error"]["code"]) == (409, "NOT_ANALYZED")


def test_an_empty_project_has_no_plan_yet(client: TestClient, actors: Actors, analyzed: uuid.UUID) -> None:
    body = client.get(f"/api/v1/projects/{analyzed}/plan", headers=actors.viewer).json()
    assert body == {"plan": None, "history": []}


def test_roles_are_enforced_on_the_server(
    client: TestClient, actors: Actors, analyzed: uuid.UUID, make_user: UserFactory
) -> None:
    from tests.conftest import bearer, login_as

    admin = bearer(login_as(client, make_user("ADMIN")))
    for headers in (actors.viewer, admin):
        assert client.post(f"/api/v1/projects/{analyzed}/plan", headers=headers).status_code == 403
    plan = propose_plan(client, actors, analyzed)
    body = {"decision": "APPROVED", "expected_version": plan["version"]}
    for headers in (actors.viewer, actors.engineer, admin):
        response = client.post(f"/api/v1/projects/{analyzed}/plan/decision", json=body, headers=headers)
        assert response.status_code == 403
    assert client.post(f"/api/v1/projects/{analyzed}/plan").status_code == 401


def test_approval_is_audited_creates_the_modules_and_cannot_repeat(
    client: TestClient, db: Session, actors: Actors, analyzed: uuid.UUID
) -> None:
    plan = propose_plan(client, actors, analyzed)
    approved = approve_plan(client, actors, analyzed, plan["version"])
    assert approved["state"] == "APPROVED"
    assert approved["decided_by_name"] == "Test Architect"
    modules = client.get(f"/api/v1/projects/{analyzed}/modules", headers=actors.viewer).json()
    assert [(m["program"], m["order_index"], m["state"], m["facade_mode"]) for m in modules] == [
        (program, index, "PENDING", "LEGACY") for index, program in enumerate(ORDER, start=1)
    ]
    assert [m["migratable"] for m in modules] == [True, True, True, True, False]
    approval = db.scalars(select(Approval).where(Approval.entity_id == uuid.UUID(plan["id"]))).one()
    assert approval.decision == "APPROVED"
    entry = db.scalars(
        select(AuditLog).where(AuditLog.action == "plan.decision", AuditLog.entity_id == plan["id"])
    ).one()
    assert entry.safe_metadata["modules_created"] == ORDER
    again = client.post(
        f"/api/v1/projects/{analyzed}/plan/decision",
        json={"decision": "APPROVED", "expected_version": plan["version"]},
        headers=actors.architect,
    )
    assert (again.status_code, again.json()["error"]["code"]) == (409, "ALREADY_DECIDED")


def test_a_stale_version_is_refused(client: TestClient, actors: Actors, analyzed: uuid.UUID) -> None:
    first = propose_plan(client, actors, analyzed)
    second = propose_plan(client, actors, analyzed)
    assert second["version"] == first["version"] + 1
    response = client.post(
        f"/api/v1/projects/{analyzed}/plan/decision",
        json={"decision": "APPROVED", "expected_version": first["version"]},
        headers=actors.architect,
    )
    assert (response.status_code, response.json()["error"]["code"]) == (409, "STALE_VERSION")


def test_a_rejection_needs_a_reason_and_creates_nothing(
    client: TestClient, db: Session, actors: Actors, analyzed: uuid.UUID
) -> None:
    plan = propose_plan(client, actors, analyzed)
    url = f"/api/v1/projects/{analyzed}/plan/decision"
    body = {"decision": "REJECTED", "expected_version": plan["version"]}
    assert client.post(url, json=body, headers=actors.architect).status_code == 422
    response = client.post(url, json={**body, "reason": "Split billing further."}, headers=actors.architect)
    assert response.status_code == 200
    assert response.json()["decision_reason"] == "Split billing further."
    assert db.scalar(select(func.count()).select_from(Module).where(Module.project_id == analyzed)) == 0


def test_re_approving_a_new_plan_keeps_module_history(
    client: TestClient, db: Session, actors: Actors, analyzed: uuid.UUID
) -> None:
    approve_plan(client, actors, analyzed, propose_plan(client, actors, analyzed)["version"])
    before = {m.program: m.id for m in db.scalars(select(Module).where(Module.project_id == analyzed))}
    approve_plan(client, actors, analyzed, propose_plan(client, actors, analyzed)["version"])
    db.expire_all()
    after = {m.program: m.id for m in db.scalars(select(Module).where(Module.project_id == analyzed))}
    assert before == after
