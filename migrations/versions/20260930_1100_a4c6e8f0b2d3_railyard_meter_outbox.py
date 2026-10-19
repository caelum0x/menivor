"""Railyard in production for Menivor: ``railyard_meter_outbox``, ``railyard_grant_redemptions`` (Wave P PM1.5)

The outbox holds Rago usage events and Mint ledger-mirror entries in the
contract shape until they are sent (``RAILYARD_LIVE=1``); the transaction id
is unique, so a repeated event is a no-op. Grant redemptions record the
Scribase add-on's monthly launch reel per org, month and user. Purely
additive and idempotent.

Revision ID: a4c6e8f0b2d3
Revises: f3b5d7e9a1c2
Create Date: 2026-09-30 11:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a4c6e8f0b2d3'
down_revision: Union[str, None] = 'f3b5d7e9a1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    tables = _tables()
    if "railyard_meter_outbox" not in tables:
        op.create_table(
            "railyard_meter_outbox",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("channel", sa.String(length=16), nullable=False, server_default="rago"),
            sa.Column("transaction_id", sa.String(length=200), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("transaction_id", name="uq_railyard_meter_outbox_txn"),
        )
    if "ix_railyard_meter_outbox_pending" not in _indexes("railyard_meter_outbox"):
        op.create_index("ix_railyard_meter_outbox_pending", "railyard_meter_outbox", ["channel", "sent_at", "id"])
    if "railyard_grant_redemptions" not in tables:
        op.create_table(
            "railyard_grant_redemptions",
            sa.Column("id", sa.String(length=32), nullable=False),
            sa.Column("org_id", sa.String(length=80), nullable=False),
            sa.Column("period", sa.String(length=7), nullable=False),
            sa.Column("n", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.String(length=32), nullable=False),
            sa.Column("grant", sa.String(length=40), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("org_id", "period", "n", name="uq_grant_redemptions_slot"),
            sa.UniqueConstraint("org_id", "period", "user_id", name="uq_grant_redemptions_user"),
        )


def downgrade() -> None:
    tables = _tables()
    if "railyard_grant_redemptions" in tables:
        op.drop_table("railyard_grant_redemptions")
    if "railyard_meter_outbox" in tables:
        op.drop_table("railyard_meter_outbox")
