"""Dodo Payments usage-event outbox: ``dodo_usage_events``

One row per metered reel render (``event_id = reel_<job_id>``) for users on a
usage-based Dodo monthly plan. Flushed to Dodo ``POST /events/ingest`` by the
worker and a Celery beat sweep. Purely additive.

Revision ID: f6a1c4e8b3d9
Revises: d4e8a1c7b2f6
Create Date: 2026-09-27 02:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f6a1c4e8b3d9'
down_revision: Union[str, None] = 'd4e8a1c7b2f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dodo_usage_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=120), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("customer_id", sa.String(length=255), nullable=False),
        sa.Column("event_name", sa.String(length=80), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=300), server_default=sa.text("''"), nullable=False),
        sa.Column("overage", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_dodo_usage_events_event_id"),
    )
    op.create_index("ix_dodo_usage_events_user_id", "dodo_usage_events", ["user_id"], unique=False)
    op.create_index("ix_dodo_usage_events_status", "dodo_usage_events", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_dodo_usage_events_status", table_name="dodo_usage_events")
    op.drop_index("ix_dodo_usage_events_user_id", table_name="dodo_usage_events")
    op.drop_table("dodo_usage_events")
