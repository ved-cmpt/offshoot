"""The facade's narrow internal API: read the route table, report a shadow comparison.

Not for people. It is authenticated by FACADE_SHARED_SECRET in `X-Facade-Token`, compared in
constant time, and fails closed when the secret is not configured (ADR-039).
"""

import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.core.deps import AppSettings, DbSession
from app.core.errors import ApiError
from app.services import promotion

MIN_SECRET_LENGTH = 16


def require_facade(request: Request, settings: AppSettings) -> None:
    secret = settings.facade_shared_secret.get_secret_value()
    if len(secret) < MIN_SECRET_LENGTH:
        raise ApiError(503, "FACADE_NOT_CONFIGURED", "The facade secret is not configured.")
    given = request.headers.get("X-Facade-Token", "")
    if not hmac.compare_digest(given.encode(), secret.encode()):
        raise ApiError(401, "UNAUTHENTICATED", "Authentication is required.")


router = APIRouter(prefix="/internal/facade", tags=["internal"], dependencies=[Depends(require_facade)])
RECORD = Annotated[str, Field(max_length=256, pattern=r"^[^\n\r]*$")]


@router.get("/routes")
def routes(db: DbSession, settings: AppSettings) -> dict[str, Any]:
    return promotion.route_table(db, settings)


class ShadowReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program: str = Field(pattern=r"^[A-Z][A-Z0-9-]{0,29}$")
    input: RECORD
    legacy: RECORD
    modern: RECORD


@router.post("/shadow")
def shadow(body: ShadowReport, db: DbSession, settings: AppSettings) -> dict[str, Any]:
    result = promotion.record_shadow(db, settings, body.program, body.input, body.legacy, body.modern)
    db.commit()
    return result
