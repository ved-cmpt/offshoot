"""Stored demo snapshots for the daily reset of a deployment without a sandbox (Run 05).

Revision ID: 0005
Revises: 0004
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = os.environ.get("APP_DB_ROLE", "offshoot_app")
if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", APP_ROLE):
    raise ValueError("APP_DB_ROLE must be a lower-case SQL identifier")

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "demo_snapshots",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_name", sa.String(length=120), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("row_counts", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_demo_snapshots")),
    )
    # Grants name existing tables, so each new table is granted here (ADR-014).
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON demo_snapshots TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("demo_snapshots")
