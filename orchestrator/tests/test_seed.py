"""The demo seed: idempotent, audited, and loads the right files only."""

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Approval, AuditLog, InventoryItem, Job, Project, Rule, SourceFile, User
from app.scripts.demo_accounts import demo_accounts
from app.scripts.seed_demo import run_seed
from app.services.rules import apply_decision
from tests.conftest import bearer

BILLRITE = Path("/legacy/billrite")


@pytest.fixture
def seeded(db: Session, migrated_db: None, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The seed, with the facade replaced by a stand-in that reports to the test database.

    The real facade reads the running stack's database, not this one. It is exercised by the
    seed on the stack itself and by the browser suite.
    """
    import httpx

    from app.services.jobs import module_handlers
    from tests.modules.helpers import FakeFacade

    fake = FakeFacade(client)
    monkeypatch.setattr(
        module_handlers, "facade_client", lambda _settings: httpx.Client(base_url="http://facade", transport=fake)
    )
    run_seed(db, get_settings())


def counts(db: Session) -> dict[str, int]:
    db.expire_all()
    return {
        "users": db.scalar(select(func.count()).select_from(User)) or 0,
        "projects": db.scalar(select(func.count()).select_from(Project)) or 0,
        "sources": db.scalar(select(func.count()).select_from(SourceFile)) or 0,
    }


def test_second_run_changes_nothing_but_one_audit_entry(db: Session, seeded: None) -> None:
    before = counts(db)
    audit_before = db.scalar(select(func.count()).select_from(AuditLog))
    hashes_before = {row[0]: row[1] for row in db.execute(select(User.email, User.password_hash))}

    result = run_seed(db, get_settings())

    assert result.changed is False
    assert counts(db) == before
    assert {row[0]: row[1] for row in db.execute(select(User.email, User.password_hash))} == hashes_before
    assert db.scalar(select(func.count()).select_from(AuditLog)) == (audit_before or 0) + 1
    last = db.scalars(select(AuditLog).order_by(AuditLog.id.desc())).first()
    assert last is not None
    assert last.action == "seed.run"
    assert last.safe_metadata["changed"] is False


def test_seed_creates_one_account_per_role_and_each_can_log_in(client: TestClient, db: Session, seeded: None) -> None:
    accounts = demo_accounts()
    assert sorted(account.role for account in accounts) == ["ADMIN", "ARCHITECT", "ENGINEER", "VIEWER"]
    for account in accounts:
        response = client.post("/api/v1/auth/login", json={"username": account.username, "password": account.password})
        assert response.status_code == 200, account.role
        assert response.json()["user"]["role"] == account.role
        me = client.get("/api/v1/auth/me", headers=bearer(response.json()))
        assert (me.json()["email"], me.json()["username"]) == (account.email, account.username)


def test_seed_repairs_a_changed_demo_account(db: Session, seeded: None) -> None:
    account = demo_accounts()[0]
    user = db.scalar(select(User).where(User.email == account.email))
    assert user is not None
    user.role = "ADMIN"
    user.active = False
    db.commit()
    result = run_seed(db, get_settings())
    assert result.users_updated == 1
    db.expire_all()
    assert (user.role, user.active) == (account.role, True)


def test_billrite_project_holds_the_application_sources(db: Session, seeded: None) -> None:
    project = db.scalar(select(Project).where(Project.name == "BillRite"))
    assert project is not None
    assert (project.source_kind, project.status) == ("BUNDLED", "ANALYZED")
    rows = db.scalars(select(SourceFile).where(SourceFile.project_id == project.id)).all()
    by_kind: dict[str, set[str]] = {}
    for row in rows:
        by_kind.setdefault(row.kind, set()).add(row.path)
    assert by_kind == {
        "PROGRAM": {f"src/{name}.cbl" for name in ("BILLRUN", "MTRVAL", "RATECALC", "LATEFEE", "STMTGEN")},
        "COPYBOOK": {f"copy/{name}.cpy" for name in ("BILLREC", "CALLREC", "CUSTREC", "ERRCODES", "RATES", "READREC")},
        "DATA_LAYOUT": {"data/LAYOUTS.txt"},
    }


def test_source_metadata_matches_the_files_on_disk(db: Session, seeded: None) -> None:
    for row in db.scalars(select(SourceFile).join(Project).where(Project.name == "BillRite")):
        content = (BILLRITE / row.path).read_bytes()
        assert row.sha256 == hashlib.sha256(content).hexdigest()
        assert row.line_count == len(content.decode().splitlines())
        assert row.content == content.decode()


def test_the_answer_key_and_harness_are_not_project_sources(db: Session, seeded: None) -> None:
    paths = list(db.scalars(select(SourceFile.path).join(Project).where(Project.name == "BillRite")))
    assert not any("RULES" in path or "BRCALL" in path or "README" in path for path in paths)
    # And the answer key is not even mounted in this container.
    assert not Path("/repo-scripts/BILLRITE_RULES.md").exists()
    assert not Path("/docs/BILLRITE_RULES.md").exists()
    assert not Path("/legacy/billrite/BILLRITE_RULES.md").exists()


def test_seed_writes_audit_entries_for_what_it_creates(db: Session, seeded: None) -> None:
    actions = set(db.scalars(select(AuditLog.action).where(AuditLog.action.like("seed.%"))))
    assert {"seed.user_created", "seed.project_created", "seed.run"} <= actions


def test_seed_never_stores_passwords_in_the_audit_log(db: Session, seeded: None) -> None:
    logged = " ".join(str(row) for row in db.scalars(select(AuditLog.safe_metadata)))
    for account in demo_accounts():
        assert account.password not in logged


def test_seed_moves_an_older_demo_account_to_its_username_and_the_published_password(db: Session, seeded: None) -> None:
    from app.core.security import hash_password, verify_password
    from app.scripts.demo_accounts import DEMO_PASSWORD

    account = demo_accounts()[1]
    user = db.scalar(select(User).where(User.email == account.email))
    assert user is not None
    # As a database seeded before usernames existed left it.
    user.username = None
    user.password_hash = hash_password("an-older-demo-password")
    db.commit()
    result = run_seed(db, get_settings())
    assert result.users_updated == 1
    db.expire_all()
    assert user.username == account.username
    assert verify_password(user.password_hash, DEMO_PASSWORD)
    assert user.password_hash.startswith("$argon2id$")
    assert run_seed(db, get_settings()).users_updated == 0


def test_project_list_shows_billrite_with_counts(client: TestClient, seeded: None) -> None:
    account = demo_accounts()[0]
    session = client.post(
        "/api/v1/auth/login", json={"username": account.username, "password": account.password}
    ).json()
    items = client.get("/api/v1/projects", headers=bearer(session)).json()["items"]
    # Other tests add projects to this database, so look for it across every page.
    offset = 50
    while not any(item["name"] == "BillRite" for item in items):
        page = client.get(f"/api/v1/projects?offset={offset}", headers=bearer(session)).json()
        assert page["items"], "BillRite is not in the project list"
        items = page["items"]
        offset += 50
    billrite = next(item for item in items if item["name"] == "BillRite")
    assert billrite["source_file_count"] == 12
    assert billrite["source_line_count"] > 1400


# --- What Run 02 added: inventory, proposed rules and labelled demo decisions (ADR-024).


def billrite(db: Session) -> Project:
    db.expire_all()
    project = db.scalar(select(Project).where(Project.name == "BillRite"))
    assert project is not None
    return project


def test_seed_analyzes_billrite(db: Session, seeded: None) -> None:
    project = billrite(db)
    assert project.status == "ANALYZED"
    programs = db.scalars(
        select(InventoryItem.name).where(InventoryItem.project_id == project.id, InventoryItem.kind == "PROGRAM")
    ).all()
    assert sorted(programs) == ["BILLRUN", "LATEFEE", "MTRVAL", "RATECALC", "STMTGEN"]


def test_seed_proposes_rules_for_every_program(db: Session, seeded: None) -> None:
    project = billrite(db)
    rows = db.scalars(select(Rule).where(Rule.project_id == project.id)).all()
    assert {row.program for row in rows} == {"BILLRUN", "LATEFEE", "MTRVAL", "RATECALC", "STMTGEN"}
    assert len(rows) == 46


def test_seeded_decisions_are_mostly_verified_with_one_rejection_and_some_pending(db: Session, seeded: None) -> None:
    project = billrite(db)
    rows = db.scalars(select(Rule).where(Rule.project_id == project.id)).all()
    states: dict[str, list[Rule]] = {}
    for row in rows:
        states.setdefault(row.state, []).append(row)
    assert len(states["VERIFIED"]) > len(states["PROPOSED"])
    assert [row.title for row in states["REJECTED"]] == ["Senior discount on the energy charge"]
    assert {row.program for row in states["VERIFIED"]} == {"BILLRUN", "LATEFEE", "MTRVAL", "RATECALC", "STMTGEN"}
    pending = {row.program for row in states["PROPOSED"]}
    assert "RATECALC" in pending
    assert all(not row.flags for row in states["VERIFIED"])
    flagged_pending = [row.title for row in states["PROPOSED"] if row.flags]
    assert sorted(flagged_pending) == ["All extracted rules are pre-approved", "Run control totals"]


def test_seeded_decisions_are_labelled_as_not_being_reviews(db: Session, seeded: None) -> None:
    project = billrite(db)
    rows = db.scalars(select(Rule).where(Rule.project_id == project.id, Rule.state != "PROPOSED")).all()
    for row in rows:
        approval = db.scalars(select(Approval).where(Approval.entity_id == row.id)).one()
        assert approval.reason is not None
        assert "not a human review" in approval.reason
        audit_row = db.scalars(
            select(AuditLog).where(AuditLog.entity_id == str(row.id), AuditLog.action == "rule.decision")
        ).one()
        assert audit_row.safe_metadata["seeded"] is True


def test_a_later_seed_never_overrides_a_persons_decision(db: Session, seeded: None) -> None:
    project = billrite(db)
    architect = db.scalar(select(User).where(User.role == "ARCHITECT", User.active))
    assert architect is not None
    row = db.scalar(
        select(Rule).where(Rule.project_id == project.id, Rule.state == "PROPOSED", Rule.program == "RATECALC")
    )
    assert row is not None
    rule_id = row.id
    apply_decision(db, row, architect, "REJECTED", "A person said no.", row.version, get_settings())
    db.commit()
    result = run_seed(db, get_settings())
    assert result.changed is False
    db.expire_all()
    refreshed = db.get(Rule, rule_id)
    assert refreshed is not None
    assert refreshed.state == "REJECTED"


def test_seed_jobs_are_reused_on_a_second_run(db: Session, seeded: None) -> None:
    project = billrite(db)
    before = db.scalar(select(func.count()).select_from(Job).where(Job.project_id == project.id))
    # Analysis, five extractions, the plan, four migrations, four verifications, two shadow replays.
    assert before == 17
    result = run_seed(db, get_settings())
    assert (result.jobs_created, result.decisions_seeded, result.plans_seeded, result.modules_migrated) == (0, 0, 0, 0)
    assert result.modules_promoted == 0
    assert db.scalar(select(func.count()).select_from(Job).where(Job.project_id == project.id)) == before


# --- Run 03: the plan and the modules, from real pipeline runs ---


def test_seed_approves_the_plan_as_a_labelled_demo_decision(db: Session, seeded: None) -> None:
    from app.db.models import Plan

    project = billrite(db)
    plan = db.scalars(select(Plan).where(Plan.project_id == project.id)).one()
    assert (plan.version, plan.state) == (1, "APPROVED")
    assert [step["program"] for step in plan.order] == ["MTRVAL", "RATECALC", "LATEFEE", "STMTGEN", "BILLRUN"]
    approval = db.scalars(select(Approval).where(Approval.entity_id == plan.id)).one()
    assert approval.reason is not None and "not a human review" in approval.reason
    entry = db.scalars(
        select(AuditLog).where(AuditLog.action == "plan.decision", AuditLog.entity_id == str(plan.id))
    ).one()
    assert entry.safe_metadata["seeded"] is True


def test_seed_modules_come_from_real_runs(db: Session, seeded: None) -> None:
    from app.db.models import CodeArtifact, Module, VerificationRun

    project = billrite(db)
    modules = {m.program: m for m in db.scalars(select(Module).where(Module.project_id == project.id))}
    # Blueprint Section 8.2: one modern, one shadow, one awaiting approval, one blocked, one pending.
    assert {name: (m.state, m.facade_mode) for name, m in modules.items()} == {
        "MTRVAL": ("APPROVED", "MODERN"),
        "RATECALC": ("BLOCKED", "LEGACY"),
        "LATEFEE": ("APPROVED", "SHADOW"),
        "STMTGEN": ("VERIFIED", "LEGACY"),
        "BILLRUN": ("PENDING", "LEGACY"),
    }
    sample = get_settings().shadow_sample_size
    assert modules["MTRVAL"].shadow_compared == sample
    assert 0 < modules["LATEFEE"].shadow_compared < sample
    module_ids = [module.id for module in modules.values()]
    decisions = db.scalars(select(Approval).where(Approval.entity_id.in_(module_ids))).all()
    assert len(decisions) == 2  # MTRVAL and LATEFEE.
    assert all("not a human review" in (row.reason or "") for row in decisions)
    ratecalc = modules["RATECALC"]
    assert ratecalc.state_reason == "EQUIVALENCE_FAILED"
    run = db.scalars(select(VerificationRun).where(VerificationRun.module_id == ratecalc.id)).one()
    assert run.failed > 0 and run.passed + run.failed == run.cases == 500
    assert set(run.report["mismatched_fields"]) <= {"RC-OUT-ENERGY", "RC-OUT-SUBTOTAL", "RC-OUT-LEVY", "RC-OUT-TOTAL"}
    artifact = db.get(CodeArtifact, ratecalc.current_artifact_id)
    assert artifact is not None
    assert "Math.Round(amount, 2)" in "".join(f["content"] for f in artifact.files)
    for name in ("MTRVAL", "LATEFEE", "STMTGEN"):
        verified = db.scalars(select(VerificationRun).where(VerificationRun.module_id == modules[name].id)).one()
        assert (verified.status, verified.failed, verified.cases) == ("PASSED", 0, 500)
        assert verified.mutation_score is not None and verified.coverage_pct is not None


def test_the_demo_reset_restores_the_seeded_state_and_keeps_the_audit_log(db: Session, seeded: None) -> None:
    from app.db.models import GateException, Module
    from app.scripts.reset_demo import ResetRefused, main, reset_demo

    project = billrite(db)
    architect = db.scalar(select(User).where(User.role == "ARCHITECT", User.active))
    assert architect is not None
    module = db.scalars(select(Module).where(Module.project_id == project.id, Module.program == "MTRVAL")).one()
    # An append-only row hangs off the module: the cascade must still remove it.
    exception = GateException(module_id=module.id, gate="COVERAGE", threshold=50.0, reason="x", actor_id=architect.id)
    db.add(exception)
    db.commit()
    exception_id = exception.id
    audit_before = db.scalar(select(func.count()).select_from(AuditLog)) or 0

    assert main([]) == 2  # Refuses without --confirm.
    result = reset_demo(db, get_settings())
    assert (result.plans_seeded, result.modules_migrated, result.modules_promoted) == (1, 4, 2)
    db.expire_all()
    fresh = billrite(db)
    assert fresh.id != project.id
    assert db.get(GateException, exception_id) is None
    assert (db.scalar(select(func.count()).select_from(AuditLog)) or 0) > audit_before
    assert db.scalars(select(AuditLog).where(AuditLog.action == "demo.reset")).first() is not None

    settings = get_settings().model_copy(update={"demo_mode": False})
    with pytest.raises(ResetRefused):
        reset_demo(db, settings)
