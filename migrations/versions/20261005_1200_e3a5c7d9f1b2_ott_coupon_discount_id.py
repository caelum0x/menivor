"""Keep the processor's discount id on each OTT coupon (Wave Q QM gaps).

Stopping a coupon now ends the discount on the creator's processor, and
switching it back on reuses the same discount (Dodo refuses a second discount
with the same code). Both need the processor's discount id. Rows made before
this stay NULL: stopping them is local only and re-enabling makes a new
discount. Additive and idempotent.

Revision ID: e3a5c7d9f1b2
Revises: d2f4a6c8e0b5
Create Date: 2026-10-05 12:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e3a5c7d9f1b2'
down_revision: Union[str, None] = 'd2f4a6c8e0b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "ott_coupons"
_COLUMN = "processor_discount_id"


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    have = _columns()
    if have and _COLUMN not in have:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(64), nullable=True))


def downgrade() -> None:
    if _COLUMN in _columns():
        op.drop_column(_TABLE, _COLUMN)
