"""spend controls: per-user/workspace budget cap + BYOK consent

Creates ``spend_policies`` (PROVIDER_MARKETPLACE_PLAN.md §1.3/§8.4): a monthly
budget cap enforced at reserve time and an explicit BYOK-consent flag.

Revision ID: e5a8b2c64d73
Revises: d4f7a1b53c62
Create Date: 2026-08-17 14:00:00.000000+00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5a8b2c64d73"
down_revision: Union[str, None] = "d4f7a1b53c62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _micros() -> sa.types.TypeEngine:
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "spend_policies",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=True),
        sa.Column("workspace_id", sa.String(length=32), nullable=True),
        sa.Column(
            "monthly_budget_micros",
            _micros(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "byok_allowed", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_spend_policies_user"),
        sa.UniqueConstraint("workspace_id", name="uq_spend_policies_workspace"),
    )
    op.create_index(
        op.f("ix_spend_policies_user_id"), "spend_policies", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_spend_policies_workspace_id"),
        "spend_policies",
        ["workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_spend_policies_workspace_id"), table_name="spend_policies")
    op.drop_index(op.f("ix_spend_policies_user_id"), table_name="spend_policies")
    op.drop_table("spend_policies")
