"""Snapshot the offer list price on each OTT grant (Wave Q QM verify).

Gross sales per title used the offer's current price, so a price change rewrote
past sales. Each grant now records the list price and currency it landed at.
These are labels for the creator's dashboard, not funds: buyers pay the
creator's own processor. Additive and idempotent.

Revision ID: b5e7a9c1d3f7
Revises: a4d6f8b0c2e6
Create Date: 2026-10-05 09:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b5e7a9c1d3f7'
down_revision: Union[str, None] = 'a4d6f8b0c2e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "ott_entitlements"


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    have = _columns()
    if "list_price_cents" not in have:
        op.add_column(_TABLE, sa.Column("list_price_cents", sa.Integer(), nullable=True))
    if "list_currency" not in have:
        op.add_column(_TABLE, sa.Column("list_currency", sa.String(3), nullable=True))


def downgrade() -> None:
    have = _columns()
    if "list_currency" in have:
        op.drop_column(_TABLE, "list_currency")
    if "list_price_cents" in have:
        op.drop_column(_TABLE, "list_price_cents")
