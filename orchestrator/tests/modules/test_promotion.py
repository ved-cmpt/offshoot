"""Approval and strangler promotion (F09, Blueprint Sections 3.1 step 8, 7.3 and 14).

The facade itself is tested in C# and against the live stack; here a fake facade drives the
orchestrator's internal API exactly as the real one does, so every rule is checked on the
server with the test database.
"""

import os
import uuid
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Approval, AuditLog, Project
from app.services.jobs import module_handlers
from tests.agent.helpers import run_jobs
from tests.conftest import UserFactory
from tests.modules.helpers import Actors, detail, module_of, ready_project, start

TOKEN = {"X-Facade-Token": os.environ.get("FACADE_SHARED_SECRET", "")}
LEGACY = "E0000150Y "


@pytest.fixture
def actors(client: TestClient, make_user: UserFactory) -> Actors:
    return Actors(client, make_user)


@pytest.fixture
def verified(client: TestClient, db: Session, actors: Actors, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A VERIFIED MTRVAL module in a bundled project that the facade serves."""
    project_id = ready_project(client, db, actors, ("MTRVAL",))
    project = db.get(Project, project_id)
    assert project is not None
    monkeypatch.setattr(get_settings(), "facade_project", project.name)
    module = module_of(client, actors, project_id, "MTRVAL")
    assert start(client, actors, module["id"], "migrate")["status"] == "SUCCEEDED"
    found = detail(client, actors, module["id"])
    assert found["state"] == "VERIFIED" and found["approvable"] is True
    return found


def decide(client: TestClient, actors: Actors, module: dict[str, Any], decision: str, **extra: Any) -> httpx.Response:
    body = {"decision": decision, "expected_version": module["version"], **extra}
    response: httpx.Response = client.post(
        f"/api/v1/modules/{module['id']}/decision", json=body, headers=actors.architect
    )
    return response


def mode(client: TestClient, actors: Actors, module: dict[str, Any], value: str) -> httpx.Response:
    body = {"mode": value, "expected_version": module["version"]}
    response: httpx.Response = client.post(
        f"/api/v1/modules/{module['id']}/facade-mode", json=body, headers=actors.architect
    )
    return response


def code(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


def report(client: TestClient, legacy: str = LEGACY, modern: str = LEGACY) -> httpx.Response:
    body = {"program": "MTRVAL", "input": "+99950+00100A", "legacy": legacy, "modern": modern}
    response: httpx.Response = client.post("/api/v1/internal/facade/shadow", json=body, headers=TOKEN)
    return response


def approved_in_shadow(client: TestClient, actors: Actors, module: dict[str, Any]) -> dict[str, Any]:
    approved = decide(client, actors, module, "APPROVED")
    assert approved.status_code == 200, approved.text
    shadow = mode(client, actors, approved.json(), "SHADOW")
    assert shadow.status_code == 200, shadow.text
    found: dict[str, Any] = shadow.json()
    return found


# --- Approval ---


def test_only_an_architect_decides(
    client: TestClient, actors: Actors, verified: dict[str, Any], make_user: UserFactory
) -> None:
    from tests.conftest import bearer, login_as

    admin = bearer(login_as(client, make_user("ADMIN")))
    for headers in (actors.viewer, actors.engineer, admin):
        body = {"decision": "APPROVED", "expected_version": verified["version"]}
        response = client.post(f"/api/v1/modules/{verified['id']}/decision", json=body, headers=headers)
        assert code(response) == (403, "FORBIDDEN")


def test_approval_is_audited_and_cannot_repeat(
    client: TestClient, db: Session, actors: Actors, verified: dict[str, Any]
) -> None:
    stale = decide(client, actors, {**verified, "version": verified["version"] - 1}, "APPROVED")
    assert code(stale) == (409, "STALE_VERSION")
    response = decide(client, actors, verified, "APPROVED")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "APPROVED"
    assert body["decision"]["by"] == "Test Architect"
    module_id = uuid.UUID(verified["id"])
    assert db.scalars(select(Approval).where(Approval.entity_id == module_id)).one().decision == "APPROVED"
    entry = db.scalars(
        select(AuditLog).where(AuditLog.action == "module.decision", AuditLog.entity_id == str(module_id))
    ).one()
    assert entry.safe_metadata["decision"] == "APPROVED"
    assert code(decide(client, actors, body, "APPROVED")) == (409, "ALREADY_DECIDED")
    # Approved code is not migrated or repaired again behind the approval.
    assert code(client.post(f"/api/v1/modules/{verified['id']}/migrate", headers=actors.engineer)) == (
        409,
        "INVALID_STATE",
    )


def test_a_blocked_module_cannot_be_approved(client: TestClient, db: Session, actors: Actors) -> None:
    project_id = ready_project(client, db, actors, ("RATECALC",))
    module = module_of(client, actors, project_id, "RATECALC")
    start(client, actors, module["id"], "migrate")
    blocked = detail(client, actors, module["id"])
    assert blocked["state"] == "BLOCKED" and blocked["approvable"] is False
    assert code(decide(client, actors, blocked, "APPROVED")) == (409, "VERIFICATION_REQUIRED")


def test_a_pending_module_cannot_be_approved(client: TestClient, db: Session, actors: Actors) -> None:
    project_id = ready_project(client, db, actors, ("MTRVAL",))
    module = detail(client, actors, module_of(client, actors, project_id, "MTRVAL")["id"])
    assert code(decide(client, actors, module, "APPROVED")) == (409, "VERIFICATION_REQUIRED")


def test_approval_rechecks_the_gates_under_todays_thresholds(
    client: TestClient, actors: Actors, verified: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "mutation_threshold", 99.9)
    assert code(decide(client, actors, verified, "APPROVED")) == (409, "VERIFICATION_REQUIRED")


def test_a_rejection_needs_a_reason_and_allows_a_new_migration(
    client: TestClient, actors: Actors, verified: dict[str, Any]
) -> None:
    assert code(decide(client, actors, verified, "REJECTED")) == (422, "REASON_REQUIRED")
    response = decide(client, actors, verified, "REJECTED", reason="The notes do not explain the rollover limit.")
    assert response.status_code == 200
    assert response.json()["state"] == "REJECTED"
    assert response.json()["decision"]["reason"] == "The notes do not explain the rollover limit."
    assert client.post(f"/api/v1/modules/{verified['id']}/migrate", headers=actors.engineer).status_code == 202


# --- Facade modes and the shadow gate ---


def test_only_an_approved_module_takes_traffic(client: TestClient, actors: Actors, verified: dict[str, Any]) -> None:
    assert code(mode(client, actors, verified, "SHADOW")) == (409, "NOT_APPROVED")
    assert code(mode(client, actors, verified, "MODERN")) == (409, "NOT_APPROVED")


def test_modern_needs_shadow_first_then_a_clean_sample(
    client: TestClient, actors: Actors, verified: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "shadow_sample_size", 5)
    approved = decide(client, actors, verified, "APPROVED").json()
    assert code(mode(client, actors, approved, "MODERN")) == (409, "SHADOW_REQUIRED")
    shadow = mode(client, actors, approved, "SHADOW").json()
    assert shadow["facade_mode"] == "SHADOW"
    assert shadow["shadow"] == {**shadow["shadow"], "compared": 0, "mismatches": 0, "sample": 5, "ready": False}
    for _ in range(4):
        assert report(client).json()["match"] is True
    gate = mode(client, actors, detail(client, actors, verified["id"]), "MODERN")
    assert code(gate) == (409, "SHADOW_GATE")
    assert "4 compared" in gate.json()["error"]["message"]
    report(client)
    ready = detail(client, actors, verified["id"])
    assert ready["shadow"]["ready"] is True
    modern = mode(client, actors, ready, "MODERN")
    assert modern.status_code == 200
    assert modern.json()["facade_mode"] == "MODERN"


def test_one_mismatch_blocks_promotion_until_shadow_starts_again(
    client: TestClient, db: Session, actors: Actors, verified: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "shadow_sample_size", 3)
    approved_in_shadow(client, actors, verified)
    result = report(client, modern="E0000149Y ").json()
    assert (result["match"], result["fields"]) == (False, ["MV-OUT-CONSUMPTION"])
    for _ in range(5):
        report(client)
    found = detail(client, actors, verified["id"])
    assert found["shadow"]["compared"] == 6 and found["shadow"]["mismatches"] == 1
    assert code(mode(client, actors, found, "MODERN")) == (409, "SHADOW_GATE")
    view = client.get(f"/api/v1/modules/{verified['id']}/shadow", headers=actors.viewer).json()
    assert view["mismatches"][0]["diff"]["diffs"][0] == {
        "field": "MV-OUT-CONSUMPTION",
        "legacy": "150",
        "modern": "149",
        "legacy_raw": "00150",
        "modern_raw": "00149",
    }
    # Rollback is always allowed, and a fresh shadow period starts the count again.
    legacy = mode(client, actors, found, "LEGACY").json()
    again = mode(client, actors, legacy, "SHADOW").json()
    assert (again["shadow"]["compared"], again["shadow"]["mismatches"]) == (0, 0)


def test_the_route_table_carries_code_only_for_approved_routed_modules(
    client: TestClient, actors: Actors, verified: dict[str, Any]
) -> None:
    table = client.get("/api/v1/internal/facade/routes", headers=TOKEN).json()
    assert table["modules"]["MTRVAL"] == {"mode": "LEGACY", "module_id": verified["id"]}
    approved_in_shadow(client, actors, verified)
    table = client.get("/api/v1/internal/facade/routes", headers=TOKEN).json()
    route = table["modules"]["MTRVAL"]
    assert route["mode"] == "SHADOW"
    assert route["artifact"]["sha256"] == verified["current_artifact"]["sha256"]
    assert {item["path"] for item in route["artifact"]["files"]} == set(verified["current_artifact"]["files"])


@pytest.mark.parametrize("headers", [{}, {"X-Facade-Token": ""}, {"X-Facade-Token": "wrong-token-of-enough-length"}])
def test_the_internal_api_refuses_callers_without_the_facade_token(
    client: TestClient, actors: Actors, headers: dict[str, str]
) -> None:
    assert client.get("/api/v1/internal/facade/routes", headers=headers).status_code == 401
    assert client.get("/api/v1/internal/facade/routes", headers={**headers, **actors.architect}).status_code == 401
    body = {"program": "MTRVAL", "input": "x", "legacy": "y", "modern": "z"}
    assert client.post("/api/v1/internal/facade/shadow", json=body, headers=headers).status_code == 401


def test_the_internal_api_fails_closed_without_a_secret(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import SecretStr

    monkeypatch.setattr(get_settings(), "facade_shared_secret", SecretStr(""))
    response = client.get("/api/v1/internal/facade/routes", headers=TOKEN)
    assert code(response) == (503, "FACADE_NOT_CONFIGURED")


def test_a_shadow_report_for_a_module_not_in_shadow_is_refused(client: TestClient, verified: dict[str, Any]) -> None:
    assert code(report(client)) == (409, "NOT_IN_SHADOW")


def test_facade_modes_are_architect_only(client: TestClient, actors: Actors, verified: dict[str, Any]) -> None:
    body = {"mode": "SHADOW", "expected_version": verified["version"]}
    for headers in (actors.viewer, actors.engineer):
        response = client.post(f"/api/v1/modules/{verified['id']}/facade-mode", json=body, headers=headers)
        assert response.status_code == 403
    assert client.post(f"/api/v1/modules/{verified['id']}/shadow-replay", headers=actors.viewer).status_code == 403


# --- Shadow replay, through a fake facade that reports like the real one ---


class FakeFacade(httpx.BaseTransport):
    """Answers like the facade in shadow mode and reports each pair to the internal API."""

    def __init__(self, client: TestClient, modern: str | None = None) -> None:
        self.client = client
        self.modern = modern
        self.paths: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/routes":
            return httpx.Response(200, json={"version": "v", "modules": {"MTRVAL": "SHADOW"}})
        self.paths.append(request.url.path)
        report(self.client, modern=self.modern or LEGACY)
        return httpx.Response(200, json={"status": "E00"}, headers={"X-ParityForge-Route": "shadow"})


def test_replay_sends_recorded_traffic_and_the_reports_fill_the_sample(
    client: TestClient, actors: Actors, verified: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    approved_in_shadow(client, actors, verified)
    fake = FakeFacade(client)
    monkeypatch.setattr(
        module_handlers, "facade_client", lambda _settings: httpx.Client(base_url="http://facade", transport=fake)
    )
    assert code(client.post(f"/api/v1/modules/{verified['id']}/shadow-replay", headers=actors.viewer)) == (
        403,
        "FORBIDDEN",
    )
    job = start(client, actors, verified["id"], "shadow-replay")
    assert job["status"] == "SUCCEEDED", (job["error_code"], job["metrics"])
    assert job["metrics"]["sent"] == job["metrics"]["answered"] == get_settings().shadow_sample_size
    assert job["metrics"]["routes"] == {"shadow": job["metrics"]["sent"]}
    assert set(fake.paths) == {"/meter/validate"}
    found = detail(client, actors, verified["id"])
    assert found["shadow"]["ready"] is True
    assert mode(client, actors, found, "MODERN").status_code == 200


def test_replay_needs_shadow_mode(client: TestClient, actors: Actors, verified: dict[str, Any]) -> None:
    response = client.post(f"/api/v1/modules/{verified['id']}/shadow-replay", headers=actors.engineer)
    assert code(response) == (409, "NOT_IN_SHADOW")


# --- Re-verifying an approved module ---


def test_a_passing_re_verification_keeps_the_approval(
    client: TestClient, actors: Actors, verified: dict[str, Any]
) -> None:
    approved_in_shadow(client, actors, verified)
    assert start(client, actors, verified["id"], "verify")["status"] == "SUCCEEDED"
    found = detail(client, actors, verified["id"])
    assert (found["state"], found["facade_mode"]) == ("APPROVED", "SHADOW")


def test_a_failing_re_verification_blocks_and_rolls_traffic_back_to_legacy(
    client: TestClient, db: Session, actors: Actors, verified: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    approved_in_shadow(client, actors, verified)
    monkeypatch.setattr(get_settings(), "mutation_threshold", 99.9)
    assert start(client, actors, verified["id"], "verify")["status"] == "SUCCEEDED"
    found = detail(client, actors, verified["id"])
    assert (found["state"], found["state_reason"], found["facade_mode"]) == ("BLOCKED", "MUTATION_FAILED", "LEGACY")
    rollback = db.scalars(
        select(AuditLog).where(AuditLog.action == "facade.rollback", AuditLog.entity_id == verified["id"])
    ).one()
    assert rollback.safe_metadata["from"] == "SHADOW"
    run_jobs()
