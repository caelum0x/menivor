"""wallet transfers: durable Mint person-to-person orchestration

Revision ID: a1f4c7e20d83
Revises: f8c9d0e1a2b3
Create Date: 2026-08-27 14:00:00+00:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1f4c7e20d83"
down_revision: Union[str, None] = "f8c9d0e1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wallet_transfers",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("sender_account_id", sa.String(length=32), nullable=False),
        sa.Column("recipient_account_id", sa.String(length=32), nullable=False),
        sa.Column("sender_user_id", sa.String(length=32), nullable=False),
        sa.Column("recipient_user_id", sa.String(length=32), nullable=False),
        sa.Column("sender_handle", sa.String(length=64), nullable=False),
        sa.Column("recipient_handle", sa.String(length=64), nullable=False),
        sa.Column("amount_micros", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("mint_first_seq", sa.BigInteger(), nullable=True),
        sa.Column(
            "mint_idempotent_replay",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["recipient_account_id"], ["wallet_accounts.id"]),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["sender_account_id"], ["wallet_accounts.id"]),
        sa.ForeignKeyConstraint(["sender_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sender_account_id",
            "idempotency_key",
            name="uq_wallet_transfers_sender_idempotency",
        ),
    )
    for column in (
        "created_at",
        "recipient_account_id",
        "recipient_user_id",
        "sender_account_id",
        "sender_user_id",
    ):
        op.create_index(
            op.f(f"ix_wallet_transfers_{column}"),
            "wallet_transfers",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in (
        "sender_user_id",
        "sender_account_id",
        "recipient_user_id",
        "recipient_account_id",
        "created_at",
    ):
        op.drop_index(
            op.f(f"ix_wallet_transfers_{column}"), table_name="wallet_transfers"
        )
    op.drop_table("wallet_transfers")
