"""wallet transfers: leased automatic reconciliation

Revision ID: a7d3e91bc462
Revises: c5e9b7d24f81
Create Date: 2026-08-27 25:00:00+00:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7d3e91bc462"
down_revision: Union[str, None] = "c5e9b7d24f81"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "wallet_transfers",
        sa.Column("reconcile_lease_owner", sa.String(length=96), nullable=True),
    )
    op.add_column(
        "wallet_transfers",
        sa.Column(
            "reconcile_lease_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "wallet_transfers",
        sa.Column("reconcile_after", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "wallet_transfers",
        sa.Column(
            "reconcile_attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "wallet_transfers",
        sa.Column(
            "reconcile_last_attempt_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "wallet_transfers",
        sa.Column("reconcile_last_error", sa.String(length=500), nullable=True),
    )
    op.create_index(
        "ix_wallet_transfers_reconcile_ready",
        "wallet_transfers",
        [
            "status",
            "reconcile_after",
            "reconcile_lease_expires_at",
            "created_at",
        ],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_wallet_transfers_reconcile_ready", table_name="wallet_transfers"
    )
    op.drop_column("wallet_transfers", "reconcile_last_error")
    op.drop_column("wallet_transfers", "reconcile_last_attempt_at")
    op.drop_column("wallet_transfers", "reconcile_attempts")
    op.drop_column("wallet_transfers", "reconcile_after")
    op.drop_column("wallet_transfers", "reconcile_lease_expires_at")
    op.drop_column("wallet_transfers", "reconcile_lease_owner")
