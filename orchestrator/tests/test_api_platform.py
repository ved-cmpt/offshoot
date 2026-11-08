"""Role guards, error envelope, security headers, CORS, health and config."""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import ADMIN_ONLY, ALL_ROLES, ARCHITECT_ONLY, AUDIT_READERS, ENGINEER_PLUS, require_roles
from app.db.models import Project
from app.db.session import get_db
from app.main import app, create_app
from tests.conftest import UserFactory, bearer, login_as

ROLES = ["VIEWER", "ENGINEER", "ARCHITECT", "ADMIN"]


# Later runs attach these guards to real endpoints. This matrix pins what they mean.
@pytest.fixture
def guarded_client(migrated_db: None) -> Iterator[TestClient]:
    test_app: FastAPI = create_app()

    for name, roles in (
        ("all", ALL_ROLES),
        ("engineer", ENGINEER_PLUS),
        ("architect", ARCHITECT_ONLY),
        ("admin", ADMIN_ONLY),
        ("audit", AUDIT_READERS),
    ):
        test_app.get(f"/guarded/{name}", dependencies=[Depends(require_roles(roles))])(lambda: {"ok": True})

    @test_app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret detail that must not reach the client")

    with TestClient(test_app, base_url="http://localhost:8100", raise_server_exceptions=False) as client:
        yield client


GUARD_MATRIX = [
    ("all", {"VIEWER": 200, "ENGINEER": 200, "ARCHITECT": 200, "ADMIN": 200}),
    ("engineer", {"VIEWER": 403, "ENGINEER": 200, "ARCHITECT": 200, "ADMIN": 403}),
    ("architect", {"VIEWER": 403, "ENGINEER": 403, "ARCHITECT": 200, "ADMIN": 403}),
    ("admin", {"VIEWER": 403, "ENGINEER": 403, "ARCHITECT": 403, "ADMIN": 200}),
    ("audit", {"VIEWER": 403, "ENGINEER": 403, "ARCHITECT": 200, "ADMIN": 200}),
]


@pytest.mark.parametrize(("guard", "expected"), GUARD_MATRIX)
def test_role_guard_matrix(
    guarded_client: TestClient, client: TestClient, make_user: UserFactory, guard: str, expected: dict[str, int]
) -> None:
    assert guarded_client.get(f"/guarded/{guard}").status_code == 401
    for role, status in expected.items():
        session = login_as(client, make_user(role))
        response = guarded_client.get(f"/guarded/{guard}", headers=bearer(session))
        assert response.status_code == status, f"{role} on {guard}"
        if status == 403:
            assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize("path", ["/api/v1/projects", f"/api/v1/projects/{uuid.uuid4()}", "/api/v1/admin/audit"])
def test_protected_endpoints_are_401_without_a_token(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 401


@pytest.mark.parametrize(("role", "status"), [("VIEWER", 403), ("ENGINEER", 403), ("ARCHITECT", 200), ("ADMIN", 200)])
def test_audit_log_access_by_role(client: TestClient, make_user: UserFactory, role: str, status: int) -> None:
    session = login_as(client, make_user(role))
    assert client.get("/api/v1/admin/audit", headers=bearer(session)).status_code == status


def test_audit_log_lists_and_filters_actions(client: TestClient, make_user: UserFactory) -> None:
    user = make_user("ADMIN")
    session = login_as(client, user)
    response = client.get("/api/v1/admin/audit", params={"action": "auth.login", "limit": 5}, headers=bearer(session))
    body = response.json()
    assert response.status_code == 200
    assert body["limit"] == 5
    assert all(item["action"] == "auth.login" for item in body["items"])
    assert body["items"][0]["actor_id"] == str(user["id"])


@pytest.mark.parametrize("path", ["/api/v1/projects", "/api/v1/admin/audit"])
def test_pagination_is_capped_at_50(client: TestClient, make_user: UserFactory, path: str) -> None:
    session = login_as(client, make_user("ADMIN"))
    assert client.get(path, params={"limit": 51}, headers=bearer(session)).status_code == 422


@pytest.mark.parametrize("role", ROLES)
def test_every_role_can_list_projects(client: TestClient, db: Session, make_user: UserFactory, role: str) -> None:
    name = f"Project {uuid.uuid4().hex}"
    db.add(Project(name=name, source_kind="UPLOAD", status="IMPORTED"))
    db.commit()
    session = login_as(client, make_user(role))
    response = client.get("/api/v1/projects", headers=bearer(session))
    assert response.status_code == 200
    # Tests share one database, so the newest project can be past the first page.
    total = response.json()["total"]
    last = client.get("/api/v1/projects", params={"offset": max(total - 50, 0)}, headers=bearer(session)).json()
    assert name in [item["name"] for item in last["items"]]


def test_project_detail(client: TestClient, db: Session, make_user: UserFactory) -> None:
    project = Project(name=f"Project {uuid.uuid4().hex}", source_kind="UPLOAD", status="IMPORTED")
    db.add(project)
    db.commit()
    session = login_as(client, make_user())
    body = client.get(f"/api/v1/projects/{project.id}", headers=bearer(session)).json()
    assert body["id"] == str(project.id)
    assert body["source_file_count"] == 0


@pytest.mark.parametrize("project_id", [str(uuid.uuid4()), "not-a-uuid"])
def test_unknown_project_is_404(client: TestClient, make_user: UserFactory, project_id: str) -> None:
    session = login_as(client, make_user())
    response = client.get(f"/api/v1/projects/{project_id}", headers=bearer(session))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def assert_envelope(body: dict[str, Any], code: str) -> None:
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    assert len(body["error"]["request_id"]) == 32


def test_error_envelope_on_unknown_route(client: TestClient) -> None:
    response = client.get("/api/v1/nope")
    assert response.status_code == 404
    assert_envelope(response.json(), "NOT_FOUND")


def test_error_envelope_on_wrong_method(client: TestClient) -> None:
    response = client.delete("/api/v1/healthz")
    assert response.status_code == 405
    assert_envelope(response.json(), "METHOD_NOT_ALLOWED")


def test_error_envelope_on_validation_failure_does_not_echo_the_password(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"password": "hunter2-not-echoed"})
    assert response.status_code == 422
    assert_envelope(response.json(), "VALIDATION_ERROR")
    assert "hunter2" not in response.text


