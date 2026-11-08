"""Request dependencies: current user and role guards."""

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import ApiError, forbidden, unauthorized
from app.core.security import decode_access_token
from app.db.models import Job, User
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
    host = request.headers.get("host", "")
    # Behind a TLS-terminating proxy the app itself sees http, while the browser's origin is https.
    own_origins = {f"{request.url.scheme}://{host}", *([f"https://{host}"] if settings.cookie_secure else [])}
    if origin not in own_origins and origin not in settings.cors_origins:
        raise ApiError(403, "CSRF_ORIGIN", "This origin is not allowed.")


def require_execution(settings: AppSettings) -> None:
    """Guard for every endpoint that compiles or runs code (ADR-047)."""
    if not settings.execution_enabled:
        raise ApiError(
            403,
            "EXECUTION_DISABLED",
            "This deployment does not compile or run code. Its results come from stored runs.",
        )


def require_job_quota(db: DbSession, settings: AppSettings) -> None:
    """In demo mode, a cap on jobs in any 24 hours, so visitors cannot fill the database (ADR-048)."""
    if not settings.demo_mode:
        return
    recent = db.scalar(
        select(func.count()).select_from(Job).where(Job.created_at > func.now() - text("interval '1 day'"))
    )
    if (recent or 0) >= settings.demo_daily_job_cap:
        raise ApiError(
            429,
            "DEMO_CAP_REACHED",
            "The public demo has run its daily share of jobs. It resets daily; please come back later.",
            {"Retry-After": "3600"},
        )
