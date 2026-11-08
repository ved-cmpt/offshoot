"""Usernames, the published demo accounts, and the user management that demo mode locks (ADR-050)."""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models import AuditLog, User
from app.scripts.demo_accounts import DEMO_PASSWORD, demo_accounts
from app.scripts.seed_demo import SeedResult, seed_users
from tests.conftest import UserFactory, bearer, login_as


@pytest.fixture
def demo_users(db: Session) -> Iterator[None]:
    seed_users(db, get_settings(), SeedResult())
    db.commit()
    yield


@pytest.fixture
def admin(client: TestClient, make_user: UserFactory) -> dict[str, Any]:
    user = make_user("ADMIN")
    return {**user, "headers": bearer(login_as(client, user))}


def demo_user(db: Session, username: str) -> User:
    user = db.scalar(select(User).where(User.username == username))
    assert user is not None
    return user


# --- Signing in ---


@pytest.mark.parametrize("account", demo_accounts(), ids=lambda account: account.username)
def test_each_demo_account_signs_in_with_its_username(client: TestClient, demo_users: None, account: Any) -> None:
    response = client.post("/api/v1/auth/login", json={"username": account.username, "password": DEMO_PASSWORD})
    assert response.status_code == 200, response.text
    body = response.json()["user"]
    assert (body["username"], body["role"], body["display_name"]) == (
        account.username,
        account.role,
        account.display_name,
    )


def test_a_username_is_matched_in_any_case_and_an_email_still_works(client: TestClient, demo_users: None) -> None:
    assert (
        client.post("/api/v1/auth/login", json={"username": " Viewer ", "password": DEMO_PASSWORD}).status_code == 200
    )
    assert (
        client.post("/api/v1/auth/login", json={"username": "viewer@demo.offshoot.dev", "password": DEMO_PASSWORD})
    ).status_code == 200
    assert (
        client.post("/api/v1/auth/login", json={"email": "viewer@demo.offshoot.dev", "password": DEMO_PASSWORD})
    ).status_code == 200


def test_a_wrong_password_or_no_name_is_refused(client: TestClient, demo_users: None) -> None:
    wrong = client.post("/api/v1/auth/login", json={"username": "viewer", "password": "demo12345"})
    assert (wrong.status_code, wrong.json()["error"]["code"]) == (401, "INVALID_CREDENTIALS")
    assert client.post("/api/v1/auth/login", json={"password": DEMO_PASSWORD}).status_code == 422


def test_the_demo_password_is_stored_as_argon2id_and_never_logged(db: Session, demo_users: None) -> None:
    for account in demo_accounts():
        assert demo_user(db, account.username).password_hash.startswith("$argon2id$")
    logged = " ".join(str(row) for row in db.scalars(select(AuditLog.safe_metadata)))
    assert DEMO_PASSWORD not in logged


def test_the_username_login_is_rate_limited_per_name(client: TestClient, demo_users: None) -> None:
    codes = [
        client.post("/api/v1/auth/login", json={"username": "engineer", "password": "wrong"}).status_code
        for _ in range(get_settings().login_rate_limit_per_minute + 1)
    ]
    assert codes[-1] == 429
    assert set(codes[:-1]) == {401}


def test_the_sign_in_page_publishes_usernames_and_the_password(client: TestClient) -> None:
    accounts = client.get("/api/v1/config").json()["demo_accounts"]
    assert {(item["username"], item["password"]) for item in accounts} == {
        ("viewer", DEMO_PASSWORD),
        ("engineer", DEMO_PASSWORD),
        ("architect", DEMO_PASSWORD),
        ("admin", DEMO_PASSWORD),
    }


# --- Demo mode locks every action that could lock others out ---


def test_in_demo_mode_an_admin_can_list_users_but_not_create_one(
    client: TestClient, admin: dict[str, Any], demo_users: None
) -> None:
    listed = client.get("/api/v1/admin/users", headers=admin["headers"])
    assert listed.status_code == 200
    assert {row["username"] for row in listed.json() if row["demo"]} == {"viewer", "engineer", "architect", "admin"}
    created = client.post(
        "/api/v1/admin/users",
        headers=admin["headers"],
        json={
            "email": f"{uuid.uuid4().hex}@test.example",
            "display_name": "New",
            "role": "ADMIN",
            "password": "x" * 12,
        },
    )
    assert (created.status_code, created.json()["error"]["code"]) == (403, "DEMO_ACCOUNTS_LOCKED")


