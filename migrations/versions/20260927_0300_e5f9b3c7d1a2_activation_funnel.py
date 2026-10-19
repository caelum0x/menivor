"""Activation funnel: ``funnel_events`` + ``funnel_reports``

``funnel_events`` holds ONE row per (user, step): the first time that user
reached the step (signup, card check, first link pasted, first reel rendered,
pack/plan bought). Written server-side only (app/services/funnel). The weekly
owner funnel email is recorded once per ISO week in ``funnel_reports`` so a
retried beat tick never sends the same week twice. Purely additive.

Revision ID: e5f9b3c7d1a2
Revises: f6a1c4e8b3d9
Create Date: 2026-09-27 03:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e5f9b3c7d1a2'
down_revision: Union[str, None] = 'f6a1c4e8b3d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "funnel_events",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("step", sa.String(length=40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "step"),
    )
    op.create_index(
        "ix_funnel_events_step_occurred_at", "funnel_events", ["step", "occurred_at"], unique=False
    )
    op.create_table(
        "funnel_reports",
        sa.Column("week_start", sa.String(length=10), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("week_start"),
    )


def downgrade() -> None:
    op.drop_table("funnel_reports")
    op.drop_index("ix_funnel_events_step_occurred_at", table_name="funnel_events")
    op.drop_table("funnel_events")
