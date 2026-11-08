"""Plans, module lifecycle, code artifacts, verification runs and gate exceptions (Run 03).

One new table, `gate_exceptions`, which the app role may read and insert but never change:
an exception is a recorded decision (ADR-014 requires each new table to be granted here).

Revision ID: 0003
Revises: 0002
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = os.environ.get("APP_DB_ROLE", "offshoot_app")
if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", APP_ROLE):
    raise ValueError("APP_DB_ROLE must be a lower-case SQL identifier")

EMPTY_OBJECT = sa.text("'{}'::jsonb")
EMPTY_ARRAY = sa.text("'[]'::jsonb")
JSONB = postgresql.JSONB(astext_type=sa.Text())
BUILD_STATUSES = "'PENDING', 'BUILT', 'BUILD_FAILED', 'POLICY_FAILED', 'TESTS_FAILED', 'TIMED_OUT', 'MEMORY_LIMIT'"


def upgrade() -> None:
    op.create_table(
        "gate_exceptions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("module_id", sa.UUID(), nullable=False),
        sa.Column("gate", sa.String(length=16), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("\"gate\" IN ('COVERAGE', 'MUTATION')", name=op.f("ck_gate_exceptions_gate")),
        sa.CheckConstraint("length(trim(reason)) > 0", name=op.f("ck_gate_exceptions_reason_required")),
        sa.CheckConstraint("threshold >= 0 AND threshold <= 100", name=op.f("ck_gate_exceptions_threshold_range")),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_gate_exceptions_actor_id_users"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["module_id"], ["modules.id"], name=op.f("fk_gate_exceptions_module_id_modules"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gate_exceptions")),
    )
    op.create_index(
        "ix_gate_exceptions_module_id_created_at",
        "gate_exceptions",
        ["module_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.execute(f"REVOKE ALL ON gate_exceptions FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON gate_exceptions TO {APP_ROLE}")

    op.add_column(
        "code_artifacts", sa.Column("kind", sa.String(16), server_default=sa.text("'MIGRATION'"), nullable=False)
    )
    op.add_column("code_artifacts", sa.Column("attempt", sa.Integer(), server_default=sa.text("1"), nullable=False))
    op.add_column("code_artifacts", sa.Column("parent_id", sa.UUID(), nullable=True))
    op.add_column(
        "code_artifacts", sa.Column("build_status", sa.String(16), server_default=sa.text("'PENDING'"), nullable=False)
    )
    op.add_column("code_artifacts", sa.Column("build_report", JSONB, server_default=EMPTY_OBJECT, nullable=False))
    op.add_column("code_artifacts", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column("code_artifacts", sa.Column("rule_ids", JSONB, server_default=EMPTY_ARRAY, nullable=False))
    op.add_column("code_artifacts", sa.Column("prompt_version", sa.String(32), nullable=True))
    op.add_column("code_artifacts", sa.Column("model_id", sa.String(120), nullable=True))
    op.create_foreign_key(
        op.f("fk_code_artifacts_parent_id_code_artifacts"),
        "code_artifacts",
        "code_artifacts",
        ["parent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(op.f("ck_code_artifacts_kind"), "code_artifacts", "\"kind\" IN ('MIGRATION', 'REPAIR')")
    op.create_check_constraint(
        op.f("ck_code_artifacts_build_status"), "code_artifacts", f'"build_status" IN ({BUILD_STATUSES})'
    )

    op.add_column("modules", sa.Column("plan_id", sa.UUID(), nullable=True))
    op.add_column("modules", sa.Column("order_index", sa.Integer(), server_default=sa.text("0"), nullable=False))
    op.add_column("modules", sa.Column("state_reason", sa.String(64), nullable=True))
    op.add_column(
        "modules",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_foreign_key(
        op.f("fk_modules_plan_id_plans"), "modules", "plans", ["plan_id"], ["id"], ondelete="SET NULL"
    )

    op.add_column("plans", sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("plans", sa.Column("job_id", sa.UUID(), nullable=True))
    op.add_column("plans", sa.Column("prompt_version", sa.String(32), nullable=True))
    op.add_column("plans", sa.Column("model_id", sa.String(120), nullable=True))
    op.add_column("plans", sa.Column("model_output", JSONB, server_default=EMPTY_OBJECT, nullable=False))
    op.add_column("plans", sa.Column("signals", JSONB, server_default=EMPTY_OBJECT, nullable=False))
    op.create_foreign_key(op.f("fk_plans_job_id_jobs"), "plans", "jobs", ["job_id"], ["id"], ondelete="SET NULL")

    op.add_column("verification_runs", sa.Column("job_id", sa.UUID(), nullable=True))
    op.add_column(
        "verification_runs", sa.Column("kind", sa.String(16), server_default=sa.text("'FULL'"), nullable=False)
    )
    op.add_column(
        "verification_runs", sa.Column("status", sa.String(16), server_default=sa.text("'FAILED'"), nullable=False)
    )
    op.add_column("verification_runs", sa.Column("gates", JSONB, server_default=EMPTY_ARRAY, nullable=False))
    op.add_column("verification_runs", sa.Column("base_run_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_verification_runs_base_run_id_verification_runs"),
        "verification_runs",
        "verification_runs",
        ["base_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_verification_runs_job_id_jobs"), "verification_runs", "jobs", ["job_id"], ["id"], ondelete="SET NULL"
    )
    op.create_check_constraint(
        op.f("ck_verification_runs_kind"), "verification_runs", "\"kind\" IN ('FULL', 'MUTATION')"
    )
    op.create_check_constraint(
        op.f("ck_verification_runs_status"), "verification_runs", "\"status\" IN ('PASSED', 'FAILED')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_verification_runs_status"), "verification_runs", type_="check")
    op.drop_constraint(op.f("ck_verification_runs_kind"), "verification_runs", type_="check")
    op.drop_constraint(op.f("fk_verification_runs_job_id_jobs"), "verification_runs", type_="foreignkey")
    op.drop_constraint(
        op.f("fk_verification_runs_base_run_id_verification_runs"), "verification_runs", type_="foreignkey"
    )
    for column in ("base_run_id", "gates", "status", "kind", "job_id"):
        op.drop_column("verification_runs", column)
    op.drop_constraint(op.f("fk_plans_job_id_jobs"), "plans", type_="foreignkey")
    for column in ("signals", "model_output", "model_id", "prompt_version", "job_id", "decided_at"):
        op.drop_column("plans", column)
    op.drop_constraint(op.f("fk_modules_plan_id_plans"), "modules", type_="foreignkey")
    for column in ("updated_at", "state_reason", "order_index", "plan_id"):
        op.drop_column("modules", column)
    op.drop_constraint(op.f("ck_code_artifacts_build_status"), "code_artifacts", type_="check")
    op.drop_constraint(op.f("ck_code_artifacts_kind"), "code_artifacts", type_="check")
    op.drop_constraint(op.f("fk_code_artifacts_parent_id_code_artifacts"), "code_artifacts", type_="foreignkey")
    for column in (
        "model_id",
        "prompt_version",
        "rule_ids",
        "notes",
        "build_report",
        "build_status",
        "parent_id",
        "attempt",
        "kind",
    ):
        op.drop_column("code_artifacts", column)
    op.drop_index("ix_gate_exceptions_module_id_created_at", table_name="gate_exceptions")
    op.drop_table("gate_exceptions")