@pytest.mark.parametrize("change", [{"active": False}, {"role": "VIEWER"}, {"display_name": "Taken over"}])
def test_in_demo_mode_no_demo_account_can_be_changed_or_disabled(
    client: TestClient, db: Session, admin: dict[str, Any], demo_users: None, change: dict[str, Any]
) -> None:
    target = demo_user(db, "architect")
    response = client.patch(f"/api/v1/admin/users/{target.id}", headers=admin["headers"], json=change)
    assert (response.status_code, response.json()["error"]["code"]) == (403, "DEMO_ACCOUNTS_LOCKED")
    db.expire_all()
    assert (target.active, target.role, target.display_name) == (True, "ARCHITECT", "Ari Architect")


def test_in_demo_mode_no_password_can_be_changed(
    client: TestClient, db: Session, admin: dict[str, Any], make_user: UserFactory, demo_users: None
) -> None:
    for target_id in (demo_user(db, "viewer").id, make_user("VIEWER")["id"], admin["id"]):
        response = client.post(
            f"/api/v1/admin/users/{target_id}/password", headers=admin["headers"], json={"password": "y" * 12}
        )
        assert (response.status_code, response.json()["error"]["code"]) == (403, "DEMO_ACCOUNTS_LOCKED")
    assert client.post("/api/v1/auth/login", json={"username": "viewer", "password": DEMO_PASSWORD}).status_code == 200


def test_users_can_never_be_deleted(client: TestClient, db: Session, admin: dict[str, Any], demo_users: None) -> None:
    target = demo_user(db, "viewer")
    assert client.delete(f"/api/v1/admin/users/{target.id}", headers=admin["headers"]).status_code == 405


def test_only_an_admin_manages_users(client: TestClient, make_user: UserFactory) -> None:
    for role in ("VIEWER", "ENGINEER", "ARCHITECT"):
        headers = bearer(login_as(client, make_user(role)))
        assert client.get("/api/v1/admin/users", headers=headers).status_code == 403


# --- Outside demo mode the same actions work, and are audited ---


def test_outside_demo_mode_an_admin_creates_changes_and_resets_users(
    client: TestClient, db: Session, admin: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "demo_mode", False)
    name = f"user{uuid.uuid4().hex[:10]}"
    created = client.post(
        "/api/v1/admin/users",
        headers=admin["headers"],
        json={
            "username": name,
            "email": f"{name}@test.example",
            "display_name": "Nia",
            "role": "ENGINEER",
            "password": "first-password",
        },
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]
    assert client.post("/api/v1/auth/login", json={"username": name, "password": "first-password"}).status_code == 200
    duplicate = client.post(
        "/api/v1/admin/users",
        headers=admin["headers"],
        json={
            "username": name,
            "email": f"x{name}@test.example",
            "display_name": "Dup",
            "role": "VIEWER",
            "password": "another-password",
        },
    )
    assert duplicate.status_code == 409

    reset = client.post(
        f"/api/v1/admin/users/{user_id}/password", headers=admin["headers"], json={"password": "second-password"}
    )
    assert reset.status_code == 204
    assert client.post("/api/v1/auth/login", json={"username": name, "password": "first-password"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": name, "password": "second-password"}).status_code == 200

    disabled = client.patch(f"/api/v1/admin/users/{user_id}", headers=admin["headers"], json={"active": False})
    assert disabled.json()["active"] is False
    assert client.post("/api/v1/auth/login", json={"username": name, "password": "second-password"}).status_code == 401
    actions = set(db.scalars(select(AuditLog.action).where(AuditLog.entity_id == user_id)))
    assert {"user.created", "user.password_set", "user.changed"} <= actions
    logged = " ".join(
        str(row) for row in db.scalars(select(AuditLog.safe_metadata).where(AuditLog.entity_id == user_id))
    )
    assert "second-password" not in logged and "first-password" not in logged


def test_an_admin_cannot_lock_themselves_out(
    client: TestClient, admin: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "demo_mode", False)
    for change in ({"active": False}, {"role": "VIEWER"}):
        response = client.patch(f"/api/v1/admin/users/{admin['id']}", headers=admin["headers"], json=change)
        assert (response.status_code, response.json()["error"]["code"]) == (409, "SELF_LOCKOUT")


def test_an_older_password_hash_still_signs_in_until_the_seed_moves_it(client: TestClient, db: Session) -> None:
    name = f"old{uuid.uuid4().hex[:8]}"
    db.add(
        User(
            username=name,
            email=f"{name}@test.example",
            password_hash=hash_password("pw-123456"),
            display_name="Old",
            role="VIEWER",
            active=True,
        )
    )
    db.commit()
    assert client.post("/api/v1/auth/login", json={"username": name, "password": "pw-123456"}).status_code == 200
