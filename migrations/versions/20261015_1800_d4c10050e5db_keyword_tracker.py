"""keyword_tracker (Menivor Growth phase 2: daily App Store keyword rank tracking)

Revision ID: d4c10050e5db
Revises: d4f6a8c0e1f3
Create Date: 2026-10-15 18:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4c10050e5db'
down_revision: Union[str, None] = 'd4f6a8c0e1f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Menivor Growth phase 2: a creator tracks a (App Store app, keyword,
    # country) triple; a daily Celery beat tick checks its top-50 rank via the
    # public, keyless iTunes Search API (app.domains.appaudit.visibility's
    # existing 24h cache) and appends a row to `keyword_rank_snapshots`, so the
    # UI can draw a current-rank + 7/30-day-change + sparkline history chart
    # without a second round of scraping. Google Play has no public rank API
    # (same honest limitation already documented for the App Store Audit tool
    # and Phase 3 store-connect), so this feature is App Store only.
    op.create_table(
        'tracked_keywords',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('app_id', sa.String(length=32), nullable=False),
        sa.Column('app_name', sa.String(length=300), server_default=sa.text("('')"), nullable=False),
        sa.Column('country', sa.String(length=2), server_default=sa.text("('us')"), nullable=False),
        sa.Column('term', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_position', sa.Integer(), nullable=True),
        sa.Column('last_checked_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('last_error', sa.Text(), server_default=sa.text("('')"), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'app_id', 'term', 'country', name='uq_tracked_keywords_user_app_term_country'),
    )
    op.create_index(op.f('ix_tracked_keywords_user_id'), 'tracked_keywords', ['user_id'], unique=False)

    op.create_table(
        'keyword_rank_snapshots',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('keyword_id', sa.String(length=32), nullable=False),
        sa.Column('checked_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('position', sa.Integer(), nullable=True),
        sa.Column('checked_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.ForeignKeyConstraint(['keyword_id'], ['tracked_keywords.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_keyword_rank_snapshots_keyword_id'), 'keyword_rank_snapshots', ['keyword_id'], unique=False,
    )
    op.create_index(
        'ix_keyword_rank_snapshots_keyword_checked', 'keyword_rank_snapshots', ['keyword_id', 'checked_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_keyword_rank_snapshots_keyword_checked', table_name='keyword_rank_snapshots')
    op.drop_index(op.f('ix_keyword_rank_snapshots_keyword_id'), table_name='keyword_rank_snapshots')
    op.drop_table('keyword_rank_snapshots')
    op.drop_index(op.f('ix_tracked_keywords_user_id'), table_name='tracked_keywords')
    op.drop_table('tracked_keywords')
