"""Audit trail. Adds to the caller's transaction; never stores secrets."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditLog


def record(
    db: Session,
    action: str,
    actor_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: str | uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            safe_metadata=metadata or {},
        )
    )
