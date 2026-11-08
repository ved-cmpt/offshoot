"""Capture and restore the demo project's rows (ADR-048).

A deployment without a sandbox cannot run the seed again, so its daily reset restores a stored
copy of the project as the seed left it: sources, inventory, rules, jobs, AI call records, the
plan, modules, artifacts, verification runs, gate exceptions and shadow mismatches. Every row
keeps its id. Columns that point at users are stored as emails and mapped back on restore, so a
snapshot taken from one database can be imported into another whose users have other ids.

Users, approvals and the append-only audit log are never part of a snapshot and are never
touched by a restore (ADR-014, ADR-037); the restore itself is audited.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Column, Table, delete, func, insert, select, text, update
from sqlalchemy import types as sqltypes
from sqlalchemy.orm import Session

from app.db.models import (
    AiCall,
    Base,
    CodeArtifact,
    DemoSnapshot,
    GateException,
    InventoryEdge,
    InventoryItem,
    Job,
    Module,
    Plan,
    Project,
    Rule,
    ShadowMismatch,
    SourceFile,
    User,
    VerificationRun,
)
from app.services import audit

FORMAT = "offshoot-demo-snapshot/1"
# A fixed key for pg_advisory_xact_lock, so two processes never restore at once.
RESTORE_LOCK = 4_771_202_611
# Insert order respects every foreign key. The three self or cyclic references are written
# afterwards (DEFERRED), because the rows they point at may come later in the same table.
TABLE_ORDER = (
    "projects",
    "source_files",
    "inventory_items",
    "inventory_edges",
    "jobs",
    "ai_calls",
    "rules",
    "plans",
    "modules",
    "code_artifacts",
    "verification_runs",
    "gate_exceptions",
    "shadow_mismatches",
)
DEFERRED = {
    "modules": ("current_artifact_id",),
    "code_artifacts": ("parent_id",),
    "verification_runs": ("base_run_id",),
}


class SnapshotError(RuntimeError):
    pass


def _table(name: str) -> Table:
    return Base.metadata.tables[name]


def _user_columns(table: Table) -> list[str]:
    return [
        column.name for column in table.columns if any(fk.column.table.name == "users" for fk in column.foreign_keys)
    ]


def _encode(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _decoder(column: Column[Any]) -> Callable[[Any], Any]:
    kind = column.type
    if isinstance(kind, sqltypes.Uuid):
        return uuid.UUID
    if isinstance(kind, sqltypes.DateTime):
        return datetime.fromisoformat
    if isinstance(kind, sqltypes.Numeric) and not isinstance(kind, sqltypes.Float):
        return Decimal
    return lambda value: value


def _selections(db: Session, project_id: uuid.UUID) -> dict[str, Any]:
    modules = select(Module.id).where(Module.project_id == project_id)
    jobs = select(Job.id).where(Job.project_id == project_id)
    return {
        "projects": select(Project).where(Project.id == project_id),
        "source_files": select(SourceFile).where(SourceFile.project_id == project_id),
        "inventory_items": select(InventoryItem).where(InventoryItem.project_id == project_id),
        "inventory_edges": select(InventoryEdge).where(InventoryEdge.project_id == project_id),
        "jobs": select(Job).where(Job.project_id == project_id),
        "ai_calls": select(AiCall).where(AiCall.job_id.in_(jobs)),
        "rules": select(Rule).where(Rule.project_id == project_id),
        "plans": select(Plan).where(Plan.project_id == project_id),
        "modules": select(Module).where(Module.project_id == project_id),
        "code_artifacts": select(CodeArtifact).where(CodeArtifact.module_id.in_(modules)),
        "verification_runs": select(VerificationRun).where(VerificationRun.module_id.in_(modules)),
        "gate_exceptions": select(GateException).where(GateException.module_id.in_(modules)),
        "shadow_mismatches": select(ShadowMismatch).where(ShadowMismatch.module_id.in_(modules)),
    }


def find_project(db: Session, name: str, source_kind: str = "BUNDLED") -> Project | None:
    return db.scalar(select(Project).where(Project.name == name, Project.source_kind == source_kind))


def build_payload(db: Session, project: Project) -> dict[str, Any]:
    """Every row of the project, as JSON. Nothing is written."""
    busy = db.scalar(
        select(func.count()).select_from(Job).where(Job.project_id == project.id, Job.status.in_(("QUEUED", "RUNNING")))
    )
    if busy:
        raise SnapshotError("The project still has queued or running jobs. Wait for them to finish.")
    emails: dict[uuid.UUID, str] = dict(db.execute(select(User.id, User.email)).all())
    tables: dict[str, list[dict[str, Any]]] = {}
    referenced: set[uuid.UUID] = set()
    for name, query in _selections(db, project.id).items():
        table = _table(name)
        user_columns = _user_columns(table)
        rows = []
        for row in db.execute(query.with_only_columns(*table.columns)).mappings():
            for column in user_columns:
                if row[column] is not None:
                    referenced.add(row[column])
            rows.append({key: _encode(value) for key, value in row.items()})
        tables[name] = rows
    return {
        "format": FORMAT,
        "project": {"name": project.name, "source_kind": project.source_kind, "id": str(project.id)},
        "users": {str(user_id): emails[user_id] for user_id in referenced if user_id in emails},
        "tables": tables,
    }


def counts(payload: dict[str, Any]) -> dict[str, int]:
    return {name: len(rows) for name, rows in payload["tables"].items()}


def store(db: Session, payload: dict[str, Any]) -> DemoSnapshot:
    """Keep this payload as the one snapshot for its project name."""
    if payload.get("format") != FORMAT:
        raise SnapshotError("This is not a demo snapshot of a supported format.")
    name = payload["project"]["name"]
    db.execute(delete(DemoSnapshot).where(DemoSnapshot.project_name == name))
    snapshot = DemoSnapshot(project_name=name, payload=payload, row_counts=counts(payload))
    db.add(snapshot)
    db.flush()
    audit.record(
        db, "demo.snapshot_stored", entity_type="project", entity_id=payload["project"]["id"], metadata=counts(payload)
    )
    return snapshot


def capture(db: Session, project: Project) -> DemoSnapshot:
    return store(db, build_payload(db, project))


def latest(db: Session, name: str | None = None) -> DemoSnapshot | None:
    query = select(DemoSnapshot).order_by(DemoSnapshot.captured_at.desc()).limit(1)
    if name is not None:
        query = query.where(DemoSnapshot.project_name == name)
    return db.scalar(query)


def _user_ids(db: Session, payload: dict[str, Any]) -> dict[str, uuid.UUID | None]:
    by_email: dict[str, uuid.UUID] = dict(db.execute(select(User.email, User.id)).all())
    return {old: by_email.get(email) for old, email in payload["users"].items()}


def _decode_row(
    table: Table,
    raw: dict[str, Any],
    users: dict[str, uuid.UUID | None],
    later: list[tuple[Table, Any, dict[str, Any]]],
) -> dict[str, Any]:
    """One stored row back to column values. Self and cyclic references go to `later`."""
    user_columns = set(_user_columns(table))
    row: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in table.columns:
            raise SnapshotError(f"The snapshot has a column the schema does not: {table.name}.{key}")
        if value is None:
            row[key] = None
        elif key in user_columns:
            mapped = users.get(value)
            if mapped is None and not table.columns[key].nullable:
                raise SnapshotError(f"A user in the snapshot does not exist here: {table.name}.{key}")
            row[key] = mapped
        else:
            row[key] = _decoder(table.columns[key])(value)
    pending = {key: row[key] for key in DEFERRED.get(table.name, ()) if row.get(key) is not None}
    for key in DEFERRED.get(table.name, ()):
        row[key] = None
    if pending:
        later.append((table, row["id"], pending))
    return row


def restore(
    db: Session, snapshot: DemoSnapshot, wait: bool = True, at: datetime | None = None
) -> dict[str, int] | None:
    """Replace the project with the snapshot's rows, in one transaction. The caller commits.

    Returns the row counts, or None when `wait` is false and another process holds the lock.
    """
    if wait:
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": RESTORE_LOCK})
    elif not db.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": RESTORE_LOCK}):
        return None
    payload = snapshot.payload
    if payload.get("format") != FORMAT:
        raise SnapshotError("This is not a demo snapshot of a supported format.")
    meta = payload["project"]
    users = _user_ids(db, payload)
    existing = find_project(db, meta["name"], meta["source_kind"])
    removed = str(existing.id) if existing is not None else None
    if existing is not None:
        db.delete(existing)
        db.flush()
    stale = db.get(Project, uuid.UUID(meta["id"]))
    if stale is not None:  # The same id under another name: it would collide.
        db.delete(stale)
        db.flush()
    later: list[tuple[Table, Any, dict[str, Any]]] = []
    for name in TABLE_ORDER:
        rows = payload["tables"].get(name, [])
        if rows:
            table = _table(name)
            values = [_decode_row(table, raw, users, later) for raw in rows]
            db.execute(insert(table), values)
    for table, row_id, pending in later:
        db.execute(update(table).where(table.c.id == row_id).values(**pending))
    snapshot.last_restored_at = at or datetime.now(UTC)
    restored = counts(payload)
    audit.record(
        db,
        "demo.reset",
        entity_type="project",
        entity_id=meta["id"],
        metadata={"mode": "snapshot", "removed_project": removed, "snapshot_id": str(snapshot.id), **restored},
    )
    return restored
