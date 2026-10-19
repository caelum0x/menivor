"""wallet transfers: durable Mint operation and portable proof

Revision ID: f4d9a6c13b72
Revises: e3c8a015bd72
Create Date: 2026-08-27 23:00:00+00:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4d9a6c13b72"
down_revision: Union[str, None] = "e3c8a015bd72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "wallet_transfers",
        sa.Column(
            "mint_operation",
            sa.String(length=96),
            server_default=sa.text("''"),
            nullable=False,
        ),
    )
    op.add_column(
        "wallet_transfers", sa.Column("mint_receipt", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("wallet_transfers", "mint_receipt")
    op.drop_column("wallet_transfers", "mint_operation")
