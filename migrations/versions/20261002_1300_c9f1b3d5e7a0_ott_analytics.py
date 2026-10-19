"""OTT analytics, team roles, AI outputs and discovery (Wave P PM3.5, MV12/MV16/MV19)

``ott_beacons``, ``ott_qoe_hourly``, ``ott_channel_members``, ``ott_ai_outputs``,
``ott_title_embeddings``. Additive and idempotent. Viewers appear only as a
salted hash; raw beacons are swept after 30 days.

Revision ID: c9f1b3d5e7a0
Revises: b8e0a2c4d6f9
Create Date: 2026-10-02 13:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c9f1b3d5e7a0'
down_revision: Union[str, None] = 'b8e0a2c4d6f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "ott_beacons" not in tables:
        op.create_table(
            "ott_beacons",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("channel_id", sa.String(32), nullable=False),
            sa.Column("title_id", sa.String(32), nullable=False),
            sa.Column("session_id", sa.String(40), nullable=False),
            sa.Column("viewer_hash", sa.String(32), nullable=False),
            sa.Column("event", sa.String(12), nullable=False),
            sa.Column("hour", sa.String(13), nullable=False),
            sa.Column("watched_s", sa.Float(), nullable=False, server_default="0"),
            sa.Column("startup_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("stall_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("bitrate_kbps", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_code", sa.String(40), nullable=False, server_default=""),
            sa.Column("device", sa.String(12), nullable=False, server_default="web"),
            sa.Column("country", sa.String(2), nullable=False, server_default="XX"),
            sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_ott_beacons_title_hour", "ott_beacons", ["title_id", "hour"])
        op.create_index("ix_ott_beacons_received", "ott_beacons", ["received_at"])
    if "ott_qoe_hourly" not in tables:
        op.create_table(
            "ott_qoe_hourly",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("channel_id", sa.String(32), nullable=False),
            sa.Column("title_id", sa.String(32), nullable=False),
            sa.Column("hour", sa.String(13), nullable=False),
            sa.Column("plays", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("viewers", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("watch_s", sa.Float(), nullable=False, server_default="0"),
            sa.Column("startup_p50_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("startup_p95_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("stalls", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("stall_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("errors", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("beacons", sa.Integer(), nullable=False, server_default="0"),
            sa.UniqueConstraint("title_id", "hour", name="uq_ott_qoe_hourly_title_hour"),
        )
        op.create_index("ix_ott_qoe_hourly_channel_hour", "ott_qoe_hourly", ["channel_id", "hour"])
    if "ott_channel_members" not in tables:
        op.create_table(
            "ott_channel_members",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("channel_id", sa.String(32), nullable=False),
            sa.Column("user_id", sa.String(32), nullable=False),
            sa.Column("role", sa.String(12), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("channel_id", "user_id", name="uq_ott_channel_members"),
        )
    if "ott_ai_outputs" not in tables:
        op.create_table(
            "ott_ai_outputs",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("title_id", sa.String(32), nullable=False),
            sa.Column("kind", sa.String(12), nullable=False),
            sa.Column("language", sa.String(8), nullable=False, server_default=""),
            sa.Column("status", sa.String(8), nullable=False, server_default="queued"),
            sa.Column("key", sa.String(512), nullable=False, server_default=""),
            sa.Column("data", sa.JSON(), nullable=False),
            sa.Column("error", sa.Text(), nullable=False, server_default=""),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("title_id", "kind", "language", name="uq_ott_ai_outputs_title_kind_lang"),
        )
    if "ott_title_embeddings" not in tables:
        op.create_table(
            "ott_title_embeddings",
            sa.Column("title_id", sa.String(32), primary_key=True),
            sa.Column("channel_id", sa.String(32), nullable=False),
            sa.Column("model", sa.String(60), nullable=False),
            sa.Column("dim", sa.Integer(), nullable=False),
            sa.Column("vector", sa.JSON(), nullable=False),
            sa.Column("text_hash", sa.String(64), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_ott_title_embeddings_channel_id", "ott_title_embeddings", ["channel_id"])


def downgrade() -> None:
    tables = _tables()
    for table in ("ott_title_embeddings", "ott_ai_outputs", "ott_channel_members", "ott_qoe_hourly", "ott_beacons"):
        if table in tables:
            op.drop_table(table)
