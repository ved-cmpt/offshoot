"""Administrative reads: the append-only audit log, for architects and admins."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.deps import AUDIT_READERS, DbSession, require_roles
from app.db.models import AuditLog, User

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_roles(AUDIT_READERS))])


class AuditEntry(BaseModel):
    id: int
    actor_id: uuid.UUID | None
    actor_name: str | None
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
    actions: list[str]
    entity_types: list[str]


@router.get("/audit")
def audit_log(
    db: DbSession,
    action: str | None = None,
    action_prefix: Annotated[str | None, Query(max_length=40, pattern=r"^[a-z_]+\.?$")] = None,
    entity_type: Annotated[str | None, Query(max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditPage:
    filters: list[Any] = []
    if action:
        filters.append(AuditLog.action == action)
    if action_prefix:
        filters.append(AuditLog.action.startswith(action_prefix, autoescape=True))
    if entity_type:
        filters.append(AuditLog.entity_type == entity_type)
    total = db.scalar(select(func.count()).select_from(AuditLog).where(*filters)) or 0
    rows = db.scalars(select(AuditLog).where(*filters).order_by(AuditLog.id.desc()).limit(limit).offset(offset)).all()
    actor_ids = {row.actor_id for row in rows if row.actor_id}
    names = (
        dict(db.execute(select(User.id, User.display_name).where(User.id.in_(actor_ids))).all()) if actor_ids else {}
    )
    items = [
        AuditEntry(
            id=row.id,
            actor_id=row.actor_id,
            actor_name=names.get(row.actor_id) if row.actor_id else None,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            safe_metadata=row.safe_metadata,
            occurred_at=row.occurred_at,
        )
        for row in rows
    ]
    actions = list(db.scalars(select(AuditLog.action).distinct().order_by(AuditLog.action)))
    types = [
        value for value in db.scalars(select(AuditLog.entity_type).distinct().order_by(AuditLog.entity_type)) if value
    ]
    return AuditPage(items=items, total=total, limit=limit, offset=offset, actions=actions, entity_types=types)
