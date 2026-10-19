"""launch_kit (Menivor Growth phase 3: first-100-users launch tooling)

Revision ID: e5a7c9f1b3d4
Revises: d4c10050e5db
Create Date: 2026-10-15 19:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a7c9f1b3d4'
down_revision: Union[str, None] = 'd4c10050e5db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Menivor Growth phase 3: first-100-users / launch-maxxing tooling.
    # `launch_platform_status` - per (user, product, launch directory) submission
    # state (not_started/submitted/live); the directory catalog itself is static
    # code (app.domains.launch_kit.catalog), not a table.
    op.create_table(
        'launch_platform_status',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('product_name', sa.String(length=200), nullable=False),
        sa.Column('platform_id', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=16), server_default=sa.text("('not_started')"), nullable=False),
        sa.Column('note', sa.Text(), server_default=sa.text("('')"), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'product_name', 'platform_id', name='uq_launch_platform_user_product_platform'),
    )
    op.create_index(op.f('ix_launch_platform_status_user_id'), 'launch_platform_status', ['user_id'], unique=False)

    # `launch_playbook_step_status` - per (user, product, playbook step) done/pending
    # state for the 10-step distribution playbook.
    op.create_table(
        'launch_playbook_step_status',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('product_name', sa.String(length=200), nullable=False),
        sa.Column('step_key', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=16), server_default=sa.text("('pending')"), nullable=False),
        sa.Column('note', sa.Text(), server_default=sa.text("('')"), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'product_name', 'step_key', name='uq_launch_step_user_product_step'),
    )
    op.create_index(op.f('ix_launch_playbook_step_status_user_id'), 'launch_playbook_step_status', ['user_id'],
                     unique=False)

    # `launch_pain_point_drafts` - candidate Reddit threads + a drafted reply for a
    # human to review and post by hand. `status` only ever moves between
    # drafted/approved/dismissed; nothing in this feature posts to Reddit.
    op.create_table(
        'launch_pain_point_drafts',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('product_name', sa.String(length=200), server_default=sa.text("('')"), nullable=False),
        sa.Column('query', sa.String(length=300), nullable=False),
        sa.Column('subreddit', sa.String(length=100), server_default=sa.text("('')"), nullable=False),
        sa.Column('thread_url', sa.Text(), nullable=False),
        sa.Column('thread_title', sa.String(length=500), server_default=sa.text("('')"), nullable=False),
        sa.Column('snippet', sa.Text(), server_default=sa.text("('')"), nullable=False),
        sa.Column('upvotes', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('age_days', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('draft_reply', sa.Text(), server_default=sa.text("('')"), nullable=False),
        sa.Column('status', sa.String(length=16), server_default=sa.text("('drafted')"), nullable=False),
        sa.Column('raw', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_launch_pain_point_drafts_user_id'), 'launch_pain_point_drafts', ['user_id'],
                     unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_launch_pain_point_drafts_user_id'), table_name='launch_pain_point_drafts')
    op.drop_table('launch_pain_point_drafts')
    op.drop_index(op.f('ix_launch_playbook_step_status_user_id'), table_name='launch_playbook_step_status')
    op.drop_table('launch_playbook_step_status')
    op.drop_index(op.f('ix_launch_platform_status_user_id'), table_name='launch_platform_status')
    op.drop_table('launch_platform_status')
