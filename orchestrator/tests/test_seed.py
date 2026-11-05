"""The demo seed: idempotent, audited, and loads the right files only."""

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import AuditLog, Project, SourceFile, User
from app.scripts.demo_accounts import demo_accounts
from app.scripts.seed_demo import run_seed
from tests.conftest import bearer

BILLRITE = Path("/legacy/billrite")


@pytest.fixture
def seeded(db: Session, migrated_db: None) -> None:
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
    accounts = demo_accounts(get_settings())
    assert sorted(account.role for account in accounts) == ["ADMIN", "ARCHITECT", "ENGINEER", "VIEWER"]
    for account in accounts:
        response = client.post("/api/v1/auth/login", json={"email": account.email, "password": account.password})
        assert response.status_code == 200, account.role
        assert response.json()["user"]["role"] == account.role
        me = client.get("/api/v1/auth/me", headers=bearer(response.json()))
        assert me.json()["email"] == account.email


def test_seed_repairs_a_changed_demo_account(db: Session, seeded: None) -> None:
    account = demo_accounts(get_settings())[0]
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
    assert (project.source_kind, project.status) == ("BUNDLED", "IMPORTED")
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
    for account in demo_accounts(get_settings()):
        assert account.password not in logged


def test_seed_refuses_to_run_without_a_demo_password(db: Session, seeded: None) -> None:
    from pydantic import SecretStr

    settings = get_settings().model_copy(update={"demo_password_admin": SecretStr("")})
    with pytest.raises(ValueError, match="ADMIN"):
        run_seed(db, settings)
    db.rollback()


def test_project_list_shows_billrite_with_counts(client: TestClient, seeded: None) -> None:
    account = demo_accounts(get_settings())[0]
    session = client.post("/api/v1/auth/login", json={"email": account.email, "password": account.password}).json()
    items = client.get("/api/v1/projects", headers=bearer(session)).json()["items"]
    billrite = next(item for item in items if item["name"] == "BillRite")
    assert billrite["source_file_count"] == 12
    assert billrite["source_line_count"] > 1400
