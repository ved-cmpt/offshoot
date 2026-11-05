"""Liveness, readiness and public configuration."""

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.deps import AppSettings, DbSession
from app.scripts.demo_accounts import demo_accounts

router = APIRouter(tags=["health"])


class DemoAccount(BaseModel):
    email: str
    password: str
    display_name: str
    role: str


class PublicConfig(BaseModel):
    demo_mode: bool
    ai_mode: str
    demo_accounts: list[DemoAccount]


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(db: DbSession, response: Response) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "database_unavailable"}
    try:
        migrated = db.scalar(text("SELECT count(*) FROM alembic_version"))
    except SQLAlchemyError:
        migrated = 0
    if not migrated:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_migrated"}
    return {"status": "ready"}


@router.get("/config")
def public_config(settings: AppSettings) -> PublicConfig:
    # Demo passwords are published on purpose, and only in demo mode.
    accounts = (
        [DemoAccount(**account.public()) for account in demo_accounts(settings) if account.password]
        if settings.demo_mode
        else []
    )
    return PublicConfig(demo_mode=settings.demo_mode, ai_mode=settings.ai_mode, demo_accounts=accounts)
