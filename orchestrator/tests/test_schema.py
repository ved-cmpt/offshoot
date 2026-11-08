"""The migration: tables, constraints, indexes, least privilege and the append-only audit log."""

import os
import uuid

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

from tests.conftest import run_alembic

TABLES = {
    "users",
    "refresh_tokens",
    "projects",
    "source_files",
    "inventory_items",
    "inventory_edges",
    "rules",
    "plans",
    "modules",
    "code_artifacts",
    "jobs",
    "ai_calls",
    "verification_runs",
    "shadow_mismatches",
    "approvals",
    "audit_logs",
}


@pytest.fixture
def app_engine(migrated_db: None) -> Engine:
    from app.db.session import get_engine

    return get_engine()


def test_every_table_from_the_data_model_exists(owner_engine: Engine) -> None:
    with owner_engine.connect() as connection:
        rows = connection.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        )
        assert {row[0] for row in rows} == TABLES | {"alembic_version"}


def test_models_and_migration_agree(migrated_db: None) -> None:
    run_alembic("check")


def test_all_foreign_keys_state_their_ondelete(owner_engine: Engine) -> None:
    with owner_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT conname, confdeltype FROM pg_constraint "
                "WHERE contype = 'f' AND connamespace = 'public'::regnamespace"
            )
        ).all()
    assert rows
    # 'a' is NO ACTION, the default you get by not saying anything.
    assert [name for name, action in rows if action == "a"] == []


def test_all_timestamps_are_timezone_aware(owner_engine: Engine) -> None:
    with owner_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND data_type = 'timestamp without time zone'"
            )
        ).all()
    assert rows == []


def test_database_runs_in_utc(owner_engine: Engine) -> None:
    with owner_engine.connect() as connection:
        assert connection.scalar(text("SHOW timezone")) == "UTC"


@pytest.mark.parametrize(
    "index",
    [
        "ix_source_files_project_id_kind",
        "ix_inventory_items_project_id_kind",
        "ix_inventory_edges_project_id_kind",
        "ix_rules_project_id_kind",
        "ix_jobs_project_id_kind",
        "ix_jobs_status_created_at",
        "ix_verification_runs_module_id_created_at",
        "ix_shadow_mismatches_module_id_created_at",
    ],
)
def test_listed_indexes_exist(owner_engine: Engine, index: str) -> None:
    with owner_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM pg_indexes WHERE indexname = :i"), {"i": index}) == 1


def test_module_created_at_indexes_are_descending(owner_engine: Engine) -> None:
    with owner_engine.connect() as connection:
        definition = connection.scalar(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_verification_runs_module_id_created_at'")
        )
    assert "created_at DESC" in str(definition)


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO users (email, password_hash, display_name, role) VALUES (:u, 'x', 'x', 'ROOT')",
        "INSERT INTO projects (name, source_kind, status) VALUES (:u, 'FTP', 'IMPORTED')",
        "INSERT INTO projects (name, source_kind, status) VALUES (:u, 'UPLOAD', 'DONE')",
    ],
)
def test_check_constraints_reject_unknown_enum_values(app_engine: Engine, statement: str) -> None:
    with app_engine.connect() as connection, pytest.raises(IntegrityError):
        connection.execute(text(statement), {"u": uuid.uuid4().hex})


def make_project(engine: Engine) -> str:
    with engine.begin() as connection:
        return str(
            connection.scalar(
                text("INSERT INTO projects (name, source_kind, status) VALUES (:n, 'UPLOAD', 'IMPORTED') RETURNING id"),
                {"n": uuid.uuid4().hex},
            )
        )


def add_source(connection: object, project_id: str, path: str) -> None:
    connection.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO source_files (project_id, path, sha256, kind, line_count, content) "
            "VALUES (:p, :path, 'x', 'PROGRAM', 1, 'x')"
        ),
        {"p": project_id, "path": path},
    )


def test_source_path_is_unique_within_a_project(app_engine: Engine) -> None:
    project_id = make_project(app_engine)
    with app_engine.begin() as connection:
        add_source(connection, project_id, "A.cbl")
    with app_engine.connect() as connection, pytest.raises(IntegrityError):
        add_source(connection, project_id, "A.cbl")