def test_login_rejects_unknown_fields(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"email": "a@b.co", "password": "x", "role": "ADMIN"})
    assert response.status_code == 422


def test_unhandled_errors_become_a_clean_500(guarded_client: TestClient) -> None:
    response = guarded_client.get("/boom")
    assert response.status_code == 500
    assert_envelope(response.json(), "INTERNAL_ERROR")
    assert "secret detail" not in response.text
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


@pytest.mark.parametrize("path", ["/api/v1/healthz", "/api/v1/nope"])
def test_security_headers_on_success_and_failure(client: TestClient, path: str) -> None:
    headers = client.get(path).headers
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert "default-src 'none'" in headers["content-security-policy"]
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["cache-control"] == "no-store"
    assert len(headers["x-request-id"]) == 32


def test_hsts_is_set_when_cookies_are_secure(migrated_db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    assert "strict-transport-security" not in TestClient(app).get("/api/v1/healthz").headers
    monkeypatch.setenv("COOKIE_SECURE", "true")
    get_settings.cache_clear()
    try:
        secure_app = create_app()
        headers = TestClient(secure_app).get("/api/v1/healthz").headers
        assert "max-age=31536000" in headers["strict-transport-security"]
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_cors_allows_the_configured_origin_with_credentials(client: TestClient) -> None:
    response = client.options(
        "/api/v1/auth/refresh",
        headers={
            "Origin": "http://localhost:4200",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-Offshoot-CSRF",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:4200"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_refuses_other_origins(client: TestClient) -> None:
    preflight = client.options(
        "/api/v1/auth/refresh",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers
    simple = client.get("/api/v1/healthz", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in simple.headers


@pytest.mark.parametrize("path", ["/api/v1/healthz", "/healthz"])
def test_healthz(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_when_migrated(client: TestClient) -> None:
    response = client.get("/api/v1/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readyz_when_the_database_is_down(client: TestClient) -> None:
    class BrokenSession:
        def execute(self, *_: Any) -> None:
            raise OperationalError("SELECT 1", {}, Exception("down"))

    app.dependency_overrides[get_db] = BrokenSession
    try:
        response = client.get("/api/v1/readyz")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json() == {"status": "database_unavailable"}


def test_config_publishes_demo_accounts_in_demo_mode(client: TestClient) -> None:
    body = client.get("/api/v1/config").json()
    assert body["demo_mode"] is True
    assert body["ai_mode"] == "mock"
    assert sorted(account["role"] for account in body["demo_accounts"]) == sorted(ROLES)
    assert all(account["password"] for account in body["demo_accounts"])


def test_config_hides_demo_accounts_outside_demo_mode(client: TestClient) -> None:
    settings = get_settings().model_copy(update={"demo_mode": False})
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        body = client.get("/api/v1/config").json()
    finally:
        app.dependency_overrides.clear()
    assert body == {
        "demo_mode": False,
        "ai_mode": "mock",
        "demo_accounts": [],
        "execution_enabled": True,
        "demo_reset_hours": 0,
    }


def test_config_never_exposes_secrets(client: TestClient) -> None:
    text = client.get("/api/v1/config").text
    settings = get_settings()
    assert settings.jwt_secret.get_secret_value() not in text
    assert settings.database_url.get_secret_value() not in text


def test_production_refuses_placeholder_secret_and_insecure_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    base = {"DATABASE_URL": "postgresql+psycopg://x@y/z", "APP_ENV": "production"}
    for name, value in base.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("JWT_SECRET", "local-dev-only-change-me-at-least-32-chars")
    monkeypatch.setenv("COOKIE_SECURE", "true")
    with pytest.raises(ValidationError, match="placeholder"):
        Settings()  # type: ignore[call-arg]
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("COOKIE_SECURE", "false")
    with pytest.raises(ValidationError, match="COOKIE_SECURE"):
        Settings()  # type: ignore[call-arg]
    monkeypatch.setenv("COOKIE_SECURE", "true")
    assert Settings().app_env == "production"  # type: ignore[call-arg]


def test_short_signing_secret_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    monkeypatch.setenv("JWT_SECRET", "too-short")
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]
