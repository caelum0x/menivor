"""Personal monthly plans: ``creator_subscriptions`` (web creators, Creem)

One row per user: plan (creator | pro | agency), interval, Creem subscription +
customer ids, status, cancel-at-period-end, and the current period's granted
included reels (so unused ones expire once when the next period starts).
Purely additive; nothing else changes.

Revision ID: d4e8a1c7b2f6
Revises: c1f6a2b4d8e0
Create Date: 2026-09-25 18:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd4e8a1c7b2f6'
down_revision: Union[str, None] = 'c1f6a2b4d8e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "creator_subscriptions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("plan_key", sa.String(length=40), nullable=False),
        sa.Column("interval", sa.String(length=10), server_default=sa.text("'month'"), nullable=False),
        sa.Column("provider", sa.String(length=40), server_default=sa.text("'creem'"), nullable=False),
        sa.Column("provider_ref", sa.String(length=255), server_default=sa.text("''"), nullable=False),
        sa.Column("customer_ref", sa.String(length=255), server_default=sa.text("''"), nullable=False),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
        sa.Column("cancel_at_period_end", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_key", sa.String(length=40), server_default=sa.text("''"), nullable=False),
        sa.Column("period_credits", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("period_grant_ledger_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_creator_subscriptions_user"),
    )
    op.create_index(
        "ix_creator_subscriptions_user_id", "creator_subscriptions", ["user_id"], unique=False
    )
    op.create_index(
        "ix_creator_subscriptions_provider_ref",
        "creator_subscriptions",
        ["provider_ref"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_creator_subscriptions_provider_ref", table_name="creator_subscriptions")
    op.drop_index("ix_creator_subscriptions_user_id", table_name="creator_subscriptions")
    op.drop_table("creator_subscriptions")
