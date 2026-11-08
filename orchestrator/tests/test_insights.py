"""Dashboard, assessment report and audit log: numbers come from stored rows only."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import UserFactory, bearer, login_as
from tests.modules.helpers import Actors, module_of, ready_project, runs, start


@pytest.fixture
def actors(client: TestClient, make_user: UserFactory) -> Actors:
    return Actors(client, make_user)


@pytest.fixture
def project(client: TestClient, db: Session, actors: Actors) -> dict[str, Any]:
    project_id = ready_project(client, db, actors, ("MTRVAL",))
    module = module_of(client, actors, project_id, "MTRVAL")
    assert start(client, actors, module["id"], "migrate")["status"] == "SUCCEEDED"
    return {"id": str(project_id), "module": module}


def test_the_dashboard_reports_stored_runs_and_counts(
    client: TestClient, actors: Actors, project: dict[str, Any]
) -> None:
    body = client.get(f"/api/v1/projects/{project['id']}/dashboard", headers=actors.viewer).json()
    run = runs(client, actors, project["module"]["id"])[0]
    row = next(item for item in body["modules"] if item["program"] == "MTRVAL")
    assert (row["cases"], row["passed"], row["coverage_pct"], row["mutation_score"], row["run_id"]) == (
        run["cases"],
        run["passed"],
        run["coverage_pct"],
        run["mutation_score"],
        run["id"],
    )
    assert body["modules_by_state"] == {"VERIFIED": 1, "PENDING": 4}
    assert body["equivalence"] == {"modules_verified": 1, "cases": run["cases"], "identical": run["passed"]}
    rules = body["rules"]
    assert rules["verified"] == rules["by_state"]["VERIFIED"] == rules["human_decisions"]
    assert rules["seeded_decisions"] == 0
    # One mock call each for the extraction, the plan and the migration. Mock calls cost nothing.
    assert body["ai"]["by_mode"] == {"mock": 3}
    assert body["ai"]["estimated_cost_usd"] == 0
    kinds = {event["what"] for event in body["activity"]}
    assert "verify MTRVAL" in kinds and "migrate MTRVAL" in kinds


def test_the_report_has_three_sections_and_a_markdown_export(
    client: TestClient, actors: Actors, project: dict[str, Any]
) -> None:
    body = client.get(f"/api/v1/projects/{project['id']}/report", headers=actors.viewer).json()
    assert [section["heading"].split(":")[0] for section in body["sections"]] == ["As-Is", "To-Be", "Transition"]
    run = runs(client, actors, project["module"]["id"])[0]
    to_be = body["sections"][1]["tables"][1]["rows"]
    assert ["MTRVAL", "VERIFIED", f"{run['passed']} of {run['cases']}"] == to_be[0][:3]
    markdown = client.get(f"/api/v1/projects/{project['id']}/report.md", headers=actors.viewer)
    assert markdown.status_code == 200
    assert markdown.headers["content-type"].startswith("text/markdown")
    assert "attachment" in markdown.headers["content-disposition"]
    assert markdown.text.startswith("# ") and "## As-Is" in markdown.text and "| MTRVAL | VERIFIED |" in markdown.text
    assert body["markdown"] == markdown.text


def test_unknown_projects_are_404(client: TestClient, actors: Actors) -> None:
    for path in ("dashboard", "report", "report.md"):
        assert (
            client.get(
                f"/api/v1/projects/00000000-0000-0000-0000-000000000000/{path}", headers=actors.viewer
            ).status_code
            == 404
        )


def test_the_audit_log_is_for_architects_and_admins_and_filters(
    client: TestClient, actors: Actors, project: dict[str, Any], make_user: UserFactory
) -> None:
    for headers in (actors.viewer, actors.engineer):
        assert client.get("/api/v1/admin/audit", headers=headers).status_code == 403
    admin = bearer(login_as(client, make_user("ADMIN")))
    for headers in (actors.architect, admin):
        assert client.get("/api/v1/admin/audit", headers=headers).status_code == 200
    page = client.get("/api/v1/admin/audit", params={"action_prefix": "plan."}, headers=actors.architect).json()
    assert page["items"] and all(item["action"].startswith("plan.") for item in page["items"])
    assert "plan.decision" in page["actions"]
    by_type = client.get("/api/v1/admin/audit", params={"entity_type": "module"}, headers=actors.architect).json()
    assert all(item["entity_type"] == "module" for item in by_type["items"])
    named = client.get("/api/v1/admin/audit", params={"action": "plan.decision"}, headers=actors.architect).json()
    assert named["items"][0]["actor_name"] == "Test Architect"
    assert (
        client.get("/api/v1/admin/audit", params={"action_prefix": "x%"}, headers=actors.architect).status_code == 422
    )
