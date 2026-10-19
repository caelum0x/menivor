"""Gallery and Recreate: ``gallery_items`` and ``gallery_remixes`` (Wave P PM1.3, MH3)

Opt-in finished outputs (preset id and whitelisted render settings only) and
the Recreate remix links that raise ``remix_count`` once each. Purely
additive and idempotent: every create checks the inspector first.

Revision ID: e2a4c6d8f0b1
Revises: d8e1f3a5c7b9
Create Date: 2026-09-30 09:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e2a4c6d8f0b1'
down_revision: Union[str, None] = 'd8e1f3a5c7b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    tables = _tables()
    if "gallery_items" not in tables:
        op.create_table(
            "gallery_items",
            sa.Column("id", sa.String(length=32), nullable=False),
            sa.Column("job_id", sa.String(length=32), nullable=False),
            sa.Column("user_id", sa.String(length=32), nullable=False),
            sa.Column("title", sa.String(length=80), nullable=False, server_default=""),
            sa.Column("preset_id", sa.String(length=80), nullable=False, server_default="reel"),
            sa.Column("safe_params", sa.JSON(), nullable=False),
            sa.Column("remix_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("wall_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("hidden_reason", sa.String(length=40), nullable=False, server_default=""),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("job_id", name="uq_gallery_items_job"),
        )
    indexes = _indexes("gallery_items")
    if "ix_gallery_items_user_id" not in indexes:
        op.create_index("ix_gallery_items_user_id", "gallery_items", ["user_id"])
    if "ix_gallery_items_visible" not in indexes:
        op.create_index("ix_gallery_items_visible", "gallery_items", ["hidden_at", "published_at"])
    if "gallery_remixes" not in tables:
        op.create_table(
            "gallery_remixes",
            sa.Column("id", sa.String(length=32), nullable=False),
            sa.Column("item_id", sa.String(length=32), nullable=False),
            sa.Column("job_id", sa.String(length=32), nullable=False),
            sa.Column("user_id", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("counted_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("job_id", name="uq_gallery_remixes_job"),
        )
    if "ix_gallery_remixes_item_id" not in _indexes("gallery_remixes"):
        op.create_index("ix_gallery_remixes_item_id", "gallery_remixes", ["item_id"])


def downgrade() -> None:
    tables = _tables()
    if "gallery_remixes" in tables:
        op.drop_table("gallery_remixes")
    if "gallery_items" in tables:
        op.drop_table("gallery_items")
