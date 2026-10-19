"""OTT live, chat and linear: ``ott_live_streams``, ``ott_chat_messages``, ``ott_linear_channels`` (Wave P PM3.4, MV10/MV11/MV15)

Additive and idempotent. Stream keys are stored as SHA-256 only.

Revision ID: b8e0a2c4d6f9
Revises: a7d9f1b3c5e8
Create Date: 2026-10-02 12:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b8e0a2c4d6f9'
down_revision: Union[str, None] = 'a7d9f1b3c5e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "ott_live_streams" not in tables:
        op.create_table(
            "ott_live_streams",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("channel_id", sa.String(32), nullable=False),
            sa.Column("title", sa.String(120), nullable=False),
            sa.Column("path", sa.String(40), nullable=False, unique=True),
            sa.Column("key_hash", sa.String(64), nullable=False),
            sa.Column("access_tier", sa.String(8), nullable=False, server_default="free"),
            sa.Column("status", sa.String(8), nullable=False, server_default="idle"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("peak_viewers", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("latency_samples", sa.JSON(), nullable=False),
            sa.Column("recordings", sa.JSON(), nullable=False),
            sa.Column("vod_title_ids", sa.JSON(), nullable=False),
            sa.Column("chat_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("slow_mode_s", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("banned_viewer_ids", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_ott_live_streams_channel_id", "ott_live_streams", ["channel_id"])
    if "ott_chat_messages" not in tables:
        op.create_table(
            "ott_chat_messages",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("stream_id", sa.String(32), nullable=False),
            sa.Column("viewer_id", sa.String(32), nullable=False),
            sa.Column("display_name", sa.String(60), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("hidden_reason", sa.String(16), nullable=False, server_default=""),
        )
        op.create_index("ix_ott_chat_messages_stream_created", "ott_chat_messages", ["stream_id", "created_at"])
    if "ott_linear_channels" not in tables:
        op.create_table(
            "ott_linear_channels",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("channel_id", sa.String(32), nullable=False),
            sa.Column("slug", sa.String(40), nullable=False),
            sa.Column("name", sa.String(80), nullable=False),
            sa.Column("title_ids", sa.JSON(), nullable=False),
            sa.Column("ad_break_every", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("anchor_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("slug", name="uq_ott_linear_channels_slug"),
        )
        op.create_index("ix_ott_linear_channels_channel_id", "ott_linear_channels", ["channel_id"])


def downgrade() -> None:
    tables = _tables()
    for table in ("ott_linear_channels", "ott_chat_messages", "ott_live_streams"):
        if table in tables:
            op.drop_table(table)
