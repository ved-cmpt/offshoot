"""User management for admins (Blueprint Section 1.3, ADR-050).

Admins list users, create them, change a display name, role or active flag, and set a password.
Users are never deleted, only deactivated, because the audit log points at them (ADR-014).

In demo mode every account is shared with the public, so nothing here may lock anyone out:
creating users, setting passwords and changing or disabling a demo account all answer 403
`DEMO_ACCOUNTS_LOCKED`. Listing still works. Outside demo mode an admin still cannot deactivate
or demote themselves, so the last way back in is never closed by accident.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.deps import ADMIN_ONLY, AppSettings, DbSession, require_roles
from app.core.errors import ApiError, not_found
from app.core.security import hash_password
from app.db.models import ROLES, RefreshToken, User
from app.scripts.demo_accounts import DEMO_EMAILS
from app.services import audit

router = APIRouter(prefix="/admin/users", tags=["users"])
Admin = Annotated[User, Depends(require_roles(ADMIN_ONLY))]
ROLE_PATTERN = "^(" + "|".join(ROLES) + ")$"
USERNAME_PATTERN = r"^[a-z0-9][a-z0-9_.-]{2,63}$"


class UserRow(BaseModel):
    id: uuid.UUID
    username: str | None
    email: str
    display_name: str
    role: str
    active: bool
    demo: bool


class NewUser(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str | None = Field(default=None, pattern=USERNAME_PATTERN)
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+$")
    display_name: str = Field(min_length=1, max_length=120)
    role: str = Field(pattern=ROLE_PATTERN)
    password: str = Field(min_length=8, max_length=256)


class UserChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: str | None = Field(default=None, pattern=ROLE_PATTERN)
    active: bool | None = None


class NewPassword(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=8, max_length=256)


def _row(user: User) -> UserRow:
    return UserRow(
        id=user.id,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        active=user.active,
        demo=user.email in DEMO_EMAILS,
    )


def _locked(what: str) -> ApiError:
    return ApiError(
        403,
        "DEMO_ACCOUNTS_LOCKED",
        f"The demo accounts are shared with every visitor, so {what} is turned off in demo mode.",
    )


def _load(db: DbSession, user_id: str) -> User:
    try:
        user = db.get(User, uuid.UUID(user_id))
    except ValueError:
        user = None
    if user is None:
        raise not_found("User not found.")
    return user


@router.get("")
def list_users(db: DbSession, _admin: Admin) -> list[UserRow]:
    return [_row(user) for user in db.scalars(select(User).order_by(User.email))]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(body: NewUser, db: DbSession, admin: Admin, settings: AppSettings) -> UserRow:
    if settings.demo_mode:
        raise _locked("creating users")
    user = User(
        username=body.username,
        email=body.email.strip().lower(),
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        role=body.role,
        active=True,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "USER_EXISTS", "A user with this email or username exists.") from None
    audit.record(
        db, "user.created", actor_id=admin.id, entity_type="user", entity_id=user.id, metadata={"role": user.role}
    )
    db.commit()
    return _row(user)


@router.patch("/{user_id}")
def change_user(user_id: str, body: UserChange, db: DbSession, admin: Admin, settings: AppSettings) -> UserRow:
    user = _load(db, user_id)
    if settings.demo_mode and user.email in DEMO_EMAILS:
        raise _locked("changing or disabling a demo account")
    if user.id == admin.id and (body.active is False or (body.role is not None and body.role != "ADMIN")):
        raise ApiError(409, "SELF_LOCKOUT", "You cannot deactivate or demote your own account.")
    changed = body.model_dump(exclude_none=True)
    for name, value in changed.items():
        setattr(user, name, value)
    if body.active is False:
        _revoke_sessions(db, user)
    audit.record(
        db,
        "user.changed",
        actor_id=admin.id,
        entity_type="user",
        entity_id=user.id,
        metadata={"fields": sorted(changed)},
    )
    db.commit()
    return _row(user)


@router.post("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def set_password(user_id: str, body: NewPassword, db: DbSession, admin: Admin, settings: AppSettings) -> None:
    user = _load(db, user_id)
    if settings.demo_mode:
        raise _locked("changing passwords")
    user.password_hash = hash_password(body.password)
    _revoke_sessions(db, user)
    # Which account, and who did it. Never the password.
    audit.record(db, "user.password_set", actor_id=admin.id, entity_type="user", entity_id=user.id)
    db.commit()


def _revoke_sessions(db: DbSession, user: User) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=func.now())
    )
