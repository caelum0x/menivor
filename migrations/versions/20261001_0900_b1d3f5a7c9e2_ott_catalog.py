"""OTT catalog: ``ott_channels``, ``ott_series``, ``ott_titles``, ``ott_collections`` (Wave P PM2.3, MV1)

Purely additive and idempotent (every table and index is created only when
missing). Applied only to a scratch local database during the wave.

Revision ID: b1d3f5a7c9e2
Revises: a9c1e3f5b7d2
Create Date: 2026-10-01 09:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b1d3f5a7c9e2'
down_revision: Union[str, None] = 'a9c1e3f5b7d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def _ts(name: str, nullable: bool = True, default: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable,
                     server_default=sa.func.now() if default else None)


def upgrade() -> None:
    tables = _tables()
    if "ott_channels" not in tables:
        op.create_table(
            "ott_channels",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("user_id", sa.String(32), nullable=False),
            sa.Column("handle", sa.String(40), nullable=False),
            sa.Column("title", sa.String(80), nullable=False, server_default=""),
            sa.Column("tagline", sa.String(160), nullable=False, server_default=""),
            sa.Column("layout", sa.String(16), nullable=False, server_default="grid"),
            sa.Column("brand_colors", sa.JSON(), nullable=False),
            sa.Column("artwork_key", sa.String(512), nullable=False, server_default=""),
            sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
            sa.Column("custom_domain", sa.String(253), nullable=True),
            _ts("published_at"), _ts("created_at", default=True), _ts("updated_at", default=True),
            sa.UniqueConstraint("user_id", name="uq_ott_channels_user"),
            sa.UniqueConstraint("handle", name="uq_ott_channels_handle"),
            sa.UniqueConstraint("custom_domain", name="uq_ott_channels_domain"),
        )
    if "ott_series" not in tables:
        op.create_table(
            "ott_series",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("channel_id", sa.String(32), nullable=False),
            sa.Column("title", sa.String(120), nullable=False),
            sa.Column("synopsis", sa.Text(), nullable=False, server_default=""),
            sa.Column("artwork_key", sa.String(512), nullable=False, server_default=""),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            _ts("created_at", default=True),
        )
    if "ix_ott_series_channel_id" not in _indexes("ott_series"):
        op.create_index("ix_ott_series_channel_id", "ott_series", ["channel_id"])
    if "ott_titles" not in tables:
        op.create_table(
            "ott_titles",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("channel_id", sa.String(32), nullable=False),
            sa.Column("series_id", sa.String(32), nullable=True),
            sa.Column("season", sa.Integer(), nullable=True),
            sa.Column("episode", sa.Integer(), nullable=True),
            sa.Column("kind", sa.String(16), nullable=False, server_default="short"),
            sa.Column("source_job_id", sa.String(32), nullable=True),
            sa.Column("source_key", sa.String(512), nullable=False, server_default=""),
            sa.Column("title", sa.String(120), nullable=False),
            sa.Column("synopsis", sa.Text(), nullable=False, server_default=""),
            sa.Column("artwork_key", sa.String(512), nullable=False, server_default=""),
            sa.Column("duration_s", sa.Float(), nullable=False, server_default="0"),
            sa.Column("genres", sa.JSON(), nullable=False),
            sa.Column("rating", sa.String(12), nullable=False, server_default=""),
            _ts("available_from"), _ts("available_until"),
            sa.Column("access_tier", sa.String(12), nullable=False, server_default="free"),
            sa.Column("geo_mode", sa.String(8), nullable=False, server_default="all"),
            sa.Column("geo_countries", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
            sa.Column("hidden_reason", sa.String(20), nullable=False, server_default=""),
            sa.Column("package_status", sa.String(16), nullable=False, server_default="none"),
            sa.Column("manifest_key", sa.String(512), nullable=False, server_default=""),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            _ts("published_at"), _ts("created_at", default=True), _ts("updated_at", default=True),
            sa.UniqueConstraint("channel_id", "source_job_id", name="uq_ott_titles_channel_job"),
        )
    existing = _indexes("ott_titles")
    if "ix_ott_titles_channel_status" not in existing:
        op.create_index("ix_ott_titles_channel_status", "ott_titles", ["channel_id", "status", "position"])
    if "ix_ott_titles_source_job" not in existing:
        op.create_index("ix_ott_titles_source_job", "ott_titles", ["source_job_id"])
    if "ott_collections" not in tables:
        op.create_table(
            "ott_collections",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("channel_id", sa.String(32), nullable=False),
            sa.Column("title", sa.String(80), nullable=False),
            sa.Column("kind", sa.String(16), nullable=False, server_default="rail"),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("title_ids", sa.JSON(), nullable=False),
            _ts("created_at", default=True),
        )
    if "ix_ott_collections_channel_id" not in _indexes("ott_collections"):
        op.create_index("ix_ott_collections_channel_id", "ott_collections", ["channel_id"])


def downgrade() -> None:
    tables = _tables()
    for name in ("ott_collections", "ott_titles", "ott_series", "ott_channels"):
        if name in tables:
            op.drop_table(name)
