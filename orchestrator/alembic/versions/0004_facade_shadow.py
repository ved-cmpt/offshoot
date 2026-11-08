"""Shadow comparison counters on modules and the SHADOW job kind (Run 04).

No new tables, so the grants from earlier migrations still cover everything (ADR-014).

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = "'ANALYZE', 'EXTRACT', 'PLAN', 'MIGRATE', 'BUILD', 'VERIFY', 'REPAIR', 'MUTATE'"
NEW_KINDS = OLD_KINDS + ", 'SHADOW'"


def upgrade() -> None:
    op.add_column("modules", sa.Column("shadow_since", sa.DateTime(timezone=True), nullable=True))
    op.add_column("modules", sa.Column("shadow_compared", sa.Integer(), server_default=sa.text("0"), nullable=False))
    op.drop_constraint(op.f("ck_jobs_kind"), "jobs", type_="check")
    op.create_check_constraint(op.f("ck_jobs_kind"), "jobs", f'"kind" IN ({NEW_KINDS})')


def downgrade() -> None:
    op.drop_constraint(op.f("ck_jobs_kind"), "jobs", type_="check")
    op.create_check_constraint(op.f("ck_jobs_kind"), "jobs", f'"kind" IN ({OLD_KINDS})')
    op.drop_column("modules", "shadow_compared")
    op.drop_column("modules", "shadow_since")
