"""keyword_tracker popularity (Menivor Growth: Apple Search Ads keyword insights)

Revision ID: c6e8a0b2d4f6
Revises: a2c4e6f8b0d1
Create Date: 2026-10-15 22:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c6e8a0b2d4f6'
down_revision: Union[str, None] = 'a2c4e6f8b0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Apple's own Search Popularity index for a tracked keyword, filled in
    # only once the tracking user's scope has a connected `apple_search_ads`
    # account (app.domains.integrations.service.keyword_insights); NULL for
    # everyone else, same "only when connected, honest fallback otherwise"
    # pattern the UI already uses. Purely additive, no backfill needed.
    op.add_column('tracked_keywords', sa.Column('popularity', sa.Integer(), nullable=True))
    op.add_column('tracked_keywords', sa.Column('popularity_checked_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('tracked_keywords', 'popularity_checked_at')
    op.drop_column('tracked_keywords', 'popularity')
