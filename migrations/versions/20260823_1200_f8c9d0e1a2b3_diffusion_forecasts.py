"""diffusion_forecasts: durable trend-bound forecast identity

Revision ID: f8c9d0e1a2b3
Revises: e1f2a3b4c5d6
Create Date: 2026-08-23 12:00:00+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8c9d0e1a2b3"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "diffusion_forecasts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("trend_observation_id", sa.String(length=32), nullable=False),
        sa.Column(
            "content_type",
            sa.String(length=40),
            server_default=sa.text("'short_video'"),
            nullable=False,
        ),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("assumptions", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["trend_observation_id"], ["trend_observations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_diffusion_forecasts_created_at"),
        "diffusion_forecasts",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_diffusion_forecasts_trend_observation_id"),
        "diffusion_forecasts",
        ["trend_observation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_diffusion_forecasts_user_id"),
        "diffusion_forecasts",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_diffusion_forecasts_user_id"), table_name="diffusion_forecasts")
    op.drop_index(
        op.f("ix_diffusion_forecasts_trend_observation_id"),
        table_name="diffusion_forecasts",
    )
    op.drop_index(op.f("ix_diffusion_forecasts_created_at"), table_name="diffusion_forecasts")
    op.drop_table("diffusion_forecasts")
