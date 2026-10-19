"""social_accounts (Direct-Publish OAuth account-connect)

Revision ID: e2b9c4d7a1f5
Revises: b7f3a1c92d84
Create Date: 2026-08-13 11:30:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2b9c4d7a1f5'
down_revision: Union[str, None] = 'b7f3a1c92d84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Direct-Publish Account-Connect: a brand-new ``social_accounts`` table holding
    # a creator's OAuth connection to a social platform (tiktok | instagram |
    # youtube) so a finished reel can be posted straight to their account.
    #
    # AUTH-CRITICAL — the plaintext OAuth tokens are NEVER stored. Only their
    # symmetrically-encrypted blobs are persisted (``access_token_enc`` /
    # ``refresh_token_enc``), encrypted at the service boundary
    # (app.services.crypto_tokens) with a config/env key. ``access_token_enc`` is
    # NOT NULL (a connection always carries an access token); ``refresh_token_enc``
    # is nullable because not every provider issues one, and ``token_expires_at``
    # is nullable (drives proactive refresh).
    #
    # STRICTLY PER-USER + one row per (user, provider): ``user_id`` is indexed for
    # owner-scoped listing and a composite UNIQUE on ``(user_id, provider)``
    # guarantees at most one connection per platform (a re-connect UPSERTs in
    # place). A brand-new table, so the CREATE is safe on an already-populated
    # database and existing rows / prior tests are unaffected. Columns declare
    # their server_default so the row shape is self-describing and Alembic
    # autogenerate reports no drift.
    op.create_table(
        'social_accounts',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('external_account_id', sa.String(length=200), server_default=sa.text("('')"), nullable=False),
        sa.Column('access_token_enc', sa.Text(), nullable=False),
        sa.Column('refresh_token_enc', sa.Text(), nullable=True),
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('scopes', sa.Text(), server_default=sa.text("('')"), nullable=False),
        sa.Column('connected_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'provider', name='uq_social_accounts_user_provider'),
    )
    op.create_index(op.f('ix_social_accounts_user_id'), 'social_accounts', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_social_accounts_user_id'), table_name='social_accounts')
    op.drop_table('social_accounts')
