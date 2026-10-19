"""First-touch acquisition source: ``funnel_attribution`` (Wave E M-4, MR1)

One row per user: partner source (scribase or rally), UTM source, medium and
campaign, and referrer, written once (first touch wins). Purely additive and
idempotent: the table and index are created only when missing.

Revision ID: d8e1f3a5c7b9
Revises: c4e6a8b0d2f3
Create Date: 2026-09-29 10:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd8e1f3a5c7b9'
down_revision: Union[str, None] = 'c4e6a8b0d2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "funnel_attribution"
_INDEX = "ix_funnel_attribution_source"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column("user_id", sa.String(length=32), nullable=False),
            sa.Column("source", sa.String(length=40), nullable=False, server_default=""),
            sa.Column("utm_source", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("utm_medium", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("utm_campaign", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("referrer", sa.String(length=300), nullable=False, server_default=""),
            sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("user_id"),
        )
    indexes = {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes(_TABLE)}
    if _INDEX not in indexes:
        op.create_index(_INDEX, _TABLE, ["source"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(_TABLE):
        indexes = {ix["name"] for ix in inspector.get_indexes(_TABLE)}
        if _INDEX in indexes:
            op.drop_index(_INDEX, table_name=_TABLE)
        op.drop_table(_TABLE)
