"""Request dependencies: current user and role guards."""

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import ApiError, forbidden, unauthorized
from app.core.security import decode_access_token
from app.db.models import User
from app.db.session import get_db

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]

# Who may do what (Blueprint Sections 1.3 and 9, ADR-014). Explicit sets, because ADMIN
# manages users and demo resets but does not run jobs or approve anything.
ALL_ROLES = frozenset({"VIEWER", "ENGINEER", "ARCHITECT", "ADMIN"})
ENGINEER_PLUS = frozenset({"ENGINEER", "ARCHITECT"})
ARCHITECT_ONLY = frozenset({"ARCHITECT"})
ADMIN_ONLY = frozenset({"ADMIN"})
AUDIT_READERS = frozenset({"ARCHITECT", "ADMIN"})


def get_current_user(request: Request, db: DbSession, settings: AppSettings) -> User:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise unauthorized()
    payload = decode_access_token(token, settings)
    if payload is None:
        raise unauthorized("The access token is invalid or has expired.", code="INVALID_ACCESS_TOKEN")
    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except ValueError as exc:
        raise unauthorized("The access token is invalid or has expired.", code="INVALID_ACCESS_TOKEN") from exc
    # The role comes from this row, on every request. The token carries no role.
    user = db.get(User, user_id)
    if user is None or not user.active:
        raise unauthorized("The access token is invalid or has expired.", code="INVALID_ACCESS_TOKEN")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(allowed: frozenset[str]) -> Callable[[User], User]:
    def guard(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise forbidden()
        return user

    return guard


def require_csrf_header(request: Request, settings: AppSettings) -> None:
    """Guard for endpoints authenticated by the refresh cookie.

    A cross-site page cannot set a custom header without a CORS preflight, and the
    CORS policy refuses those origins. If the browser sends an Origin, it must also
    be one we allow.
    """
    if request.headers.get("X-Offshoot-CSRF") != "1":
        raise ApiError(403, "CSRF_REQUIRED", "A required request header is missing.")
    origin = request.headers.get("Origin")
    if origin is None:
        return
    own_origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
    if origin != own_origin and origin not in settings.cors_origins:
        raise ApiError(403, "CSRF_ORIGIN", "This origin is not allowed.")
