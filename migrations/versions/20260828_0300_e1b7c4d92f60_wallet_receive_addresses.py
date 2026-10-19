"""stable public receive address for wallet sources

Revision ID: e1b7c4d92f60
Revises: d7a4b91ce820
Create Date: 2026-08-28 03:00:00
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "e1b7c4d92f60"
down_revision: Union[str, None] = "d7a4b91ce820"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    op.add_column(
        "wallet_accounts",
        sa.Column("mint_receive_address", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "uq_wallet_accounts_mint_receive_address",
        "wallet_accounts",
        ["mint_receive_address"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_wallet_accounts_mint_receive_address", table_name="wallet_accounts"
    )
    op.drop_column("wallet_accounts", "mint_receive_address")
