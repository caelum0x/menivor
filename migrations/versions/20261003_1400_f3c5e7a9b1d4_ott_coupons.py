"""OTT coupon code references (Wave Q QM1.3).

A coupon row names a discount that lives on the creator's own processor.
No amount, percent, balance or payout column is added. Additive and idempotent.

Revision ID: f3c5e7a9b1d4
Revises: e2b4d6f8a0c3
Create Date: 2026-10-03 14:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f3c5e7a9b1d4'
down_revision: Union[str, None] = 'e2b4d6f8a0c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "ott_coupons" not in tables:
        op.create_table(
            "ott_coupons",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("channel_id", sa.String(32), nullable=False),
            sa.Column("code", sa.String(16), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("channel_id", "code", name="uq_ott_coupons_channel_code"),
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "ott_coupons" in tables:
        op.drop_table("ott_coupons")
