"""store_connections (Phase 3 "Connect your store": App Store Connect + Play)

Revision ID: d4f6a8c0e1f3
Revises: c3e5a7b9d1f2
Create Date: 2026-10-15 12:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4f6a8c0e1f3'
down_revision: Union[str, None] = 'c3e5a7b9d1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Phase 3 "Connect your store": a brand-new `store_connections` table holding
    # a creator's App Store Connect API key or Google Play service-account JSON
    # so Menivor can read their published apps' current versions and ratings
    # (feeding the App Store Audit tool).
    #
    # AUTH-CRITICAL — the whole credential is NEVER stored in the clear. Only
    # its symmetrically-encrypted JSON blob is persisted (`credentials_enc`),
    # encrypted at the service boundary (app.services.crypto_tokens — the same
    # Fernet helper already protecting `social_accounts`) with a config/env key.
    # `account_name` is a NON-secret label (ASC issuer id, or the Play service
    # account's client_email) so the UI can show "which account" without
    # decrypting anything.
    #
    # STRICTLY PER-USER + one row per (user, provider): `user_id` is indexed for
    # owner-scoped listing and a composite UNIQUE on (user_id, provider)
    # guarantees at most one connection per store (a re-connect UPSERTs in
    # place). A brand-new table, so the CREATE is safe on an already-populated
    # database.
    op.create_table(
        'store_connections',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('account_name', sa.String(length=300), server_default=sa.text("('')"), nullable=False),
        sa.Column('credentials_enc', sa.Text(), nullable=False),
        sa.Column('meta', sa.JSON(), server_default=sa.text("('{}')"), nullable=False),
        sa.Column('status', sa.String(length=20), server_default=sa.text("('connected')"), nullable=False),
        sa.Column('status_note', sa.Text(), server_default=sa.text("('')"), nullable=False),
        sa.Column('connected_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'provider', name='uq_store_connections_user_provider'),
    )
    op.create_index(op.f('ix_store_connections_user_id'), 'store_connections', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_store_connections_user_id'), table_name='store_connections')
    op.drop_table('store_connections')
