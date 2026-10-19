"""Ad Clone product presets made by the Brand Agent from the user's own products.

Additive and idempotent (created only when missing).

Revision ID: a1c3e5f7b9d2
Revises: f7b9d1e3a5c8
Create Date: 2026-10-06 15:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1c3e5f7b9d2'
down_revision: Union[str, None] = 'f7b9d1e3a5c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "adclone_presets" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "adclone_presets",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("space_id", sa.String(32), nullable=True),
        sa.Column("product_ref", sa.String(80), nullable=False, server_default=""),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_adclone_presets_user_id", "adclone_presets", ["user_id"])
    op.create_index("ix_adclone_presets_space_id", "adclone_presets", ["space_id"])


def downgrade() -> None:
    if "adclone_presets" not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.drop_index("ix_adclone_presets_space_id", table_name="adclone_presets")
    op.drop_index("ix_adclone_presets_user_id", table_name="adclone_presets")
    op.drop_table("adclone_presets")
