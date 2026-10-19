"""OTT transcode lanes: ``ott_nodes``, ``ott_encode_jobs``, ``ott_content_keys`` (Wave P PM2.4, MV2/MV3)

Additive and idempotent. ``ott_content_keys.key_enc`` holds the tier-1 key
encrypted with ``OTT_CONTENT_KEY_SECRET``; the plain key is never stored.

Revision ID: c2e4a6b8d0f3
Revises: b1d3f5a7c9e2
Create Date: 2026-10-01 10:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c2e4a6b8d0f3'
down_revision: Union[str, None] = 'b1d3f5a7c9e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    tables = _tables()
    if "ott_nodes" not in tables:
        op.create_table(
            "ott_nodes",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("name", sa.String(60), nullable=False),
            sa.Column("kind", sa.String(12), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("free_gb", sa.Float(), nullable=False, server_default="0"),
            sa.Column("cores", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    if "ott_encode_jobs" not in tables:
        op.create_table(
            "ott_encode_jobs",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("title_id", sa.String(32), nullable=False),
            sa.Column("user_id", sa.String(32), nullable=False),
            sa.Column("source_key", sa.String(512), nullable=False),
            sa.Column("source_seconds", sa.Float(), nullable=False, server_default="0"),
            sa.Column("source_height", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("paid_plan", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("lane", sa.String(12), nullable=False),
            sa.Column("status", sa.String(12), nullable=False, server_default="queued"),
            sa.Column("node_id", sa.String(32), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cpu_seconds", sa.Float(), nullable=False, server_default="0"),
            sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
            sa.Column("output_prefix", sa.String(512), nullable=False, server_default=""),
            sa.Column("manifest_key", sa.String(512), nullable=False, server_default=""),
            sa.Column("packager_sha256", sa.String(64), nullable=False, server_default=""),
            sa.Column("error", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        )
    existing = _indexes("ott_encode_jobs")
    if "ix_ott_encode_jobs_title_id" not in existing:
        op.create_index("ix_ott_encode_jobs_title_id", "ott_encode_jobs", ["title_id"])
    if "ix_ott_encode_jobs_lane_status" not in existing:
        op.create_index("ix_ott_encode_jobs_lane_status", "ott_encode_jobs", ["lane", "status", "created_at"])
    if "ott_content_keys" not in tables:
        op.create_table(
            "ott_content_keys",
            sa.Column("title_id", sa.String(32), primary_key=True),
            sa.Column("key_id_hex", sa.String(32), nullable=False),
            sa.Column("key_enc", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )


def downgrade() -> None:
    tables = _tables()
    for name in ("ott_content_keys", "ott_encode_jobs", "ott_nodes"):
        if name in tables:
            op.drop_table(name)
