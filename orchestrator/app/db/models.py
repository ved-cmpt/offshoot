"""The full data model (Blueprint Section 8.1).

Enums are VARCHAR + CHECK. Timestamps are timezone-aware and stored in UTC. Every
foreign key states its ondelete. Later runs add behaviour, not new core tables.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ROLES = ("VIEWER", "ENGINEER", "ARCHITECT", "ADMIN")
PROJECT_SOURCE_KINDS = ("BUNDLED", "UPLOAD")
PROJECT_STATUSES = ("IMPORTED", "ANALYZING", "ANALYZED", "FAILED")
SOURCE_FILE_KINDS = ("PROGRAM", "COPYBOOK", "DATA_LAYOUT")
INVENTORY_ITEM_KINDS = ("PROGRAM", "PARAGRAPH", "SECTION", "FILE", "RECORD", "FIELD")
INVENTORY_EDGE_KINDS = ("PERFORMS", "GOES_TO", "CALLS", "READS", "WRITES", "USES")
RULE_KINDS = ("CALCULATION", "VALIDATION", "DECISION", "DATA", "PROCESS")
RULE_STATES = ("PROPOSED", "VERIFIED", "REJECTED", "EDITED")
PLAN_STATES = ("PROPOSED", "APPROVED", "REJECTED")
MODULE_STATES = ("PENDING", "MIGRATING", "BUILD_FAILED", "VERIFYING", "BLOCKED", "VERIFIED", "APPROVED", "REJECTED")
FACADE_MODES = ("LEGACY", "SHADOW", "MODERN")
JOB_KINDS = ("ANALYZE", "EXTRACT", "PLAN", "MIGRATE", "BUILD", "VERIFY", "REPAIR", "MUTATE")
JOB_STATUSES = ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED")
AI_MODES = ("mock", "gemini")
AI_CALL_STATUSES = ("OK", "FAILED")
APPROVAL_ENTITY_TYPES = ("RULE", "PLAN", "MODULE")
APPROVAL_DECISIONS = ("APPROVED", "REJECTED", "VERIFIED")

MAX_SOURCE_CONTENT_BYTES = 2 * 1024 * 1024

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def enum_check(column: str, values: tuple[str, ...], name: str | None = None) -> CheckConstraint:
    listed = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f'"{column}" IN ({listed})', name=name or column)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )


def created_at_column() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (enum_check("role", ROLES),)

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = created_at_column()


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_family_id", "family_id"), Index("ix_refresh_tokens_user_id", "user_id"))

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        enum_check("source_kind", PROJECT_SOURCE_KINDS),
        enum_check("status", PROJECT_STATUSES),
        # A bundled source set exists once, which makes the seed idempotent.
        Index(
            "uq_projects_bundled_name",
            "name",
            unique=True,
            postgresql_where=text("source_kind = 'BUNDLED'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_at_column()


class SourceFile(Base):
    __tablename__ = "source_files"
    __table_args__ = (
        UniqueConstraint("project_id", "path", name="uq_source_files_project_id_path"),
        enum_check("kind", SOURCE_FILE_KINDS),
        CheckConstraint(f"octet_length(content) <= {MAX_SOURCE_CONTENT_BYTES}", name="content_size"),
        Index("ix_source_files_project_id_kind", "project_id", "kind"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)


class InventoryItem(Base):
    __tablename__ = "inventory_items"
    __table_args__ = (
        enum_check("kind", INVENTORY_ITEM_KINDS),
        Index("ix_inventory_items_project_id_kind", "project_id", "kind"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_files.id", ondelete="CASCADE"))
    start_line: Mapped[int | None] = mapped_column(Integer)
    end_line: Mapped[int | None] = mapped_column(Integer)
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))


class InventoryEdge(Base):
    __tablename__ = "inventory_edges"
    __table_args__ = (
        enum_check("kind", INVENTORY_EDGE_KINDS),
        Index("ix_inventory_edges_project_id_kind", "project_id", "kind"),
        Index("ix_inventory_edges_from_item", "from_item"),
        Index("ix_inventory_edges_to_item", "to_item"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    from_item: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False)
    to_item: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)


class Rule(Base):
    __tablename__ = "rules"
    __table_args__ = (
        enum_check("kind", RULE_KINDS),
        enum_check("state", RULE_STATES),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_range"),
        Index("ix_rules_project_id_kind", "project_id", "kind"),
        Index("ix_rules_project_id_program_state", "project_id", "program", "state"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    program: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    inputs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    outputs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    conditions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    examples: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    spans: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    flags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    confidence: Mapped[float | None] = mapped_column(Float)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'PROPOSED'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (
        enum_check("state", PLAN_STATES),
        UniqueConstraint("project_id", "version", name="uq_plans_project_id_version"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    services: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    order: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    risks: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    estimate: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'PROPOSED'"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_at_column()


class Module(Base):
    __tablename__ = "modules"
    __table_args__ = (
        enum_check("state", MODULE_STATES),
        enum_check("facade_mode", FACADE_MODES),
        UniqueConstraint("project_id", "program", name="uq_modules_project_id_program"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    program: Mapped[str] = mapped_column(String(64), nullable=False)
    target_service: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'PENDING'"))
    facade_mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'LEGACY'"))
    # Circular with code_artifacts, so the constraint is added after both tables exist.
    current_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("code_artifacts.id", ondelete="SET NULL", use_alter=True, name="fk_modules_current_artifact_id")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = created_at_column()


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        enum_check("kind", JOB_KINDS),
        enum_check("status", JOB_STATUSES),
        Index("ix_jobs_project_id_kind", "project_id", "kind"),
        Index("ix_jobs_status_created_at", "status", "created_at"),
        Index("ix_jobs_project_id_input_hash", "project_id", "kind", "input_hash"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'QUEUED'"))
    input_hash: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = created_at_column()


class CodeArtifact(Base):
    __tablename__ = "code_artifacts"
    __table_args__ = (UniqueConstraint("module_id", "version", name="uq_code_artifacts_module_id_version"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    module_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    files: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    produced_by_job: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = created_at_column()


class AiCall(Base):
    __tablename__ = "ai_calls"
    __table_args__ = (
        enum_check("mode", AI_MODES),
        enum_check("status", AI_CALL_STATUSES),
        Index("ix_ai_calls_job_id", "job_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    tokens: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    redacted_input: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()


class VerificationRun(Base):
    __tablename__ = "verification_runs"
    __table_args__ = (Index("ix_verification_runs_module_id_created_at", "module_id", text("created_at DESC")),)

    id: Mapped[uuid.UUID] = uuid_pk()
    module_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"), nullable=False)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("code_artifacts.id", ondelete="SET NULL"))
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cases: Mapped[int] = mapped_column(Integer, nullable=False)
    passed: Mapped[int] = mapped_column(Integer, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, nullable=False)
    coverage_pct: Mapped[float | None] = mapped_column(Float)
    mutation_score: Mapped[float | None] = mapped_column(Float)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = created_at_column()


class ShadowMismatch(Base):
    __tablename__ = "shadow_mismatches"
    __table_args__ = (Index("ix_shadow_mismatches_module_id_created_at", "module_id", text("created_at DESC")),)

    id: Mapped[uuid.UUID] = uuid_pk()
    module_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    diff: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = created_at_column()


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        enum_check("entity_type", APPROVAL_ENTITY_TYPES),
        enum_check("decision", APPROVAL_DECISIONS),
        Index("ix_approvals_entity", "entity_type", "entity_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    # RESTRICT: who decided must survive. Deactivate users rather than deleting them.
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = created_at_column()


class AuditLog(Base):
    """Append-only. Triggers and grants in the migration reject UPDATE, DELETE and TRUNCATE."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_occurred_at", text("occurred_at DESC")),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_action", "action"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    # RESTRICT, not SET NULL: SET NULL would be an UPDATE, which the trigger rejects.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    safe_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
