"""Shared steps for plan, migration and verification tests: a bundled project with verified
rules and an approved plan, driven through the public API exactly as a person would.
"""

import os
import uuid
from typing import Any

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.agent.helpers import analyze, extract, make_project, run_jobs
from tests.conftest import UserFactory, bearer, login_as

EXECUTABLE = ("MTRVAL", "RATECALC", "LATEFEE", "STMTGEN")


class Actors:
    def __init__(self, client: TestClient, make_user: UserFactory) -> None:
        self.engineer = bearer(login_as(client, make_user("ENGINEER")))
        self.architect = bearer(login_as(client, make_user("ARCHITECT")))
        self.viewer = bearer(login_as(client, make_user("VIEWER")))


def verify_rules(client: TestClient, actors: Actors, project_id: uuid.UUID, program: str) -> int:
    """Verify every unflagged rule of one program, as the architect."""
    items = client.get(
        f"/api/v1/projects/{project_id}/rules", params={"program": program, "limit": 50}, headers=actors.viewer
    ).json()["items"]
    done = 0
    for rule in items:
        if rule["verifiable"]:
            response = client.post(
                f"/api/v1/rules/{rule['id']}/decision",
                json={"decision": "VERIFIED", "expected_version": rule["version"]},
                headers=actors.architect,
            )
            assert response.status_code == 200, response.text
            done += 1
    return done


def propose_plan(client: TestClient, actors: Actors, project_id: uuid.UUID) -> dict[str, Any]:
    response = client.post(f"/api/v1/projects/{project_id}/plan", headers=actors.engineer)
    assert response.status_code == 202, response.text
    run_jobs()
    job = client.get(f"/api/v1/jobs/{response.json()['id']}", headers=actors.viewer).json()
    assert job["status"] == "SUCCEEDED", job
    plan: dict[str, Any] = client.get(f"/api/v1/projects/{project_id}/plan", headers=actors.viewer).json()["plan"]
    return plan


def approve_plan(client: TestClient, actors: Actors, project_id: uuid.UUID, version: int) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/projects/{project_id}/plan/decision",
        json={"decision": "APPROVED", "expected_version": version},
        headers=actors.architect,
    )
    assert response.status_code == 200, response.text
    plan: dict[str, Any] = response.json()
    return plan


def ready_project(client: TestClient, db: Session, actors: Actors, programs: tuple[str, ...] = EXECUTABLE) -> uuid.UUID:
    """Analyzed, rules extracted and verified for `programs`, plan proposed and approved."""
    project = make_project(db, "BUNDLED")
    analyze(client, actors.engineer, project.id)
    for program in programs:
        assert extract(client, actors.engineer, project.id, program)["status"] == "SUCCEEDED"
        assert verify_rules(client, actors, project.id, program) > 0
    plan = propose_plan(client, actors, project.id)
    approve_plan(client, actors, project.id, plan["version"])
    return project.id


def module_of(client: TestClient, actors: Actors, project_id: uuid.UUID, program: str) -> dict[str, Any]:
    modules = client.get(f"/api/v1/projects/{project_id}/modules", headers=actors.viewer).json()
    found: dict[str, Any] = next(module for module in modules if module["program"] == program)
    return found


def start(client: TestClient, actors: Actors, module_id: str, action: str, **body: Any) -> dict[str, Any]:
    response = client.post(f"/api/v1/modules/{module_id}/{action}", json=body or None, headers=actors.engineer)
    assert response.status_code == 202, response.text
    run_jobs()
    job: dict[str, Any] = client.get(f"/api/v1/jobs/{response.json()['id']}", headers=actors.viewer).json()
    return job


def detail(client: TestClient, actors: Actors, module_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/modules/{module_id}", headers=actors.viewer)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found


def runs(client: TestClient, actors: Actors, module_id: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = client.get(f"/api/v1/modules/{module_id}/runs", headers=actors.viewer).json()
    return found


def run_detail(client: TestClient, actors: Actors, module_id: str, run_id: str) -> dict[str, Any]:
    found: dict[str, Any] = client.get(f"/api/v1/modules/{module_id}/runs/{run_id}", headers=actors.viewer).json()
    return found


# --- A stand-in for the facade, for tests that cannot reach the real one ---

FACADE_TOKEN = {"X-Facade-Token": os.environ.get("FACADE_SHARED_SECRET", "")}
OUTPUT_LENGTHS = {"MTRVAL": 10, "RATECALC": 58, "LATEFEE": 37, "STMTGEN": 83}
FACADE_PATHS = {
    "/meter/validate": "MTRVAL",
    "/billing/rate": "RATECALC",
    "/billing/late-fee": "LATEFEE",
    "/statement/render": "STMTGEN",
}


class FakeFacade(httpx.BaseTransport):
    """Behaves like the facade in shadow mode: it reads the real route table, and for each
    request reports an identical legacy and modern record to the internal API."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.paths: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/routes":
            table = self.client.get("/api/v1/internal/facade/routes", headers=FACADE_TOKEN).json()
            modes = {program: entry["mode"] for program, entry in table["modules"].items()}
            return httpx.Response(200, json={"version": table["version"], "modules": modes})
        self.paths.append(request.url.path)
        program = FACADE_PATHS[request.url.path]
        record = "E00" + "0" * (OUTPUT_LENGTHS[program] - 3)
        body = {"program": program, "input": "replayed", "legacy": record, "modern": record}
        self.client.post("/api/v1/internal/facade/shadow", json=body, headers=FACADE_TOKEN)
        return httpx.Response(200, json={"status": "E00"}, headers={"X-ParityForge-Route": "shadow"})
