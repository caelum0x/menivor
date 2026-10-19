"""OTT ad-event dedupe and team invites (Wave Q QM1.0: P-M12, P-M15)

``ott_ad_events``: one row per counted (play, ad, event), unique, so a
replayed tracking URL never counts twice. ``ott_channel_invites``: team seats
by email, stored whether or not the email has an account. Additive and
idempotent.

Revision ID: d1a3c5e7f9b2
Revises: c9f1b3d5e7a0
Create Date: 2026-10-03 09:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd1a3c5e7f9b2'
down_revision: Union[str, None] = 'c9f1b3d5e7a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "ott_ad_events" not in tables:
        op.create_table(
            "ott_ad_events",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("ad_id", sa.String(32), nullable=False),
            sa.Column("play_id", sa.String(32), nullable=False),
            sa.Column("event", sa.String(16), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("play_id", "ad_id", "event", name="uq_ott_ad_events_play_ad_event"),
        )
        op.create_index("ix_ott_ad_events_created", "ott_ad_events", ["created_at"])
    if "ott_channel_invites" not in tables:
        op.create_table(
            "ott_channel_invites",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("channel_id", sa.String(32), nullable=False),
            sa.Column("email", sa.String(254), nullable=False),
            sa.Column("role", sa.String(12), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("channel_id", "email", name="uq_ott_channel_invites"),
        )


def downgrade() -> None:
    tables = _tables()
    if "ott_channel_invites" in tables:
        op.drop_table("ott_channel_invites")
    if "ott_ad_events" in tables:
        op.drop_index("ix_ott_ad_events_created", table_name="ott_ad_events")
        op.drop_table("ott_ad_events")
