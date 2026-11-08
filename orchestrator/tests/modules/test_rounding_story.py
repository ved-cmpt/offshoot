"""The rounding-defect story, end to end through the API (Blueprint Section 3.1, steps 4-7).

The first RATECALC artifact rounds with Math.Round, which goes to the even cent. The harness
runs the real COBOL program and the C# module on the same cases; the midpoint cases differ,
so the module is BLOCKED. A repair that rounds half-up passes every case and the gates.
"""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import UserFactory
from tests.modules.helpers import Actors, detail, module_of, ready_project, run_detail, runs, start


def test_banker_rounding_is_caught_blocked_repaired_and_verified(
    client: TestClient, db: Session, make_user: UserFactory
) -> None:
    actors = Actors(client, make_user)
    project_id = ready_project(client, db, actors, ("RATECALC",))
    module = module_of(client, actors, project_id, "RATECALC")
    assert module["state"] == "PENDING"

    migrate = start(client, actors, module["id"], "migrate")
    assert migrate["status"] == "SUCCEEDED", migrate
    blocked = detail(client, actors, module["id"])
    assert blocked["state"] == "BLOCKED"
    assert blocked["state_reason"] == "EQUIVALENCE_FAILED"
    assert blocked["current_artifact"]["version"] == 1
    assert blocked["current_artifact"]["build_status"] == "BUILT"
    first = runs(client, actors, module["id"])[0]
    report = run_detail(client, actors, module["id"], first["id"])["report"]
    print("first run", first["cases"], first["passed"], first["failed"], report["mismatched_fields"])
    assert first["status"] == "FAILED"
    assert first["failed"] > 0
    assert first["cases"] == 500
    assert set(report["mismatched_fields"]) <= {"RC-OUT-ENERGY", "RC-OUT-SUBTOTAL", "RC-OUT-LEVY", "RC-OUT-TOTAL"}
    assert report["mutation"]["skipped"]
    for mismatch in report["mismatches"]:
        for diff in mismatch["diffs"]:
            # Every difference is exactly one cent, and the legacy value is the larger, half-up one.
            assert Decimal(diff["legacy"]) - Decimal(diff["modern"]) == Decimal("0.01")

    repair = start(client, actors, module["id"], "repair")
    assert repair["status"] == "SUCCEEDED", repair
    verified = detail(client, actors, module["id"])
    second = runs(client, actors, module["id"])[0]
    print(
        "second run",
        second["cases"],
        second["passed"],
        second["failed"],
        second["coverage_pct"],
        second["mutation_score"],
    )
    print("gates", verified["gates"])
    assert verified["current_artifact"]["version"] == 2
    assert verified["current_artifact"]["kind"] == "REPAIR"
    assert second["failed"] == 0
    assert second["passed"] == second["cases"] == 500
    assert verified["state"] == "VERIFIED", verified["gates"]
