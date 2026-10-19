"""Content reports and takedown: ``takedown_reports`` (MN5)

One row per public report (a ticket). Rows are never deleted; ``status`` records
open, blocked (media soft-blocked), dismissed or restored. Purely additive.

Revision ID: c4e6a8b0d2f3
Revises: b7d2e4f6a8c1
Create Date: 2026-09-28 22:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c4e6a8b0d2f3'
down_revision: Union[str, None] = 'b7d2e4f6a8c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "takedown_reports",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=True),
        sa.Column("content_ref", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("details", sa.Text(), nullable=False, server_default=""),
        sa.Column("reporter_email", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("resolved_by", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_takedown_reports_job_id", "takedown_reports", ["job_id"])
    op.create_index("ix_takedown_reports_status_created", "takedown_reports", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_takedown_reports_status_created", table_name="takedown_reports")
    op.drop_index("ix_takedown_reports_job_id", table_name="takedown_reports")
    op.drop_table("takedown_reports")
