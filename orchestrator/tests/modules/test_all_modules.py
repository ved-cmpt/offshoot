"""Every executable BillRite module migrates and verifies in mock mode (Run 03 acceptance)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import UserFactory
from tests.modules.helpers import Actors, detail, module_of, ready_project, run_detail, runs, start


@pytest.mark.parametrize("program", ["MTRVAL", "LATEFEE", "STMTGEN"])
def test_module_migrates_and_verifies(client: TestClient, db: Session, make_user: UserFactory, program: str) -> None:
    actors = Actors(client, make_user)
    project_id = ready_project(client, db, actors, (program,))
    module = module_of(client, actors, project_id, program)
    job = start(client, actors, module["id"], "migrate")
    assert job["status"] == "SUCCEEDED", job
    found = detail(client, actors, module["id"])
    run = runs(client, actors, module["id"])[0]
    report = run_detail(client, actors, module["id"], run["id"])["report"]
    print(program, run["cases"], run["passed"], run["failed"], run["coverage_pct"], run["mutation_score"])
    print(report["by_source"], report["mismatched_fields"], report["mismatches"][:3], report["coverage"]["missed"])
    assert run["failed"] == 0
    assert found["state"] == "VERIFIED", found["gates"]
