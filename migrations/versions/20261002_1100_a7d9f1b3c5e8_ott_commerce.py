"""OTT commerce and ads: ``ott_offers``, ``ott_entitlements``, ``ott_mint_events``, ``ott_ads``, ``ott_ad_settings`` (Wave P PM3.2, MV13/MV14)

Additive and idempotent. No amount, balance, payout or payment detail is
stored: the creator's own processor takes the money (Mint seller-own).

Revision ID: a7d9f1b3c5e8
Revises: f6c8e0a2b4d7
Create Date: 2026-10-02 11:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a7d9f1b3c5e8'
down_revision: Union[str, None] = 'f6c8e0a2b4d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "ott_offers" not in tables:
        op.create_table(
            "ott_offers",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("channel_id", sa.String(32), nullable=False),
            sa.Column("kind", sa.String(8), nullable=False),
            sa.Column("title_id", sa.String(32), nullable=True),
            sa.Column("sku", sa.String(64), nullable=False),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("price_cents", sa.Integer(), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
            sa.Column("interval", sa.String(8), nullable=False, server_default=""),
            sa.Column("rental_hours", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("channel_id", "sku", name="uq_ott_offers_channel_sku"),
        )
    if "ott_entitlements" not in tables:
        op.create_table(
            "ott_entitlements",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("channel_id", sa.String(32), nullable=False),
            sa.Column("viewer_id", sa.String(32), nullable=False),
            sa.Column("offer_id", sa.String(32), nullable=False),
            sa.Column("kind", sa.String(8), nullable=False),
            sa.Column("title_id", sa.String(32), nullable=True),
            sa.Column("status", sa.String(10), nullable=False, server_default="active"),
            sa.Column("granted_event_id", sa.String(64), nullable=False),
            sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_reason", sa.String(16), nullable=False, server_default=""),
            sa.UniqueConstraint("granted_event_id", name="uq_ott_entitlements_granted_event"),
        )
        op.create_index("ix_ott_entitlements_viewer", "ott_entitlements", ["viewer_id", "status"])
    if "ott_mint_events" not in tables:
        op.create_table(
            "ott_mint_events",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("kind", sa.String(10), nullable=False),
            sa.Column("outcome", sa.String(24), nullable=False),
            sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    if "ott_ads" not in tables:
        op.create_table(
            "ott_ads",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("channel_id", sa.String(32), nullable=True),
            sa.Column("kind", sa.String(8), nullable=False),
            sa.Column("name", sa.String(80), nullable=False),
            sa.Column("sponsor", sa.String(80), nullable=False, server_default=""),
            sa.Column("title_id", sa.String(32), nullable=False),
            sa.Column("click_url", sa.String(500), nullable=False, server_default=""),
            sa.Column("duration_s", sa.Float(), nullable=False, server_default="15"),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("completes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skips", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    if "ott_ad_settings" not in tables:
        op.create_table(
            "ott_ad_settings",
            sa.Column("channel_id", sa.String(32), primary_key=True),
            sa.Column("ads_on_free", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("ads_on_paid", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("house_ads", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )


def downgrade() -> None:
    tables = _tables()
    for table in ("ott_ad_settings", "ott_ads", "ott_mint_events", "ott_entitlements", "ott_offers"):
        if table in tables:
            op.drop_table(table)
