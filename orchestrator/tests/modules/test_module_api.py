"""Module endpoints: roles, preconditions and the repair budget, all enforced on the server."""

import shutil
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import AiCall, CodeArtifact
from app.services.agent.mock import FIXTURES, MockAgent
from app.services.jobs import module_handlers
from tests.agent.helpers import analyze, extract, make_project
from tests.conftest import UserFactory, bearer, login_as
from tests.modules.helpers import (
    Actors,
    approve_plan,
    detail,
    module_of,
    propose_plan,
    ready_project,
    start,
    verify_rules,
)


@pytest.fixture
def actors(client: TestClient, make_user: UserFactory) -> Actors:
    return Actors(client, make_user)


@pytest.fixture
def project_id(client: TestClient, db: Session, actors: Actors) -> uuid.UUID:
    return ready_project(client, db, actors, ("RATECALC",))


def error_code(response: Any) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


@pytest.mark.parametrize("action", ["migrate", "repair", "verify", "mutate"])
def test_viewers_and_admins_cannot_start_module_jobs(
    client: TestClient, actors: Actors, project_id: uuid.UUID, make_user: UserFactory, action: str
) -> None:
    module = module_of(client, actors, project_id, "RATECALC")
    admin = bearer(login_as(client, make_user("ADMIN")))
    for headers in (actors.viewer, admin):
        response = client.post(f"/api/v1/modules/{module['id']}/{action}", headers=headers)
        assert error_code(response) == (403, "FORBIDDEN")
    assert client.post(f"/api/v1/modules/{module['id']}/{action}").status_code == 401


def test_unknown_modules_are_404(client: TestClient, actors: Actors) -> None:
    for path in (
        f"/api/v1/modules/{uuid.uuid4()}",
        "/api/v1/modules/not-a-uuid",
        f"/api/v1/modules/{uuid.uuid4()}/runs",
    ):
        assert client.get(path, headers=actors.viewer).status_code == 404
    assert client.post(f"/api/v1/modules/{uuid.uuid4()}/migrate", headers=actors.engineer).status_code == 404


def test_the_batch_driver_cannot_be_migrated(client: TestClient, actors: Actors, project_id: uuid.UUID) -> None:
    module = module_of(client, actors, project_id, "BILLRUN")
    assert module["migratable"] is False
    response = client.post(f"/api/v1/modules/{module['id']}/migrate", headers=actors.engineer)
    assert error_code(response) == (409, "MODULE_NOT_SUPPORTED")


def test_a_module_without_verified_rules_cannot_be_migrated(
    client: TestClient, actors: Actors, project_id: uuid.UUID
) -> None:
    module = module_of(client, actors, project_id, "MTRVAL")  # Its rules were never extracted here.
    response = client.post(f"/api/v1/modules/{module['id']}/migrate", headers=actors.engineer)
    assert error_code(response) == (409, "NO_VERIFIED_RULES")


def test_uploaded_sources_are_never_executed(client: TestClient, db: Session, actors: Actors) -> None:
    project = make_project(db, "UPLOAD")
    analyze(client, actors.engineer, project.id)
    extract(client, actors.engineer, project.id, "RATECALC")
    verify_rules(client, actors, project.id, "RATECALC")
    approve_plan(client, actors, project.id, propose_plan(client, actors, project.id)["version"])
    module = module_of(client, actors, project.id, "RATECALC")
    for action in ("migrate", "verify", "repair"):
        response = client.post(f"/api/v1/modules/{module['id']}/{action}", headers=actors.engineer)
        assert error_code(response) == (409, "UPLOAD_NOT_EXECUTABLE")


@pytest.mark.parametrize("action", ["repair", "verify", "mutate"])
def test_a_pending_module_can_only_be_migrated(
    client: TestClient, actors: Actors, project_id: uuid.UUID, action: str
) -> None:
    module = module_of(client, actors, project_id, "RATECALC")
    response = client.post(f"/api/v1/modules/{module['id']}/{action}", headers=actors.engineer)
    assert response.status_code == 409


