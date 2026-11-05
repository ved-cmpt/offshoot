"""Shared fixtures. API tests run against a dedicated database, never the dev one.

The environment is rewritten here, before anything imports `app`. The API connects
as the least-privilege role, exactly as it does in the running stack.
"""

import os
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

TEST_DB = "legacylens_test"


def _for_test_db(url: str) -> str:
    return make_url(url).set(database=TEST_DB).render_as_string(hide_password=False)


_app_url = os.environ.get("DATABASE_URL")
_owner_url = os.environ.get("MIGRATION_DATABASE_URL")
if _app_url and _owner_url:
    os.environ["DATABASE_URL"] = _for_test_db(_app_url)
    os.environ["MIGRATION_DATABASE_URL"] = _for_test_db(_owner_url)
    _owner_maintenance_url = make_url(_owner_url).set(database="postgres").render_as_string(hide_password=False)
os.environ.update(
    {
        "APP_ENV": "test",
        "DEMO_MODE": "true",
        "COOKIE_SECURE": "false",
        "CORS_ORIGINS": "http://localhost:4200",
        "LOGIN_RATE_LIMIT_PER_MINUTE": "5",
        "LOGIN_RATE_LIMIT_IP_PER_MINUTE": "1000",
        "DEMO_PASSWORD_VIEWER": "test-viewer-pass",
        "DEMO_PASSWORD_ENGINEER": "test-engineer-pass",
        "DEMO_PASSWORD_ARCHITECT": "test-architect-pass",
        "DEMO_PASSWORD_ADMIN": "test-admin-pass",
    }
)


def run_alembic(command_name: str, *args: str, url: str | None = None) -> None:
    from alembic.config import Config

    from alembic import command

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", (url or os.environ["MIGRATION_DATABASE_URL"]).replace("%", "%%"))
    getattr(command, command_name)(config, *args)


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[None]:
    maintenance = create_engine(_owner_maintenance_url, isolation_level="AUTOCOMMIT")
    with maintenance.connect() as connection:
        connection.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
        connection.execute(text(f"CREATE DATABASE {TEST_DB}"))
    run_alembic("upgrade", "head")
    yield
    from app.db.session import get_engine

    get_engine().dispose()
    with maintenance.connect() as connection:
        connection.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
    maintenance.dispose()


@pytest.fixture(scope="session")
def owner_engine(migrated_db: None) -> Iterator[Engine]:
    engine = create_engine(os.environ["MIGRATION_DATABASE_URL"])
    yield engine
    engine.dispose()


@pytest.fixture
def db(migrated_db: None) -> Iterator[Session]:
    from app.db.session import get_session_factory

    with get_session_factory()() as session:
        yield session


@pytest.fixture
def client(migrated_db: None) -> Iterator[Any]:
    from fastapi.testclient import TestClient

    from app.core.rate_limit import login_limiter
    from app.main import app

    login_limiter.reset()
    with TestClient(app, base_url="http://localhost:8100") as test_client:
        yield test_client


UserFactory = Callable[..., dict[str, Any]]


@pytest.fixture
def make_user(db: Session) -> UserFactory:
    """Create a user with a unique email. Audit rows are append-only, so tests don't clean up."""

    from app.core.security import hash_password
    from app.db.models import User

    def factory(role: str = "VIEWER", password: str = "correct horse", active: bool = True) -> dict[str, Any]:
        email = f"user-{uuid.uuid4().hex}@test.example"
        user = User(
            email=email,
            password_hash=hash_password(password),
            display_name=f"Test {role.title()}",
            role=role,
            active=active,
        )
        db.add(user)
        db.commit()
        return {"id": user.id, "email": email, "password": password, "role": role}

    return factory


def login_as(client: Any, user: dict[str, Any]) -> dict[str, Any]:
    response = client.post("/api/v1/auth/login", json={"email": user["email"], "password": user["password"]})
    assert response.status_code == 200, response.text
    session: dict[str, Any] = response.json()
    return session


def bearer(session: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {session['access_token']}"}


CSRF = {"X-LegacyLens-CSRF": "1"}
