"""job studio columns

Revision ID: 677d1259a269
Revises: 8d33fcd0b532
Create Date: 2026-08-11 08:58:35.624302+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '677d1259a269'
down_revision: Union[str, None] = '8d33fcd0b532'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Phase-6 (Creator Studio) artifacts / config on jobs. ``server_default`` is
    # set so each NOT NULL ADD COLUMN is safe on an already-populated jobs table
    # (existing rows backfill to '') and the ORM default keeps new inserts at ''.
    op.add_column('jobs', sa.Column('poster_key', sa.String(length=512), server_default=sa.text("('')"), nullable=False))
    op.add_column('jobs', sa.Column('preview_key', sa.String(length=512), server_default=sa.text("('')"), nullable=False))
    op.add_column('jobs', sa.Column('webhook_url', sa.String(length=1024), server_default=sa.text("('')"), nullable=False))


def downgrade() -> None:
    op.drop_column('jobs', 'webhook_url')
    op.drop_column('jobs', 'preview_key')
    op.drop_column('jobs', 'poster_key')
