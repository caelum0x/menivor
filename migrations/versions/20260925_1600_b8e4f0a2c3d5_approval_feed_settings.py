"""Approvals feed settings: opt-in capture / catalog suggestions (default off)

Additive: one new table, nothing existing is altered.

* ``approval_feed_settings`` - per-owner list of scanned approval sources
  (``capture_publish``, ``catalog_import``) allowed to add items on their own.
  No row means every opt-in source is off.

Revision ID: b8e4f0a2c3d5
Revises: a7d3e9c1f2b4
Create Date: 2026-09-25 16:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8e4f0a2c3d5'
down_revision: Union[str, None] = 'a7d3e9c1f2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "approval_feed_settings",
        sa.Column("user_id", sa.String(length=32), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("auto_sources", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("approval_feed_settings")