def test_source_rows_go_with_their_project(app_engine: Engine) -> None:
    project_id = make_project(app_engine)
    with app_engine.begin() as connection:
        add_source(connection, project_id, "A.cbl")
        connection.execute(text("DELETE FROM projects WHERE id = :p"), {"p": project_id})
        assert (
            connection.scalar(text("SELECT count(*) FROM source_files WHERE project_id = :p"), {"p": project_id}) == 0
        )


def insert_audit(engine: Engine) -> int:
    with engine.begin() as connection:
        return int(connection.scalar(text("INSERT INTO audit_logs (action) VALUES ('test.entry') RETURNING id")))


def test_app_role_can_append_and_read_the_audit_log(app_engine: Engine) -> None:
    entry = insert_audit(app_engine)
    with app_engine.connect() as connection:
        assert connection.scalar(text("SELECT action FROM audit_logs WHERE id = :i"), {"i": entry}) == "test.entry"


@pytest.mark.parametrize(
    "statement",
    ["UPDATE audit_logs SET action = 'x' WHERE id = :i", "DELETE FROM audit_logs WHERE id = :i"],
)
def test_app_role_has_no_grant_to_change_the_audit_log(app_engine: Engine, statement: str) -> None:
    entry = insert_audit(app_engine)
    with app_engine.connect() as connection, pytest.raises(ProgrammingError, match="permission denied"):
        connection.execute(text(statement), {"i": entry})


def test_app_role_cannot_truncate_the_audit_log(app_engine: Engine) -> None:
    with app_engine.connect() as connection, pytest.raises(ProgrammingError, match="permission denied"):
        connection.execute(text("TRUNCATE audit_logs"))


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_logs SET action = 'x' WHERE id = :i",
        "DELETE FROM audit_logs WHERE id = :i",
        "TRUNCATE audit_logs",
    ],
)
def test_triggers_stop_even_the_schema_owner(owner_engine: Engine, app_engine: Engine, statement: str) -> None:
    entry = insert_audit(app_engine)
    with owner_engine.connect() as connection, pytest.raises(DBAPIError, match="append-only"):
        connection.execute(text(statement), {"i": entry})


def test_a_user_with_audit_history_cannot_be_deleted(owner_engine: Engine) -> None:
    with owner_engine.begin() as connection:
        user_id = connection.scalar(
            text(
                "INSERT INTO users (email, password_hash, display_name, role) "
                "VALUES (:e, 'x', 'x', 'VIEWER') RETURNING id"
            ),
            {"e": f"{uuid.uuid4().hex}@test.example"},
        )
        connection.execute(text("INSERT INTO audit_logs (actor_id, action) VALUES (:u, 'test.entry')"), {"u": user_id})
    with owner_engine.connect() as connection, pytest.raises(IntegrityError):
        connection.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})


def test_app_role_is_not_privileged(app_engine: Engine) -> None:
    with app_engine.connect() as connection:
        role = connection.execute(
            text("SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = current_user")
        ).one()
    assert tuple(role) == (False, False, False)


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE sneaky (id int)",
        "DROP TABLE users",
        "ALTER TABLE users ADD COLUMN sneaky int",
        "DROP TRIGGER audit_logs_no_update_delete ON audit_logs",
        "INSERT INTO alembic_version VALUES ('sneaky')",
    ],
)
def test_app_role_cannot_change_the_schema(app_engine: Engine, statement: str) -> None:
    with app_engine.connect() as connection, pytest.raises(ProgrammingError):
        connection.execute(text(statement))


def test_migration_runs_down_and_back_up_on_a_clean_database() -> None:
    owner_url = os.environ["MIGRATION_DATABASE_URL"]
    scratch = f"parityforge_scratch_{uuid.uuid4().hex[:8]}"
    maintenance = create_engine(
        make_url(owner_url).set(database="postgres").render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
    )
    scratch_url = make_url(owner_url).set(database=scratch).render_as_string(hide_password=False)
    with maintenance.connect() as connection:
        connection.execute(text(f"CREATE DATABASE {scratch}"))
    try:
        run_alembic("upgrade", "head", url=scratch_url)
        run_alembic("downgrade", "base", url=scratch_url)
        run_alembic("upgrade", "head", url=scratch_url)
        engine = create_engine(scratch_url)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM audit_logs")) == 0
        engine.dispose()
    finally:
        with maintenance.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS {scratch} WITH (FORCE)"))
        maintenance.dispose()
