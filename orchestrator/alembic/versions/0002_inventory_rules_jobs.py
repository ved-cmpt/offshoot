"""Inventory edge details, rule provenance and job payloads for Run 02.

No new tables, so the table-level grants from 0001 still cover everything (ADR-014).

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMPTY_OBJECT = sa.text("'{}'::jsonb")
EMPTY_ARRAY = sa.text("'[]'::jsonb")


def upgrade() -> None:
    op.drop_constraint(op.f("ck_inventory_items_kind"), "inventory_items", type_="check")
    op.create_check_constraint(
        op.f("ck_inventory_items_kind"),
        "inventory_items",
        "kind IN ('PROGRAM', 'COPYBOOK', 'PARAGRAPH', 'SECTION', 'FILE', 'RECORD', 'FIELD')",
    )
    op.add_column(
        "inventory_edges",
        sa.Column("attrs", postgresql.JSONB(astext_type=sa.Text()), server_default=EMPTY_OBJECT, nullable=False),
    )

    op.add_column(
        "jobs",
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default=EMPTY_OBJECT, nullable=False),
    )
    op.add_column("jobs", sa.Column("requested_by", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_jobs_requested_by_users"), "jobs", "users", ["requested_by"], ["id"], ondelete="SET NULL"
    )
    op.create_index(
        "uq_jobs_active_input",
        "jobs",
        ["project_id", "kind", "input_hash"],
        unique=True,
        postgresql_where=sa.text("status IN ('QUEUED', 'RUNNING')"),
    )

    op.add_column(
        "rules",
        sa.Column("flag_details", postgresql.JSONB(astext_type=sa.Text()), server_default=EMPTY_ARRAY, nullable=False),
    )
    op.add_column("rules", sa.Column("fingerprint", sa.String(length=64), nullable=False))
    op.add_column("rules", sa.Column("job_id", sa.UUID(), nullable=True))
    op.add_column("rules", sa.Column("prompt_version", sa.String(length=32), nullable=False))
    op.add_column("rules", sa.Column("model_id", sa.String(length=120), nullable=True))
    op.add_column(
        "rules",
        sa.Column("model_output", postgresql.JSONB(astext_type=sa.Text()), server_default=EMPTY_OBJECT, nullable=False),
    )
    op.add_column("rules", sa.Column("edited_by", sa.UUID(), nullable=True))
    op.add_column("rules", sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(op.f("fk_rules_job_id_jobs"), "rules", "jobs", ["job_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(
        op.f("fk_rules_edited_by_users"), "rules", "users", ["edited_by"], ["id"], ondelete="SET NULL"
    )
    op.create_unique_constraint(
        "uq_rules_project_id_program_fingerprint", "rules", ["project_id", "program", "fingerprint"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_rules_project_id_program_fingerprint", "rules", type_="unique")
    op.drop_constraint(op.f("fk_rules_edited_by_users"), "rules", type_="foreignkey")
    op.drop_constraint(op.f("fk_rules_job_id_jobs"), "rules", type_="foreignkey")
    for column in (
        "edited_at",
        "edited_by",
        "model_output",
        "model_id",
        "prompt_version",
        "job_id",
        "fingerprint",
        "flag_details",
    ):
        op.drop_column("rules", column)

    op.drop_index(
        "uq_jobs_active_input", table_name="jobs", postgresql_where=sa.text("status IN ('QUEUED', 'RUNNING')")
    )
    op.drop_constraint(op.f("fk_jobs_requested_by_users"), "jobs", type_="foreignkey")
    op.drop_column("jobs", "requested_by")
    op.drop_column("jobs", "payload")

    op.drop_column("inventory_edges", "attrs")
    op.execute("DELETE FROM inventory_items WHERE kind = 'COPYBOOK'")
    op.drop_constraint(op.f("ck_inventory_items_kind"), "inventory_items", type_="check")
    op.create_check_constraint(
        op.f("ck_inventory_items_kind"),
        "inventory_items",
        "kind IN ('PROGRAM', 'PARAGRAPH', 'SECTION', 'FILE', 'RECORD', 'FIELD')",
    )
