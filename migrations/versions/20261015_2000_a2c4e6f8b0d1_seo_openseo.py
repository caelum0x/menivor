"""seo_openseo (Menivor Growth: OpenSEO site audit, keyword research, rank tracking)

Revision ID: a2c4e6f8b0d1
Revises: e5a7c9f1b3d4
Create Date: 2026-10-15 20:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2c4e6f8b0d1'
down_revision: Union[str, None] = 'e5a7c9f1b3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `seo_connections` - one OpenSEO API key per scope (bring-your-own-credential,
    # same pattern as `integration_connections`), plus the OpenSEO project it reads.
    op.create_table(
        'seo_connections',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('owner_scope', sa.String(length=48), nullable=False),
        sa.Column('workspace_id', sa.String(length=32), nullable=True),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=16), server_default=sa.text("('connected')"), nullable=False),
        sa.Column('api_key_enc', sa.Text(), nullable=False),
        sa.Column('token_hint', sa.String(length=16), server_default=sa.text("('')"), nullable=False),
        sa.Column('project_id', sa.String(length=64), server_default=sa.text("('')"), nullable=False),
        sa.Column('domain', sa.String(length=300), server_default=sa.text("('')"), nullable=False),
        sa.Column('last_error', sa.Text(), server_default=sa.text("('')"), nullable=False),
        sa.Column('connected_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('owner_scope', name='uq_seo_connections_scope'),
    )
    op.create_index(op.f('ix_seo_connections_owner_scope'), 'seo_connections', ['owner_scope'], unique=False)
    op.create_index(op.f('ix_seo_connections_workspace_id'), 'seo_connections', ['workspace_id'], unique=False)
    op.create_index(op.f('ix_seo_connections_user_id'), 'seo_connections', ['user_id'], unique=False)

    # `seo_audit_runs` - one site-audit request and its cached score/issues summary.
    op.create_table(
        'seo_audit_runs',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('connection_id', sa.String(length=32), nullable=False),
        sa.Column('owner_scope', sa.String(length=48), nullable=False),
        sa.Column('external_audit_id', sa.String(length=128), server_default=sa.text("('')"), nullable=False),
        sa.Column('status', sa.String(length=16), server_default=sa.text("('queued')"), nullable=False),
        sa.Column('score', sa.Integer(), nullable=True),
        sa.Column('issues_count', sa.Integer(), nullable=True),
        sa.Column('summary', sa.JSON(), nullable=False),
        sa.Column('requested_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['connection_id'], ['seo_connections.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_seo_audit_runs_connection_id'), 'seo_audit_runs', ['connection_id'], unique=False)
    op.create_index(op.f('ix_seo_audit_runs_owner_scope'), 'seo_audit_runs', ['owner_scope'], unique=False)

    # `seo_keyword_research` - cached keyword-research rows (volume, difficulty, CPC,
    # intent) so re-opening the page never re-spends OpenSEO credits.
    op.create_table(
        'seo_keyword_research',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('connection_id', sa.String(length=32), nullable=False),
        sa.Column('owner_scope', sa.String(length=48), nullable=False),
        sa.Column('seed', sa.String(length=200), server_default=sa.text("('')"), nullable=False),
        sa.Column('keyword', sa.String(length=200), nullable=False),
        sa.Column('volume', sa.Integer(), nullable=True),
        sa.Column('difficulty', sa.Integer(), nullable=True),
        sa.Column('cpc_minor', sa.Integer(), nullable=True),
        sa.Column('intent', sa.String(length=32), server_default=sa.text("('')"), nullable=False),
        sa.Column('currency', sa.String(length=3), server_default=sa.text("('USD')"), nullable=False),
        sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['connection_id'], ['seo_connections.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('connection_id', 'keyword', name='uq_seo_keyword_research_conn_kw'),
    )
    op.create_index(op.f('ix_seo_keyword_research_connection_id'), 'seo_keyword_research', ['connection_id'],
                     unique=False)
    op.create_index(op.f('ix_seo_keyword_research_owner_scope'), 'seo_keyword_research', ['owner_scope'],
                     unique=False)

    # `seo_rank_keywords` - the handful (<=10) of target keywords Menivor tracks.
    op.create_table(
        'seo_rank_keywords',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('connection_id', sa.String(length=32), nullable=False),
        sa.Column('owner_scope', sa.String(length=48), nullable=False),
        sa.Column('keyword', sa.String(length=200), nullable=False),
        sa.Column('country', sa.String(length=8), server_default=sa.text("('us')"), nullable=False),
        sa.Column('external_tracker_id', sa.String(length=128), server_default=sa.text("('')"), nullable=False),
        sa.Column('current_rank', sa.Integer(), nullable=True),
        sa.Column('change_7d', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['connection_id'], ['seo_connections.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('connection_id', 'keyword', 'country', name='uq_seo_rank_keyword'),
    )
    op.create_index(op.f('ix_seo_rank_keywords_connection_id'), 'seo_rank_keywords', ['connection_id'], unique=False)
    op.create_index(op.f('ix_seo_rank_keywords_owner_scope'), 'seo_rank_keywords', ['owner_scope'], unique=False)

    # `seo_rank_snapshots` - daily position history per tracked keyword.
    op.create_table(
        'seo_rank_snapshots',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('rank_keyword_id', sa.String(length=32), nullable=False),
        sa.Column('day', sa.String(length=10), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['rank_keyword_id'], ['seo_rank_keywords.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('rank_keyword_id', 'day', name='uq_seo_rank_snapshot_day'),
    )
    op.create_index(op.f('ix_seo_rank_snapshots_rank_keyword_id'), 'seo_rank_snapshots', ['rank_keyword_id'],
                     unique=False)
    op.create_index(op.f('ix_seo_rank_snapshots_day'), 'seo_rank_snapshots', ['day'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_seo_rank_snapshots_day'), table_name='seo_rank_snapshots')
    op.drop_index(op.f('ix_seo_rank_snapshots_rank_keyword_id'), table_name='seo_rank_snapshots')
    op.drop_table('seo_rank_snapshots')
    op.drop_index(op.f('ix_seo_rank_keywords_owner_scope'), table_name='seo_rank_keywords')
    op.drop_index(op.f('ix_seo_rank_keywords_connection_id'), table_name='seo_rank_keywords')
    op.drop_table('seo_rank_keywords')
    op.drop_index(op.f('ix_seo_keyword_research_owner_scope'), table_name='seo_keyword_research')
    op.drop_index(op.f('ix_seo_keyword_research_connection_id'), table_name='seo_keyword_research')
    op.drop_table('seo_keyword_research')
    op.drop_index(op.f('ix_seo_audit_runs_owner_scope'), table_name='seo_audit_runs')
    op.drop_index(op.f('ix_seo_audit_runs_connection_id'), table_name='seo_audit_runs')
    op.drop_table('seo_audit_runs')
    op.drop_index(op.f('ix_seo_connections_user_id'), table_name='seo_connections')
    op.drop_index(op.f('ix_seo_connections_workspace_id'), table_name='seo_connections')
    op.drop_index(op.f('ix_seo_connections_owner_scope'), table_name='seo_connections')
    op.drop_table('seo_connections')
