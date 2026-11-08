"""Gates (Blueprint Section 7.2): no module reaches VERIFIED unless the build, the unit tests,
100% equivalence, coverage and mutation all pass. Exceptions need an architect and a reason.
Reports are reproducible: the same seed gives a byte-identical report.
"""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import CodeArtifact
from app.services import gates
from app.services.agent.mock import FIXTURES, MockAgent
from app.services.jobs import module_handlers
from tests.conftest import UserFactory
from tests.modules.helpers import Actors, detail, module_of, ready_project, run_detail, runs, start

REPAIRED = FIXTURES / "repair_v1" / "RATECALC"


@pytest.fixture
def actors(client: TestClient, make_user: UserFactory) -> Actors:
    return Actors(client, make_user)


def repaired_ratecalc_root(tmp_path: Path) -> Path:
    """Fixtures whose first migration is already the half-up version."""
    root = tmp_path / "workflow"
    shutil.copytree(REPAIRED, root / "migrate_v1" / "RATECALC")
    shutil.copytree(FIXTURES / "plan_v1", root / "plan_v1")
    return root


@pytest.fixture
def verified_ratecalc(
    client: TestClient, db: Session, actors: Actors, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    root = repaired_ratecalc_root(tmp_path)
    monkeypatch.setattr(module_handlers, "get_agent_provider", lambda _settings: MockAgent(workflow_root=root))
    project_id = ready_project(client, db, actors, ("RATECALC",))
    module = module_of(client, actors, project_id, "RATECALC")
    assert start(client, actors, module["id"], "migrate")["status"] == "SUCCEEDED"
    found = detail(client, actors, module["id"])
    assert found["state"] == "VERIFIED", found["gates"]
    return found


# --- The evaluation itself ---


def artifact(build_ok: bool = True, tests_ok: bool = True, status: str = "BUILT") -> CodeArtifact:
    return CodeArtifact(
        build_status=status,
        build_report={
            "build": {"ok": build_ok, "errors": 0 if build_ok else 1},
            "tests": {"ok": tests_ok, "failed": 0 if tests_ok else 1, "total": 5, "passed": 5 if tests_ok else 4},
        },
    )


LIMITS = gates.Thresholds(coverage=85.0, mutation=70.0, exceptions={})


def test_all_gates_pass_only_together() -> None:
    assert gates.all_passed(gates.evaluate(artifact(), 500, 0, 90.0, 75.0, LIMITS))


@pytest.mark.parametrize(
    ("case", "failing"),
    [
        ({"artifact": artifact(build_ok=False, status="BUILD_FAILED")}, "BUILD"),
        ({"artifact": artifact(build_ok=False, status="POLICY_FAILED")}, "BUILD"),
        ({"artifact": artifact(tests_ok=False, status="TESTS_FAILED")}, "UNIT_TESTS"),
        ({"failed": 1}, "EQUIVALENCE"),
        ({"cases": 0}, "EQUIVALENCE"),
        ({"coverage": 84.99}, "COVERAGE"),
        ({"coverage": None}, "COVERAGE"),
        ({"mutation": 69.99}, "MUTATION"),
        ({"mutation": None}, "MUTATION"),
    ],
)
def test_each_gate_alone_keeps_a_module_from_passing(case: dict[str, Any], failing: str) -> None:
    evaluated = gates.evaluate(
        case.get("artifact", artifact()),
        case.get("cases", 500),
        case.get("failed", 0),
        case.get("coverage", 90.0),
        case.get("mutation", 75.0),
        LIMITS,
    )
    assert not gates.all_passed(evaluated)
    assert gates.first_failure(evaluated) == f"{failing}_FAILED"
    assert [gate["gate"] for gate in evaluated if not gate["passed"]] == [failing]


def test_an_exception_lowers_only_its_own_threshold() -> None:
    limits = gates.Thresholds(coverage=80.0, mutation=70.0, exceptions={"COVERAGE": {"reason": "dead code"}})
    evaluated = gates.evaluate(artifact(), 500, 0, 82.0, 75.0, limits)
    assert gates.all_passed(evaluated)
    assert evaluated[3]["exception"] == {"reason": "dead code"}
    assert "exception" not in evaluated[4]


# --- Through the API, on real verification runs ---


def test_a_coverage_threshold_above_the_measured_value_blocks_the_module(
    client: TestClient, actors: Actors, verified_ratecalc: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    module_id = verified_ratecalc["id"]
    coverage = verified_ratecalc["latest_run"]["coverage_pct"]
    monkeypatch.setattr(get_settings(), "coverage_threshold", 99.0)
    assert coverage < 99.0
    assert start(client, actors, module_id, "verify")["status"] == "SUCCEEDED"
    found = detail(client, actors, module_id)
    assert (found["state"], found["state_reason"]) == ("BLOCKED", "COVERAGE_FAILED")
    assert found["latest_run"]["failed"] == 0  # Equivalence alone is not enough.

    # An engineer cannot lower a gate; an architect must give a reason.
    body = {
        "gate": "COVERAGE",
        "threshold": 90.0,
        "reason": "The only missed paragraph is dead code.",
        "expected_version": found["version"],
    }
    assert (
        client.post(f"/api/v1/modules/{module_id}/gate-exceptions", json=body, headers=actors.engineer).status_code
        == 403
    )
    blank = {**body, "reason": "   "}
    response = client.post(f"/api/v1/modules/{module_id}/gate-exceptions", json=blank, headers=actors.architect)
    assert response.status_code == 422
    stale = {**body, "expected_version": found["version"] - 1}
    response = client.post(f"/api/v1/modules/{module_id}/gate-exceptions", json=stale, headers=actors.architect)
    assert response.status_code == 409
    response = client.post(f"/api/v1/modules/{module_id}/gate-exceptions", json=body, headers=actors.architect)
    assert response.status_code == 200, response.text
    after = response.json()
    assert after["state"] == "VERIFIED"
    assert after["thresholds"]["coverage"] == 90.0
    assert after["thresholds"]["exceptions"]["COVERAGE"]["reason"] == body["reason"]
    coverage_gate = next(gate for gate in after["gates"] if gate["gate"] == "COVERAGE")
    assert coverage_gate["passed"] and coverage_gate["exception"]["reason"] == body["reason"]


def test_a_mutation_threshold_above_the_measured_score_blocks_the_module(
    client: TestClient, actors: Actors, verified_ratecalc: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    module_id = verified_ratecalc["id"]
    monkeypatch.setattr(get_settings(), "mutation_threshold", 99.5)
    assert start(client, actors, module_id, "verify")["status"] == "SUCCEEDED"
    found = detail(client, actors, module_id)
    assert (found["state"], found["state_reason"]) == ("BLOCKED", "MUTATION_FAILED")


def test_equivalence_cannot_be_excepted(client: TestClient, actors: Actors, verified_ratecalc: dict[str, Any]) -> None:
    body = {
        "gate": "EQUIVALENCE",
        "threshold": 90.0,
        "reason": "close enough",
        "expected_version": verified_ratecalc["version"],
    }
    response = client.post(
        f"/api/v1/modules/{verified_ratecalc['id']}/gate-exceptions", json=body, headers=actors.architect
    )
    assert response.status_code == 422


def test_no_endpoint_sets_a_module_state(client: TestClient, actors: Actors, verified_ratecalc: dict[str, Any]) -> None:
    module_id = verified_ratecalc["id"]
    for method in ("PATCH", "PUT"):
        response = client.request(
            method, f"/api/v1/modules/{module_id}", json={"state": "VERIFIED"}, headers=actors.architect
        )
        assert response.status_code == 405


def test_the_same_seed_gives_an_identical_report(
    client: TestClient, actors: Actors, verified_ratecalc: dict[str, Any]
) -> None:
    module_id = verified_ratecalc["id"]
    assert start(client, actors, module_id, "verify")["status"] == "SUCCEEDED"
    first, second = runs(client, actors, module_id)[:2]
    assert first["id"] != second["id"]
    assert first["seed"] == second["seed"]
    left = run_detail(client, actors, module_id, first["id"])
    right = run_detail(client, actors, module_id, second["id"])
    assert json.dumps(left["report"], sort_keys=True) == json.dumps(right["report"], sort_keys=True)
    assert left["gates"] == right["gates"]
    assert left["report"]["versions"]["hypothesis"]
    assert left["report"]["versions"]["modern"]["stryker"] == "4.16.0"
    assert left["report"]["versions"]["legacy"]["compiler"].startswith("cobc (GnuCOBOL) 3.2")


def test_a_different_seed_draws_different_random_cases(
    client: TestClient, actors: Actors, verified_ratecalc: dict[str, Any]
) -> None:
    module_id = verified_ratecalc["id"]
    assert start(client, actors, module_id, "verify", seed=12345)["status"] == "SUCCEEDED"
    latest, previous = runs(client, actors, module_id)[:2]
    assert (latest["seed"], previous["seed"]) == (12345, get_settings().equivalence_seed)
    assert latest["failed"] == 0
    assert latest["cases"] == previous["cases"] == 500


def test_a_report_says_where_its_cases_came_from(
    client: TestClient, actors: Actors, verified_ratecalc: dict[str, Any]
) -> None:
    run = verified_ratecalc["latest_run"]
    report = run_detail(client, actors, verified_ratecalc["id"], run["id"])["report"]
    assert set(report["by_source"]) == {"boundary", "constant", "rule", "recorded", "random"}
    assert sum(report["by_source"].values()) == report["cases"] == 500
    assert report["coverage"]["missed"] == ["8500-APPLY-WINTER-DISCOUNT"]
    assert report["rules"]["exercised"]
    assert report["mutation"]["tool"] == "Stryker.NET"
    assert report["mutation"]["score"] == run["mutation_score"]
