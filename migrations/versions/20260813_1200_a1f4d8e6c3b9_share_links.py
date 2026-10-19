"""share_links (Public Watermarked Share Pages)

Revision ID: a1f4d8e6c3b9
Revises: e2b9c4d7a1f5
Create Date: 2026-08-13 12:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1f4d8e6c3b9'
down_revision: Union[str, None] = 'e2b9c4d7a1f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Public Watermarked Share Pages: a brand-new ``share_links`` table holding a
    # creator's public, unguessable, revocable link to one of THEIR OWN reels. A
    # public visitor (no auth) resolves a link by its ``token`` and sees a
    # WATERMARKED preview — never the clean ``result_key``.
    #
    # SECURITY — SAFE PUBLIC SURFACE. ``token`` is a 128-bit
    # ``secrets.token_urlsafe`` value that is UNIQUE + indexed so it resolves in an
    # O(index) lookup and can never be enumerated. ``revoked`` (default False) is a
    # soft kill-switch: a revoked link is treated as non-existent by every public
    # read (the row is retained for audit), so a creator can instantly and durably
    # take a shared reel offline.
    #
    # STRICTLY PER-USER + one active link per job: ``user_id`` denormalizes the
    # owning creator (always the job's ``user_id``, verified before insert) and is
    # indexed for owner-scoped revoke; ``job_id`` is indexed so the
    # "does an active link already exist for this job?" check is O(index). A
    # brand-new table, so the CREATE is safe on an already-populated database and
    # existing rows / prior tests are unaffected. Columns declare their
    # server_default so the row shape is self-describing and Alembic autogenerate
    # reports no drift.
    op.create_table(
        'share_links',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('job_id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('revoked', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('view_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_share_links_job_id'), 'share_links', ['job_id'], unique=False)
    op.create_index(op.f('ix_share_links_user_id'), 'share_links', ['user_id'], unique=False)
    op.create_index(op.f('ix_share_links_token'), 'share_links', ['token'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_share_links_token'), table_name='share_links')
    op.drop_index(op.f('ix_share_links_user_id'), table_name='share_links')
    op.drop_index(op.f('ix_share_links_job_id'), table_name='share_links')
    op.drop_table('share_links')
