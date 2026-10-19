"""Weekly preset drops: ``preset_drops`` (Wave P PM3.0, MH9)

Additive and idempotent: one row per released ISO week.

Revision ID: e5b7d9f1a3c6
Revises: c2e4a6b8d0f3
Create Date: 2026-10-02 09:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e5b7d9f1a3c6'
down_revision: Union[str, None] = 'c2e4a6b8d0f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "preset_drops" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "preset_drops",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("week", sa.String(10), nullable=False, unique=True),
        sa.Column("preset_ids", sa.JSON(), nullable=False),
        sa.Column("spend_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    if "preset_drops" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("preset_drops")
