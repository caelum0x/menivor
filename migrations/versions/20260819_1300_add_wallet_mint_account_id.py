"""add wallet_accounts.mint_account_id (Mint-settlement rail)

Additive, backward-compatible: a nullable ``mint_account_id`` on
``wallet_accounts`` caching the payer's mint-server ``acct_...`` id, provisioned
lazily on the owner's first Mint hold. No backfill (existing rows read NULL and
keep using the local microdollar ledger). Safe on SQLite and Postgres/Neon.

Revision ID: e1f2a3b4c5d6
Revises: c9a10canonlock
Create Date: 2026-08-19 13:00:00.000000+00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "c9a10canonlock"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "wallet_accounts",
        sa.Column("mint_account_id", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("wallet_accounts", "mint_account_id")
