"""Analysis as a job: queueing, idempotency, recovery, and the read endpoints."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import AuditLog, InventoryEdge, InventoryItem, Job, Project, SourceFile
from app.db.session import get_session_factory
from app.services.jobs import queue
from app.services.jobs.worker import JobWorker
from tests.agent.helpers import analyze, make_project, run_jobs
from tests.conftest import UserFactory, bearer, login_as


def headers_for(client: TestClient, make_user: UserFactory, role: str) -> dict[str, str]:
    return bearer(login_as(client, make_user(role)))


@pytest.fixture
def engineer(client: TestClient, make_user: UserFactory) -> dict[str, str]:
    return headers_for(client, make_user, "ENGINEER")


@pytest.fixture
def analyzed(client: TestClient, db: Session, engineer: dict[str, str]) -> Project:
    project = make_project(db)
    analyze(client, engineer, project.id)
    db.expire_all()
    return project


def api(project: Project, suffix: str = "") -> str:
    return f"/api/v1/projects/{project.id}{suffix}"


@pytest.mark.parametrize(("role", "code"), [("VIEWER", 403), ("ADMIN", 403), ("ENGINEER", 202), ("ARCHITECT", 202)])
def test_who_can_start_an_analysis(
    client: TestClient, db: Session, make_user: UserFactory, role: str, code: int
) -> None:
    project = make_project(db)
    response = client.post(api(project, "/analyze"), headers=headers_for(client, make_user, role))
    assert response.status_code == code
    if code == 403:
        assert response.json()["error"]["code"] == "FORBIDDEN"
    run_jobs()


def test_analysis_needs_a_session(client: TestClient, db: Session) -> None:
    project = make_project(db)
    assert client.post(api(project, "/analyze")).status_code == 401


def test_unknown_project_is_404_for_every_endpoint(client: TestClient, engineer: dict[str, str]) -> None:
    for pid in (uuid.uuid4(), "not-a-uuid"):
        assert client.post(f"/api/v1/projects/{pid}/analyze", headers=engineer).status_code == 404
        for suffix in ("inventory", "inventory/layouts", "graph", "sources", f"sources/{uuid.uuid4()}", "jobs"):
            assert client.get(f"/api/v1/projects/{pid}/{suffix}", headers=engineer).status_code == 404, suffix


def test_a_job_runs_through_its_states_and_is_audited(
    client: TestClient, db: Session, engineer: dict[str, str]
) -> None:
    project = make_project(db)
    queued = client.post(api(project, "/analyze"), headers=engineer).json()
    assert queued["status"] == "QUEUED"
    assert queued["kind"] == "ANALYZE"
    assert queued["deduplicated"] is False
    assert client.get(f"/api/v1/jobs/{queued['id']}", headers=engineer).json()["status"] == "QUEUED"

    assert run_jobs() >= 1
    job = client.get(f"/api/v1/jobs/{queued['id']}", headers=engineer).json()
    assert job["status"] == "SUCCEEDED"
    assert job["attempts"] == 1
    assert job["started_at"] is not None
    assert job["ended_at"] is not None
    assert job["error_code"] is None
    assert job["metrics"]["summary"]["programs"] == 5

    db.expire_all()
    assert db.get(Project, project.id).status == "ANALYZED"  # type: ignore[union-attr]
    actions = db.scalars(select(AuditLog.action).where(AuditLog.entity_id == queued["id"])).all()
    assert list(actions) == ["job.queued", "job.succeeded"]


def test_the_same_input_returns_the_same_job_without_new_work(
    client: TestClient, db: Session, engineer: dict[str, str], analyzed: Project
) -> None:
    first = db.scalar(select(func.count()).select_from(Job).where(Job.project_id == analyzed.id))
    again = client.post(api(analyzed, "/analyze"), headers=engineer)
    assert again.status_code == 202
    assert again.json()["deduplicated"] is True
    assert again.json()["status"] == "SUCCEEDED"
    assert db.scalar(select(func.count()).select_from(Job).where(Job.project_id == analyzed.id)) == first


def test_a_queued_duplicate_also_returns_the_same_job(
    client: TestClient, db: Session, engineer: dict[str, str]
) -> None:
    project = make_project(db)
    first = client.post(api(project, "/analyze"), headers=engineer).json()
    second = client.post(api(project, "/analyze"), headers=engineer).json()
    assert (second["id"], second["deduplicated"]) == (first["id"], True)
    run_jobs()


def test_racing_requests_queue_one_job(db: Session) -> None:
    project = make_project(db)
    project_id = project.id
    factory = get_session_factory()

    def request(_: int) -> uuid.UUID:
        with factory() as session:
            job, _created = queue.enqueue(session, project_id, "ANALYZE", "race", {}, None)
            return job.id

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = set(pool.map(request, range(16)))
    assert len(ids) == 1
    run_jobs()


def test_changing_a_source_gives_a_new_job(
    client: TestClient, db: Session, engineer: dict[str, str], analyzed: Project
) -> None:
    row = db.scalars(select(SourceFile).where(SourceFile.project_id == analyzed.id)).first()
    assert row is not None
    row.sha256 = uuid.uuid4().hex
    db.commit()
    response = client.post(api(analyzed, "/analyze"), headers=engineer).json()
    assert response["deduplicated"] is False
    run_jobs()


def test_a_failed_job_can_be_retried_and_keeps_a_sanitized_code(
    client: TestClient, db: Session, engineer: dict[str, str]
) -> None:
    project = make_project(db)
    for row in db.scalars(select(SourceFile).where(SourceFile.project_id == project.id, SourceFile.kind == "PROGRAM")):
        db.delete(row)
    db.commit()
    job = client.post(api(project, "/analyze"), headers=engineer).json()
    run_jobs()
    failed = client.get(f"/api/v1/jobs/{job['id']}", headers=engineer).json()
    assert (failed["status"], failed["error_code"]) == ("FAILED", "NO_PROGRAMS")
    db.expire_all()
    assert db.get(Project, project.id).status == "FAILED"  # type: ignore[union-attr]
    assert db.scalar(select(func.count()).select_from(InventoryItem).where(InventoryItem.project_id == project.id)) == 0

    retry = client.post(api(project, "/analyze"), headers=engineer).json()
    assert retry["id"] != job["id"]
    run_jobs()


def test_an_unexpected_crash_stores_only_a_fixed_code(
    client: TestClient, db: Session, engineer: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.jobs import handlers

    def explode(*_args: Any) -> dict[str, Any]:
        raise RuntimeError("secret detail that must not be stored")

    monkeypatch.setitem(handlers.HANDLERS, "ANALYZE", explode)
    project = make_project(db)
    job = client.post(api(project, "/analyze"), headers=engineer).json()
    run_jobs()
    failed = client.get(f"/api/v1/jobs/{job['id']}", headers=engineer)
    assert failed.json()["error_code"] == "INTERNAL_ERROR"
    assert "secret detail" not in failed.text


def test_skip_locked_lets_two_workers_take_different_jobs(db: Session) -> None:
    # Queue two jobs with an empty queue around them, then claim in two open transactions.
    run_jobs()
    project = make_project(db)
    queue.enqueue(db, project.id, "ANALYZE", "one", {}, None)
    queue.enqueue(db, project.id, "ANALYZE", "two", {}, None)
    factory = get_session_factory()
    with factory() as first, factory() as second:
        locked = first.scalar(
            select(Job)
            .where(Job.status == "QUEUED")
            .order_by(Job.created_at, Job.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        assert locked is not None
        other = queue.claim_next(second)
        assert other is not None
        assert other != locked.id
        first.rollback()
    run_jobs()


def test_a_job_lost_by_a_dead_worker_is_requeued_then_failed(db: Session) -> None:
    project = make_project(db)
    job, _ = queue.enqueue(db, project.id, "ANALYZE", "lost", {}, None)
    job.status = "RUNNING"
    job.started_at = datetime.now(UTC) - timedelta(hours=1)
    job.attempts = 1
    db.commit()
    assert queue.recover_abandoned(db, 60) >= 1
    db.expire_all()
    assert db.get(Job, job.id).status == "QUEUED"  # type: ignore[union-attr]

    job.status = "RUNNING"
    job.started_at = datetime.now(UTC) - timedelta(hours=1)
    job.attempts = queue.MAX_ATTEMPTS
    db.commit()
    queue.recover_abandoned(db, 60)
    db.expire_all()
    refreshed = db.get(Job, job.id)
    assert refreshed is not None
    assert (refreshed.status, refreshed.error_code) == ("FAILED", "JOB_ABANDONED")


def test_a_recent_running_job_is_left_alone(db: Session) -> None:
    project = make_project(db)
    job, _ = queue.enqueue(db, project.id, "ANALYZE", "fresh", {}, None)
    job.status = "RUNNING"
    job.started_at = datetime.now(UTC)
    db.commit()
    queue.recover_abandoned(db, 300)
    db.expire_all()
    assert db.get(Job, job.id).status == "RUNNING"  # type: ignore[union-attr]
    job.status = "FAILED"
    db.commit()


def test_the_worker_thread_picks_up_a_job(client: TestClient, db: Session, engineer: dict[str, str]) -> None:
    import time

    project = make_project(db)
    job = client.post(api(project, "/analyze"), headers=engineer).json()
    worker = JobWorker(get_session_factory(), get_settings())
    worker.start()
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            status = client.get(f"/api/v1/jobs/{job['id']}", headers=engineer).json()["status"]
            if status == "SUCCEEDED":
                break
            time.sleep(0.1)
        assert status == "SUCCEEDED"
    finally:
        worker.stop()


def test_the_worker_survives_an_unexpected_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    from app.services.jobs import worker as worker_module

    calls = threading.Semaphore(0)
    worker = JobWorker(get_session_factory(), get_settings())

    def explode(_polls: int = 0) -> bool:
        calls.release()
        raise RuntimeError("not a database error")

    monkeypatch.setattr(worker, "run_once", explode)
    monkeypatch.setattr(worker_module, "ERROR_BACKOFF_SECONDS", 0.01)
    worker.start()
    try:
        assert calls.acquire(timeout=5)
        assert calls.acquire(timeout=5), "The worker stopped after one error"
    finally:
        worker.stop()


def test_analysis_replaces_rather_than_duplicates(
    client: TestClient, db: Session, engineer: dict[str, str], analyzed: Project
) -> None:
    def count() -> int:
        return (
            db.scalar(select(func.count()).select_from(InventoryItem).where(InventoryItem.project_id == analyzed.id))
            or 0
        )

    before = count()
    row = db.scalars(select(SourceFile).where(SourceFile.project_id == analyzed.id)).first()
    assert row is not None
    row.sha256 = uuid.uuid4().hex
    db.commit()
    client.post(api(analyzed, "/analyze"), headers=engineer)
    run_jobs()
    db.expire_all()
    assert count() == before


def test_inventory_summary_matches_the_hand_checked_counts(
    client: TestClient, engineer: dict[str, str], analyzed: Project
) -> None:
    body = client.get(api(analyzed, "/inventory"), headers=engineer).json()
    assert body["analyzed"] is True
    assert body["diagnostics"] == []
    summary = body["summary"]
    assert summary["programs"] == 5
    assert summary["copybooks"] == 6
    assert summary["working_paragraphs"] == 69
    assert summary["go_tos"] == 1
    assert summary["dead_paragraphs"] == 1
    assert summary["obsolete_records"] == 1
    assert summary["files"] == 4
    assert [item["name"] for item in body["dead_code"]["paragraphs"]] == ["8500-APPLY-WINTER-DISCOUNT"]
    assert body["dead_code"]["paragraphs"][0]["program"] == "RATECALC"
    assert body["dead_code"]["paragraphs"][0]["start_line"] == 216
    assert [item["name"] for item in body["dead_code"]["records"]] == ["RT-WINTER-1987-TABLE"]
    assert {item["name"] for item in body["copybooks"]} >= {"CALLREC", "RATES"}
    billrun = next(item for item in body["programs"] if item["name"] == "BILLRUN")
    assert billrun["is_entry"] is True
    assert billrun["calls"] == ["LATEFEE", "MTRVAL", "RATECALC", "STMTGEN"]
    assert billrun["metrics"]["working_paragraphs"] == 25
    assert {item["name"] for item in billrun["copybooks"]} == {"CUSTREC", "READREC", "BILLREC", "ERRCODES", "CALLREC"}
    assert all(item["file_id"] for item in billrun["copybooks"])
    assert {item["name"] for item in body["files"]} == {"CUSTFILE", "READFILE", "BILLFILE", "ERRFILE"}


def test_inventory_before_any_analysis_is_an_empty_state(
    client: TestClient, db: Session, engineer: dict[str, str]
) -> None:
    project = make_project(db)
    body = client.get(api(project, "/inventory"), headers=engineer).json()
    assert body["analyzed"] is False
    assert body["programs"] == []


def test_a_viewer_can_read_everything(client: TestClient, make_user: UserFactory, analyzed: Project) -> None:
    viewer = headers_for(client, make_user, "VIEWER")
    for suffix in ("/inventory", "/inventory/layouts", "/graph", "/sources", "/jobs"):
        assert client.get(api(analyzed, suffix), headers=viewer).status_code == 200, suffix


def test_layouts_are_paged_with_computed_sizes(client: TestClient, engineer: dict[str, str], analyzed: Project) -> None:
    page = client.get(api(analyzed, "/inventory/layouts?program=BILLRUN&limit=50"), headers=engineer).json()
    records = {item["name"]: item for item in page["items"]}
    assert records["CUSTOMER-RECORD"]["length"] == 100
    assert records["READ-RECORD"]["length"] == 40
    assert records["BILL-RECORD"]["length"] == 190
    assert records["ERROR-RECORD"]["length"] == 87
    assert records["STMTGEN-PARMS"]["length"] == 165
    field = next(item for item in records["CUSTOMER-RECORD"]["fields"] if item["name"] == "CUST-OVERDUE-BAL")
    assert (field["offset"], field["length"], field["picture"], field["scale"]) == (70, 9, "9(7)V99", 2)

    narrow = client.get(api(analyzed, "/inventory/layouts?limit=2&offset=1"), headers=engineer).json()
    assert len(narrow["items"]) == 2
    assert narrow["total"] >= 15
    assert client.get(api(analyzed, "/inventory/layouts?limit=51"), headers=engineer).status_code == 422


def test_a_copybook_record_appears_once_with_all_its_users(
    client: TestClient, engineer: dict[str, str], analyzed: Project
) -> None:
    items = client.get(api(analyzed, "/inventory/layouts?limit=50"), headers=engineer).json()["items"]
    rates = [item for item in items if item["name"] == "RATE-CONSTANTS"]
    assert len(rates) == 1
    assert rates[0]["used_by"] == ["LATEFEE", "MTRVAL", "RATECALC"]


def test_graph_overview_has_programs_files_and_copybooks(
    client: TestClient, engineer: dict[str, str], analyzed: Project
) -> None:
    graph = client.get(api(analyzed, "/graph"), headers=engineer).json()
    names = {node["id"]: node for node in graph["nodes"]}
    kinds = {node["kind"] for node in graph["nodes"]}
    assert kinds == {"PROGRAM", "COPYBOOK", "FILE"}
    calls = sorted(names[edge["to"]]["name"] for edge in graph["edges"] if edge["kind"] == "CALLS")
    assert calls == ["LATEFEE", "MTRVAL", "RATECALC", "STMTGEN"]
    assert {names[edge["to"]]["name"] for edge in graph["edges"] if edge["kind"] == "READS"} == {"CUSTFILE", "READFILE"}
    assert {names[edge["to"]]["name"] for edge in graph["edges"] if edge["kind"] == "WRITES"} == {"BILLFILE", "ERRFILE"}
    assert len([edge for edge in graph["edges"] if edge["kind"] == "USES"]) == 16


def test_paragraph_graph_expands_thru_and_marks_dead_code(
    client: TestClient, engineer: dict[str, str], analyzed: Project
) -> None:
    graph = client.get(api(analyzed, "/graph?program=ratecalc"), headers=engineer).json()
    assert graph["program"] == "RATECALC"
    by_name = {node["name"]: node for node in graph["nodes"]}
    assert by_name["8500-APPLY-WINTER-DISCOUNT"]["dead"] is True
    assert by_name["3400-TARIFF-EXIT"]["is_exit_label"] is True
    assert sum(1 for node in graph["nodes"] if node["dead"]) == 1
    names = {node["id"]: node["name"] for node in graph["nodes"]}
    from_main = {names[edge["to"]]: edge for edge in graph["edges"] if names[edge["from"]] == "0000-MAIN-CONTROL"}
    assert from_main["3300-SELECT-SEASON"]["thru"] is True
    assert from_main["3300-SELECT-SEASON"]["by_name"] is False
    assert from_main["3000-SELECT-TARIFF"]["by_name"] is True
    assert from_main["3000-SELECT-TARIFF"]["lines"] == [60]
    assert "3500-LOAD-RESIDENTIAL" not in from_main


def test_billrun_graph_has_the_single_go_to(client: TestClient, engineer: dict[str, str], analyzed: Project) -> None:
    graph = client.get(api(analyzed, "/graph?program=BILLRUN"), headers=engineer).json()
    names = {node["id"]: node["name"] for node in graph["nodes"]}
    gotos = [edge for edge in graph["edges"] if edge["kind"] == "GOES_TO"]
    assert [(names[edge["from"]], names[edge["to"]], edge["lines"]) for edge in gotos] == [
        ("2000-PROCESS-READ", "2000-EXIT", [170])
    ]
    assert {names[edge["to"]] for edge in graph["edges"] if edge["kind"] == "CALLS"} == {
        "MTRVAL",
        "RATECALC",
        "LATEFEE",
        "STMTGEN",
    }


def test_unknown_program_graph_is_404(client: TestClient, engineer: dict[str, str], analyzed: Project) -> None:
    assert client.get(api(analyzed, "/graph?program=NOPE"), headers=engineer).status_code == 404


def test_edges_reference_items_in_the_same_project(db: Session, analyzed: Project) -> None:
    edges = db.scalars(select(InventoryEdge).where(InventoryEdge.project_id == analyzed.id)).all()
    assert len(edges) > 100
    ids = set(db.scalars(select(InventoryItem.id).where(InventoryItem.project_id == analyzed.id)))
    assert all(edge.from_item in ids and edge.to_item in ids for edge in edges)


def test_source_view_has_lines_and_copy_links(client: TestClient, engineer: dict[str, str], analyzed: Project) -> None:
    sources = client.get(api(analyzed, "/sources"), headers=engineer).json()
    assert sources["total"] == 12
    by_name = {item["name"]: item for item in sources["items"]}
    body = client.get(api(analyzed, f"/sources/{by_name['BILLRUN.cbl']['id']}"), headers=engineer).json()
    assert body["line_count"] == len(body["lines"]) == 426
    assert body["lines"][169].strip() == "GO TO 2000-EXIT"
    assert [(link["line"], link["name"]) for link in body["copy_links"]] == [
        (59, "CUSTREC"),
        (61, "READREC"),
        (63, "BILLREC"),
        (72, "ERRCODES"),
        (73, "CALLREC"),
    ]
    assert body["copy_links"][0]["file_id"] == by_name["CUSTREC.cpy"]["id"]
    assert body["rule_spans"] == []


def test_a_source_from_another_project_is_404(
    client: TestClient, db: Session, engineer: dict[str, str], analyzed: Project
) -> None:
    other = make_project(db)
    row = db.scalars(select(SourceFile).where(SourceFile.project_id == other.id)).first()
    assert row is not None
    assert client.get(api(analyzed, f"/sources/{row.id}"), headers=engineer).status_code == 404


def test_the_job_list_filters_by_kind(client: TestClient, engineer: dict[str, str], analyzed: Project) -> None:
    jobs = client.get(api(analyzed, "/jobs?kind=ANALYZE"), headers=engineer).json()
    assert jobs["total"] == 1
    assert jobs["items"][0]["kind"] == "ANALYZE"
    assert client.get(api(analyzed, "/jobs?kind=EXTRACT"), headers=engineer).json()["total"] == 0
