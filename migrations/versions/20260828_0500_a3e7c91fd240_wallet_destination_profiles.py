"""public workspace, agent, and service wallet destinations

Revision ID: a3e7c91fd240
Revises: f2c8d5e03a71
Create Date: 2026-08-28 05:00:00
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "a3e7c91fd240"
down_revision: Union[str, None] = "f2c8d5e03a71"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    op.create_table(
        "wallet_destination_profiles",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("handle", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("owner_user_id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=True),
        sa.Column(
            "active", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('workspace', 'agent', 'service')",
            name="ck_wallet_destination_profiles_kind",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["wallet_accounts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id"),
    )
    # ``handle`` MUST be globally unique (a typed destination like
    # ``agent:caption-bot`` must route to exactly one profile). The ORM model
    # declares that via ``mapped_column(unique=True, index=True)`` — a single
    # UNIQUE INDEX. The inline ``UniqueConstraint("handle")`` above was redundant
    # with this index (double-declaring uniqueness) and surfaced as drift
    # (``wallet_destination_profiles_handle_key`` present in DB, absent in the
    # model). Uniqueness is preserved by this unique index alone.
    op.create_index(
        "ix_wallet_destination_profiles_handle",
        "wallet_destination_profiles",
        ["handle"],
        unique=True,
    )
    op.create_index(
        "ix_wallet_destination_profiles_owner_user_id",
        "wallet_destination_profiles",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_wallet_destination_profiles_workspace_id",
        "wallet_destination_profiles",
        ["workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_wallet_destination_profiles_workspace_id",
        table_name="wallet_destination_profiles",
    )
    op.drop_index(
        "ix_wallet_destination_profiles_owner_user_id",
        table_name="wallet_destination_profiles",
    )
    op.drop_index(
        "ix_wallet_destination_profiles_handle",
        table_name="wallet_destination_profiles",
    )
    op.drop_table("wallet_destination_profiles")
