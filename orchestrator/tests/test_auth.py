"""Sessions: login, cookies, token handling, rotation, reuse detection, CSRF."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import AuditLog, RefreshToken, User
from app.main import app
from tests.conftest import CSRF, UserFactory, bearer, login_as

ROLES = ["VIEWER", "ENGINEER", "ARCHITECT", "ADMIN"]


def audit_actions(db: Session, user_id: Any) -> list[str]:
    db.expire_all()
    return list(db.scalars(select(AuditLog.action).where(AuditLog.actor_id == user_id).order_by(AuditLog.id)))


@pytest.mark.parametrize("role", ROLES)
def test_login_returns_access_token_and_user_for_each_role(
    client: TestClient, make_user: UserFactory, role: str
) -> None:
    user = make_user(role)
    response = client.post("/api/v1/auth/login", json={"email": user["email"], "password": user["password"]})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == get_settings().access_token_ttl_seconds
    assert body["user"]["email"] == user["email"]
    assert body["user"]["role"] == role
    me = client.get("/api/v1/auth/me", headers=bearer(body))
    assert me.status_code == 200
    assert me.json()["role"] == role


def test_login_email_is_case_insensitive(client: TestClient, make_user: UserFactory) -> None:
    user = make_user()
    response = client.post(
        "/api/v1/auth/login", json={"email": f"  {user['email'].upper()} ", "password": user["password"]}
    )
    assert response.status_code == 200


def test_refresh_token_goes_only_in_a_hardened_cookie(client: TestClient, make_user: UserFactory) -> None:
    user = make_user()
    response = client.post("/api/v1/auth/login", json={"email": user["email"], "password": user["password"]})
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("ll_refresh=")
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/api/v1/auth" in cookie
    assert "refresh" not in response.json()
    value = cookie.split(";")[0].split("=", 1)[1]
    assert value not in response.text


def test_secure_flag_follows_settings(make_user: UserFactory, migrated_db: None) -> None:
    settings = get_settings().model_copy(update={"cookie_secure": True})
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        user = make_user()
        with TestClient(app, base_url="http://localhost:8100") as client:
            response = client.post("/api/v1/auth/login", json={"email": user["email"], "password": user["password"]})
        assert "Secure" in response.headers["set-cookie"]
    finally:
        app.dependency_overrides.clear()


def test_access_token_carries_no_role(client: TestClient, make_user: UserFactory) -> None:
    session = login_as(client, make_user("ARCHITECT"))
    claims = jwt.decode(session["access_token"], options={"verify_signature": False})
    assert "role" not in claims


def test_password_is_stored_as_argon2id(db: Session, make_user: UserFactory, client: TestClient) -> None:
    user = make_user()
    stored = db.scalar(select(User.password_hash).where(User.id == user["id"]))
    assert stored is not None
    assert stored.startswith("$argon2id$")
    assert user["password"] not in stored


def test_refresh_tokens_are_stored_hashed(db: Session, client: TestClient, make_user: UserFactory) -> None:
    user = make_user()
    login_as(client, user)
    value = client.cookies.get("ll_refresh")
    stored = db.scalar(select(RefreshToken.token_hash).where(RefreshToken.user_id == user["id"]))
    assert stored is not None
    assert stored != value
    assert len(stored) == 64


def test_wrong_password_and_unknown_email_look_the_same(client: TestClient, make_user: UserFactory) -> None:
    user = make_user()
    wrong = client.post("/api/v1/auth/login", json={"email": user["email"], "password": "nope"})
    unknown = client.post("/api/v1/auth/login", json={"email": "nobody@test.example", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert "set-cookie" not in wrong.headers


def test_inactive_user_cannot_log_in(client: TestClient, make_user: UserFactory) -> None:
    user = make_user(active=False)
    response = client.post("/api/v1/auth/login", json={"email": user["email"], "password": user["password"]})
    assert response.status_code == 401


def test_login_success_and_failure_are_audited(db: Session, client: TestClient, make_user: UserFactory) -> None:
    user = make_user()
    client.post("/api/v1/auth/login", json={"email": user["email"], "password": "nope"})
    login_as(client, user)
    assert audit_actions(db, user["id"]) == ["auth.login_failed", "auth.login"]


def test_unknown_email_failure_is_audited_without_the_address(db: Session, client: TestClient) -> None:
    client.post("/api/v1/auth/login", json={"email": "ghost@test.example", "password": "secret-value"})
    row = db.scalars(
        select(AuditLog).where(AuditLog.action == "auth.login_failed").order_by(AuditLog.id.desc())
    ).first()
    assert row is not None
    assert row.actor_id is None
    assert "ghost" not in str(row.safe_metadata)
    assert "secret-value" not in str(row.safe_metadata)


def test_login_is_rate_limited(client: TestClient, make_user: UserFactory) -> None:
    user = make_user()
    for _ in range(5):
        assert client.post("/api/v1/auth/login", json={"email": user["email"], "password": "x"}).status_code == 401
    # The limit blocks further attempts even with the right password.
    blocked = client.post("/api/v1/auth/login", json={"email": user["email"], "password": user["password"]})
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"
    assert int(blocked.headers["retry-after"]) >= 1


def test_rate_limit_for_one_account_leaves_others_alone(client: TestClient, make_user: UserFactory) -> None:
    target, other = make_user(), make_user()
    for _ in range(6):
        client.post("/api/v1/auth/login", json={"email": target["email"], "password": "x"})
    assert (
        client.post("/api/v1/auth/login", json={"email": other["email"], "password": other["password"]}).status_code
        == 200
    )


def test_me_requires_a_token(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert response.headers["www-authenticate"] == "Bearer"


def forge(user_id: Any, **changes: Any) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "typ": "access",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        **changes,
    }
    secret = changes.pop("secret", settings.jwt_secret.get_secret_value())
    payload.pop("secret", None)
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.mark.parametrize(
    "changes",
    [
        {"exp": datetime(2020, 1, 1, tzinfo=UTC)},
        {"typ": "refresh"},
        {"aud": "another-api"},
        {"iss": "someone-else"},
        {"secret": "an-entirely-different-signing-secret-value"},
        {"sub": "not-a-uuid"},
        {"sub": "00000000-0000-4000-8000-000000000000"},
    ],
)
def test_bad_tokens_are_rejected(client: TestClient, make_user: UserFactory, changes: dict[str, Any]) -> None:
    token = forge(make_user()["id"], **changes)
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_ACCESS_TOKEN"


def test_unsigned_token_is_rejected(client: TestClient, make_user: UserFactory) -> None:
    settings = get_settings()
    token = jwt.encode(
        {"sub": str(make_user()["id"]), "typ": "access", "iss": settings.jwt_issuer, "aud": settings.jwt_audience},
        key="",
        algorithm="none",
    )
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_a_valid_forged_shape_passes_so_the_rejections_above_mean_something(
    client: TestClient, make_user: UserFactory
) -> None:
    token = forge(make_user()["id"])
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_role_is_read_from_the_database_on_every_request(
    db: Session, client: TestClient, make_user: UserFactory
) -> None:
    user = make_user("ARCHITECT")
    session = login_as(client, user)
    assert client.get("/api/v1/admin/audit", headers=bearer(session)).status_code == 200
    db.execute(text("UPDATE users SET role = 'VIEWER' WHERE id = :id"), {"id": user["id"]})
    db.commit()
    assert client.get("/api/v1/admin/audit", headers=bearer(session)).status_code == 403
    assert client.get("/api/v1/auth/me", headers=bearer(session)).json()["role"] == "VIEWER"


def test_deactivation_ends_access_immediately(db: Session, client: TestClient, make_user: UserFactory) -> None:
    user = make_user()
    session = login_as(client, user)
    db.execute(text("UPDATE users SET active = false WHERE id = :id"), {"id": user["id"]})
    db.commit()
    assert client.get("/api/v1/auth/me", headers=bearer(session)).status_code == 401
    assert client.post("/api/v1/auth/refresh", headers=CSRF).status_code == 401


def test_refresh_rotates_the_cookie_and_issues_a_working_token(client: TestClient, make_user: UserFactory) -> None:
    login_as(client, make_user())
    first = client.cookies.get("ll_refresh")
    response = client.post("/api/v1/auth/refresh", headers=CSRF)
    assert response.status_code == 200
    second = client.cookies.get("ll_refresh")
    assert first and second and first != second
    assert client.get("/api/v1/auth/me", headers=bearer(response.json())).status_code == 200


def test_refresh_without_a_cookie_is_401(client: TestClient) -> None:
    response = client.post("/api/v1/auth/refresh", headers=CSRF)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"


def test_refresh_with_an_unknown_cookie_is_401(client: TestClient) -> None:
    client.cookies.set("ll_refresh", "not-a-real-token", path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh", headers=CSRF).status_code == 401


def test_reusing_a_rotated_token_revokes_the_whole_family(
    db: Session, client: TestClient, make_user: UserFactory
) -> None:
    user = make_user()
    login_as(client, user)
    stolen = client.cookies.get("ll_refresh")
    assert client.post("/api/v1/auth/refresh", headers=CSRF).status_code == 200
    current = client.cookies.get("ll_refresh")

    client.cookies.clear()
    client.cookies.set("ll_refresh", stolen, path="/api/v1/auth")
    replay = client.post("/api/v1/auth/refresh", headers=CSRF)
    assert replay.status_code == 401
    assert "ll_refresh=" in replay.headers["set-cookie"]  # told to drop it

    client.cookies.clear()
    client.cookies.set("ll_refresh", current, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh", headers=CSRF).status_code == 401
    assert "auth.refresh_reuse_detected" in audit_actions(db, user["id"])
    db.expire_all()
    live = db.scalar(
        select(func.count())
        .select_from(RefreshToken)
        .where(RefreshToken.user_id == user["id"], RefreshToken.revoked_at.is_(None))
    )
    assert live == 0


def test_reuse_in_one_session_leaves_another_session_alone(client: TestClient, make_user: UserFactory) -> None:
    user = make_user()
    login_as(client, user)
    other_session = client.cookies.get("ll_refresh")
    client.cookies.clear()
    login_as(client, user)
    stolen = client.cookies.get("ll_refresh")
    client.post("/api/v1/auth/refresh", headers=CSRF)
    client.cookies.clear()
    client.cookies.set("ll_refresh", stolen, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh", headers=CSRF).status_code == 401
    client.cookies.clear()
    client.cookies.set("ll_refresh", other_session, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh", headers=CSRF).status_code == 200


def test_concurrent_use_of_one_token_lets_only_one_through(make_user: UserFactory, client: TestClient) -> None:
    login_as(client, make_user())
    token = client.cookies.get("ll_refresh")

    def attempt(_: int) -> int:
        with TestClient(app, base_url="http://localhost:8100") as racer:
            racer.cookies.set("ll_refresh", token, path="/api/v1/auth")
            return int(racer.post("/api/v1/auth/refresh", headers=CSRF).status_code)

    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = list(pool.map(attempt, range(4)))
    assert sorted(codes) == [200, 401, 401, 401]


def test_expired_refresh_token_is_rejected(db: Session, client: TestClient, make_user: UserFactory) -> None:
    user = make_user()
    login_as(client, user)
    db.execute(
        text("UPDATE refresh_tokens SET expires_at = now() - interval '1 minute' WHERE user_id = :id"),
        {"id": user["id"]},
    )
    db.commit()
    assert client.post("/api/v1/auth/refresh", headers=CSRF).status_code == 401


@pytest.mark.parametrize("path", ["/api/v1/auth/refresh", "/api/v1/auth/logout"])
def test_cookie_endpoints_require_the_csrf_header(client: TestClient, make_user: UserFactory, path: str) -> None:
    login_as(client, make_user())
    cookie = client.cookies.get("ll_refresh")
    response = client.post(path)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_REQUIRED"
    # The refused request did nothing: the same token still works.
    assert client.cookies.get("ll_refresh") == cookie
    assert client.post("/api/v1/auth/refresh", headers=CSRF).status_code == 200


@pytest.mark.parametrize("path", ["/api/v1/auth/refresh", "/api/v1/auth/logout"])
def test_cookie_endpoints_refuse_a_foreign_origin(client: TestClient, make_user: UserFactory, path: str) -> None:
    login_as(client, make_user())
    response = client.post(path, headers={**CSRF, "Origin": "https://evil.example"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_ORIGIN"


def test_allowed_origin_passes_the_csrf_check(client: TestClient, make_user: UserFactory) -> None:
    login_as(client, make_user())
    response = client.post("/api/v1/auth/refresh", headers={**CSRF, "Origin": "http://localhost:4200"})
    assert response.status_code == 200


def test_logout_revokes_the_session_and_clears_the_cookie(
    db: Session, client: TestClient, make_user: UserFactory
) -> None:
    user = make_user()
    login_as(client, user)
    token = client.cookies.get("ll_refresh")
    response = client.post("/api/v1/auth/logout", headers=CSRF)
    assert response.status_code == 204
    assert 'll_refresh=""' in response.headers["set-cookie"] or "Max-Age=0" in response.headers["set-cookie"]
    assert "auth.logout" in audit_actions(db, user["id"])
    client.cookies.clear()
    client.cookies.set("ll_refresh", token, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh", headers=CSRF).status_code == 401


def test_logout_without_a_session_is_harmless(client: TestClient) -> None:
    assert client.post("/api/v1/auth/logout", headers=CSRF).status_code == 204
