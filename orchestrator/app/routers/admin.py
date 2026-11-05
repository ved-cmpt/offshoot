"""Administrative reads."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.deps import AUDIT_READERS, DbSession, require_roles
from app.db.models import AuditLog

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_roles(AUDIT_READERS))])


class AuditEntry(BaseModel):
    id: int
    actor_id: uuid.UUID | None
    action: str
    entity_type: str | None
    entity_id: str | None
    safe_metadata: dict[str, Any]
    occurred_at: datetime


class AuditPage(BaseModel):
    items: list[AuditEntry]
    total: int
    limit: int
    offset: int


@router.get("/audit")
def audit_log(
    db: DbSession,
    action: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditPage:
    filters = [AuditLog.action == action] if action else []
    total = db.scalar(select(func.count()).select_from(AuditLog).where(*filters)) or 0
    rows = db.scalars(select(AuditLog).where(*filters).order_by(AuditLog.id.desc()).limit(limit).offset(offset)).all()
    items = [
        AuditEntry(
            id=row.id,
            actor_id=row.actor_id,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            safe_metadata=row.safe_metadata,
            occurred_at=row.occurred_at,
        )
        for row in rows
    ]
    return AuditPage(items=items, total=total, limit=limit, offset=offset)
