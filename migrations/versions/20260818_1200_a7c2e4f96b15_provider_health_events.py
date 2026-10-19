"""provider health events (health/uptime-weighted routing + status)

Append-only ``provider_health_events``: one row per provider run (ok + latency),
aggregated into uptime %/latency band for routing and a status view.

Revision ID: a7c2e4f96b15
Revises: f6b9c3d75e84
Create Date: 2026-08-18 12:00:00.000000+00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c2e4f96b15"
down_revision: Union[str, None] = "f6b9c3d75e84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "provider_health_events",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("provider_key", sa.String(length=64), nullable=False),
        sa.Column("capability", sa.String(length=40), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column(
            "latency_ms", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_provider_health_events_provider_key"),
        "provider_health_events",
        ["provider_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_provider_health_events_created_at"),
        "provider_health_events",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_provider_health_provider_created",
        "provider_health_events",
        ["provider_key", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_provider_health_provider_created", table_name="provider_health_events"
    )
    op.drop_index(
        op.f("ix_provider_health_events_created_at"),
        table_name="provider_health_events",
    )
    op.drop_index(
        op.f("ix_provider_health_events_provider_key"),
        table_name="provider_health_events",
    )
    op.drop_table("provider_health_events")
