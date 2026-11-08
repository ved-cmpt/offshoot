"""Session endpoints. The access token goes in JSON; the refresh token only in a cookie."""

import uuid

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.client_ip import client_address
from app.core.config import Settings
from app.core.deps import AppSettings, CurrentUser, DbSession, require_csrf_header
from app.core.errors import ApiError
from app.core.rate_limit import login_limiter
from app.db.models import User
from app.services import auth as auth_service
from app.services.auth import IssuedTokens

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "ll_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    # Capped so that a huge body cannot make Argon2 do pointless work.
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    role: str

    @classmethod
    def of(cls, user: User) -> "UserOut":
        return cls(id=user.id, email=user.email, display_name=user.display_name, role=user.role)


class SessionOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int
    user: UserOut


def _session_response(issued: IssuedTokens, response: Response, settings: Settings) -> SessionOut:
    response.set_cookie(
        REFRESH_COOKIE,
        issued.refresh_token,
        max_age=settings.refresh_token_ttl_seconds,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )
    return SessionOut(access_token=issued.access_token, expires_in=issued.expires_in, user=UserOut.of(issued.user))


def _clear_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


def _enforce_login_rate_limit(request: Request, email: str, settings: Settings) -> None:
    client_ip = client_address(request, settings.trusted_proxy_hops)
    # Per address and account, so that one attacker cannot lock a demo account for
    # everyone; and per address, so that one attacker cannot spray many accounts.
    checks = (
        (f"ip-email:{client_ip}:{email.strip().lower()}", settings.login_rate_limit_per_minute),
        (f"ip:{client_ip}", settings.login_rate_limit_ip_per_minute),
    )
    for key, limit in checks:
        allowed, retry_after = login_limiter.allow(key, limit)
        if not allowed:
            raise ApiError(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "RATE_LIMITED",
                "Too many sign-in attempts. Please wait a minute and try again.",
                {"Retry-After": str(retry_after)},
            )


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response, db: DbSession, settings: AppSettings) -> SessionOut:
    _enforce_login_rate_limit(request, body.email, settings)
    issued = auth_service.login(db, body.email, body.password, settings)
    return _session_response(issued, response, settings)


@router.post("/refresh", dependencies=[Depends(require_csrf_header)])
def refresh(request: Request, response: Response, db: DbSession, settings: AppSettings) -> SessionOut:
    try:
        issued = auth_service.refresh(db, request.cookies.get(REFRESH_COOKIE), settings)
    except ApiError as error:
        # A failure handler builds its own response, so the cookie is cleared there.
        error.headers = {
            **(error.headers or {}),
            "Set-Cookie": _expired_cookie_header(settings),
        }
        raise
    return _session_response(issued, response, settings)


def _expired_cookie_header(settings: Settings) -> str:
    holder = Response()
    _clear_cookie(holder, settings)
    return holder.headers["set-cookie"]


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf_header)])
def logout(request: Request, response: Response, db: DbSession, settings: AppSettings) -> None:
    auth_service.logout(db, request.cookies.get(REFRESH_COOKIE))
    _clear_cookie(response, settings)


@router.get("/me")
def me(user: CurrentUser) -> UserOut:
    return UserOut.of(user)