def test_a_verified_module_cannot_be_migrated_or_repaired_again(
    client: TestClient, actors: Actors, project_id: uuid.UUID
) -> None:
    module = module_of(client, actors, project_id, "RATECALC")
    start(client, actors, module["id"], "migrate")
    start(client, actors, module["id"], "repair")
    assert detail(client, actors, module["id"])["state"] == "VERIFIED"
    for action in ("migrate", "repair"):
        response = client.post(f"/api/v1/modules/{module['id']}/{action}", headers=actors.engineer)
        assert error_code(response) == (409, "INVALID_STATE")


BROKEN = """namespace ParityForge.Generated;

public static class Broken
{
    public static int Value => undefined_name;
}
"""


def test_the_repair_loop_stops_after_three_attempts(
    client: TestClient,
    db: Session,
    actors: Actors,
    project_id: uuid.UUID,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every answer fails to compile, so the job tries the migration and three repairs, then stops."""
    root = tmp_path / "workflow"
    for folder in ("migrate_v1", "repair_v1"):
        shutil.copytree(FIXTURES / "repair_v1" / "RATECALC", root / folder / "RATECALC")
        (root / folder / "RATECALC" / "src" / "Broken.cs").write_text(BROKEN)
    monkeypatch.setattr(module_handlers, "get_agent_provider", lambda _settings: MockAgent(workflow_root=root))
    module = module_of(client, actors, project_id, "RATECALC")
    job = start(client, actors, module["id"], "migrate")
    assert (job["status"], job["error_code"]) == ("FAILED", "BUILD_FAILED"), job
    found = detail(client, actors, module["id"])
    assert (found["state"], found["repairs_used"], found["repairs_remaining"]) == ("BUILD_FAILED", 3, 0)
    artifacts = db.scalars(
        select(CodeArtifact).where(CodeArtifact.module_id == uuid.UUID(module["id"])).order_by(CodeArtifact.version)
    ).all()
    assert [(a.kind, a.attempt, a.build_status) for a in artifacts] == [
        ("MIGRATION", 1, "BUILD_FAILED"),
        ("REPAIR", 2, "BUILD_FAILED"),
        ("REPAIR", 3, "BUILD_FAILED"),
        ("REPAIR", 4, "BUILD_FAILED"),
    ]
    assert any(
        d["id"] == "CS0103" and d["file"] == "src/Broken.cs" for d in artifacts[0].build_report["build"]["diagnostics"]
    )
    prompts = [call.prompt_version for call in db.scalars(select(AiCall).where(AiCall.job_id == uuid.UUID(job["id"])))]
    assert sorted(prompts) == ["migrate-v1", "repair-v1", "repair-v1", "repair-v1"]
    response = client.post(f"/api/v1/modules/{module['id']}/repair", headers=actors.engineer)
    assert error_code(response) == (409, "REPAIR_LIMIT")
    assert get_settings().repair_max_attempts == 3


def test_the_artifact_records_its_rules_and_files(
    client: TestClient, db: Session, actors: Actors, project_id: uuid.UUID
) -> None:
    module = module_of(client, actors, project_id, "RATECALC")
    start(client, actors, module["id"], "migrate")
    artifact = client.get(f"/api/v1/modules/{module['id']}/artifacts/1", headers=actors.viewer).json()
    assert artifact["kind"] == "MIGRATION"
    assert artifact["prompt_version"] == "migrate-v1"
    assert len(artifact["rule_ids"]) == 12  # Every verified RATECALC rule the recording covers.
    assert artifact["files"] == [item["path"] for item in artifact["file_contents"]]
    assert "src/ModuleEntry.cs" in artifact["files"]
    assert "Math.Round(amount, 2)" in next(
        f["content"] for f in artifact["file_contents"] if f["path"].endswith("RateCalculator.cs")
    )
    assert artifact["build_report"]["tests"]["passed"] == artifact["build_report"]["tests"]["total"] > 0
    assert client.get(f"/api/v1/modules/{module['id']}/artifacts/99", headers=actors.viewer).status_code == 404
