"""Initial schema: the full data model, least-privilege grants, append-only audit log.

Revision ID: 0001
Revises:
Create Date: 2026-11-05 01:51:01.898455+00:00
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The least-privilege login the API uses. It is deployment config, not schema: the
# name comes from APP_DB_ROLE and must match the role db/init creates (ADR-029).
APP_ROLE = os.environ.get("APP_DB_ROLE", "offshoot_app")
if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", APP_ROLE):
    raise ValueError("APP_DB_ROLE must be a lower-case SQL identifier")


def _create_audit_guards() -> None:
    """Make audit_logs append-only for everyone, including the schema owner."""
    op.execute(
        """
        CREATE FUNCTION audit_logs_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs is append-only: % is not allowed', TG_OP
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_logs_no_update_delete
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION audit_logs_reject_change()
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_logs_no_truncate
        BEFORE TRUNCATE ON audit_logs
        FOR EACH STATEMENT EXECUTE FUNCTION audit_logs_reject_change()
        """
    )


def _grant_app_role() -> None:
    """The API connects as this role: data access only, no schema changes (ADR-014)."""
    # db/init creates the role with a login locally. Elsewhere, create it without one,
    # so that the grants apply and an operator can set the login separately.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
            END IF;
        END;
        $$
        """
    )
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM {APP_ROLE}")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("\"role\" IN ('VIEWER', 'ENGINEER', 'ARCHITECT', 'ADMIN')", name=op.f("ck_users_role")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "approvals",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("\"decision\" IN ('APPROVED', 'REJECTED', 'VERIFIED')", name=op.f("ck_approvals_decision")),
        sa.CheckConstraint("\"entity_type\" IN ('RULE', 'PLAN', 'MODULE')", name=op.f("ck_approvals_entity_type")),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_approvals_actor_id_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approvals")),
    )
    op.create_index("ix_approvals_entity", "approvals", ["entity_type", "entity_id"], unique=False)
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=True),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column(
            "safe_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_audit_logs_actor_id_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"], unique=False)
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"], unique=False)
    op.create_index("ix_audit_logs_occurred_at", "audit_logs", [sa.literal_column("occurred_at DESC")], unique=False)
    op.create_table(
        "projects",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("\"source_kind\" IN ('BUNDLED', 'UPLOAD')", name=op.f("ck_projects_source_kind")),
        sa.CheckConstraint(
            "\"status\" IN ('IMPORTED', 'ANALYZING', 'ANALYZED', 'FAILED')", name=op.f("ck_projects_status")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_projects_created_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
    )
    op.create_index(
        "uq_projects_bundled_name",
        "projects",
        ["name"],
        unique=True,
        postgresql_where=sa.text("source_kind = 'BUNDLED'"),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("family_id", sa.UUID(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_refresh_tokens_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"], unique=False)
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"], unique=False)
    op.create_table(
        "jobs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'QUEUED'"), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "metrics", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "\"kind\" IN ('ANALYZE', 'EXTRACT', 'PLAN', 'MIGRATE', 'BUILD', 'VERIFY', 'REPAIR', 'MUTATE')",
            name=op.f("ck_jobs_kind"),
        ),
        sa.CheckConstraint("\"status\" IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')", name=op.f("ck_jobs_status")),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_jobs_project_id_projects"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index("ix_jobs_project_id_input_hash", "jobs", ["project_id", "kind", "input_hash"], unique=False)
    op.create_index("ix_jobs_project_id_kind", "jobs", ["project_id", "kind"], unique=False)
    op.create_index("ix_jobs_status_created_at", "jobs", ["status", "created_at"], unique=False)
    op.create_table(
        "modules",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("program", sa.String(length=64), nullable=False),
        sa.Column("target_service", sa.String(length=120), nullable=True),
        sa.Column("state", sa.String(length=16), server_default=sa.text("'PENDING'"), nullable=False),
        sa.Column("facade_mode", sa.String(length=16), server_default=sa.text("'LEGACY'"), nullable=False),
        sa.Column("current_artifact_id", sa.UUID(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("\"facade_mode\" IN ('LEGACY', 'SHADOW', 'MODERN')", name=op.f("ck_modules_facade_mode")),
        sa.CheckConstraint(
            "\"state\" IN ('PENDING', 'MIGRATING', 'BUILD_FAILED', 'VERIFYING', 'BLOCKED', 'VERIFIED', 'APPROVED', 'REJECTED')",
            name=op.f("ck_modules_state"),
        ),
        sa.ForeignKeyConstraint(
            ["current_artifact_id"],
            ["code_artifacts.id"],
            name="fk_modules_current_artifact_id",
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_modules_project_id_projects"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_modules")),
        sa.UniqueConstraint("project_id", "program", name="uq_modules_project_id_program"),
    )
    op.create_table(
        "plans",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "services", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "order", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "risks", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "estimate", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("state", sa.String(length=16), server_default=sa.text("'PROPOSED'"), nullable=False),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("\"state\" IN ('PROPOSED', 'APPROVED', 'REJECTED')", name=op.f("ck_plans_state")),
        sa.ForeignKeyConstraint(
            ["approved_by"], ["users.id"], name=op.f("fk_plans_approved_by_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_plans_project_id_projects"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plans")),
        sa.UniqueConstraint("project_id", "version", name="uq_plans_project_id_version"),
    )
    op.create_table(
        "rules",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("program", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column(
            "inputs", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "outputs", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "conditions", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "examples", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "spans", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "flags", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("state", sa.String(length=16), server_default=sa.text("'PROPOSED'"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("decided_by", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "\"kind\" IN ('CALCULATION', 'VALIDATION', 'DECISION', 'DATA', 'PROCESS')", name=op.f("ck_rules_kind")
        ),
        sa.CheckConstraint("\"state\" IN ('PROPOSED', 'VERIFIED', 'REJECTED', 'EDITED')", name=op.f("ck_rules_state")),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name=op.f("ck_rules_confidence_range")
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"], ["users.id"], name=op.f("fk_rules_decided_by_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_rules_project_id_projects"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rules")),
    )
    op.create_index("ix_rules_project_id_kind", "rules", ["project_id", "kind"], unique=False)
    op.create_index("ix_rules_project_id_program_state", "rules", ["project_id", "program", "state"], unique=False)
    op.create_table(
        "source_files",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.CheckConstraint("\"kind\" IN ('PROGRAM', 'COPYBOOK', 'DATA_LAYOUT')", name=op.f("ck_source_files_kind")),
        sa.CheckConstraint("octet_length(content) <= 2097152", name=op.f("ck_source_files_content_size")),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_source_files_project_id_projects"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_files")),
        sa.UniqueConstraint("project_id", "path", name="uq_source_files_project_id_path"),
    )
    op.create_index("ix_source_files_project_id_kind", "source_files", ["project_id", "kind"], unique=False)
    op.create_table(
        "ai_calls",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("model_id", sa.String(length=120), nullable=True),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column(
            "tokens", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("redacted_input", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("\"mode\" IN ('mock', 'gemini')", name=op.f("ck_ai_calls_mode")),
        sa.CheckConstraint("\"status\" IN ('OK', 'FAILED')", name=op.f("ck_ai_calls_status")),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_ai_calls_job_id_jobs"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_calls")),
    )
    op.create_index("ix_ai_calls_job_id", "ai_calls", ["job_id"], unique=False)
    op.create_table(
        "code_artifacts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("module_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "files", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("produced_by_job", sa.UUID(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["module_id"], ["modules.id"], name=op.f("fk_code_artifacts_module_id_modules"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["produced_by_job"], ["jobs.id"], name=op.f("fk_code_artifacts_produced_by_job_jobs"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_code_artifacts")),
        sa.UniqueConstraint("module_id", "version", name="uq_code_artifacts_module_id_version"),
    )
    op.create_table(
        "inventory_items",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("file_id", sa.UUID(), nullable=True),
        sa.Column("start_line", sa.Integer(), nullable=True),
        sa.Column("end_line", sa.Integer(), nullable=True),
        sa.Column(
            "attrs", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.CheckConstraint(
            "\"kind\" IN ('PROGRAM', 'PARAGRAPH', 'SECTION', 'FILE', 'RECORD', 'FIELD')",
            name=op.f("ck_inventory_items_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["file_id"], ["source_files.id"], name=op.f("fk_inventory_items_file_id_source_files"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_inventory_items_project_id_projects"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_items")),
    )
    op.create_index("ix_inventory_items_project_id_kind", "inventory_items", ["project_id", "kind"], unique=False)
    op.create_table(
        "shadow_mismatches",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("module_id", sa.UUID(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "diff", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["module_id"], ["modules.id"], name=op.f("fk_shadow_mismatches_module_id_modules"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shadow_mismatches")),
    )
    op.create_index(
        "ix_shadow_mismatches_module_id_created_at",
        "shadow_mismatches",
        ["module_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "inventory_edges",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("from_item", sa.UUID(), nullable=False),
        sa.Column("to_item", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "\"kind\" IN ('PERFORMS', 'GOES_TO', 'CALLS', 'READS', 'WRITES', 'USES')",
            name=op.f("ck_inventory_edges_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["from_item"],
            ["inventory_items.id"],
            name=op.f("fk_inventory_edges_from_item_inventory_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_inventory_edges_project_id_projects"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["to_item"],
            ["inventory_items.id"],
            name=op.f("fk_inventory_edges_to_item_inventory_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_edges")),
    )
    op.create_index("ix_inventory_edges_from_item", "inventory_edges", ["from_item"], unique=False)
    op.create_index("ix_inventory_edges_project_id_kind", "inventory_edges", ["project_id", "kind"], unique=False)
    op.create_index("ix_inventory_edges_to_item", "inventory_edges", ["to_item"], unique=False)
    op.create_table(
        "verification_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("module_id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=True),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("cases", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("coverage_pct", sa.Float(), nullable=True),
        sa.Column("mutation_score", sa.Float(), nullable=True),
        sa.Column(
            "report", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["code_artifacts.id"],
            name=op.f("fk_verification_runs_artifact_id_code_artifacts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["module_id"], ["modules.id"], name=op.f("fk_verification_runs_module_id_modules"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verification_runs")),
    )
    op.create_index(
        "ix_verification_runs_module_id_created_at",
        "verification_runs",
        ["module_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    # modules and code_artifacts reference each other, so this one comes last.
    op.create_foreign_key(
        "fk_modules_current_artifact_id",
        "modules",
        "code_artifacts",
        ["current_artifact_id"],
        ["id"],
        ondelete="SET NULL",
    )
    _create_audit_guards()
    _grant_app_role()


def downgrade() -> None:
    op.drop_constraint("fk_modules_current_artifact_id", "modules", type_="foreignkey")
    op.drop_index("ix_verification_runs_module_id_created_at", table_name="verification_runs")
    op.drop_table("verification_runs")
    op.drop_index("ix_inventory_edges_to_item", table_name="inventory_edges")
    op.drop_index("ix_inventory_edges_project_id_kind", table_name="inventory_edges")
    op.drop_index("ix_inventory_edges_from_item", table_name="inventory_edges")
    op.drop_table("inventory_edges")
    op.drop_index("ix_shadow_mismatches_module_id_created_at", table_name="shadow_mismatches")
    op.drop_table("shadow_mismatches")
    op.drop_index("ix_inventory_items_project_id_kind", table_name="inventory_items")
    op.drop_table("inventory_items")
    op.drop_table("code_artifacts")
    op.drop_index("ix_ai_calls_job_id", table_name="ai_calls")
    op.drop_table("ai_calls")
    op.drop_index("ix_source_files_project_id_kind", table_name="source_files")
    op.drop_table("source_files")
    op.drop_index("ix_rules_project_id_program_state", table_name="rules")
    op.drop_index("ix_rules_project_id_kind", table_name="rules")
    op.drop_table("rules")
    op.drop_table("plans")
    op.drop_table("modules")
    op.drop_index("ix_jobs_status_created_at", table_name="jobs")
    op.drop_index("ix_jobs_project_id_kind", table_name="jobs")
    op.drop_index("ix_jobs_project_id_input_hash", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index(
        "uq_projects_bundled_name", table_name="projects", postgresql_where=sa.text("source_kind = 'BUNDLED'")
    )
    op.drop_table("projects")
    op.drop_index("ix_audit_logs_occurred_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_entity", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_approvals_entity", table_name="approvals")
    op.drop_table("approvals")
    op.drop_table("users")
    op.execute("DROP FUNCTION audit_logs_reject_change()")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
