"""enterprise identity & sso: sso_connections + scim_tokens + security_policies + external_identities

Revision ID: f1a2b3c4d5e6
Revises: e5f2a9c74b13
Create Date: 2026-08-13 15:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'e5f2a9c74b13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Explicit name so the composite UNIQUE is addressable in ``downgrade`` and
# portable across SQLite (tests) and Postgres/Neon (prod).
_UQ_EXTID_WS_SUBJECT = "uq_external_identities_ws_subject"


def upgrade() -> None:
    # Enterprise Identity & SSO (Epic 2). Four BRAND-NEW tables — all additive, so
    # every CREATE is safe on an already-populated database and existing rows /
    # prior tests are unaffected. Every column declares its ``server_default`` so
    # the row shape is self-describing and Alembic autogenerate reports no drift.
    #
    # AUTH-CRITICAL — the IdP signing certificate (``idp_x509_cert_enc``) and the
    # OIDC client secret (``oidc_client_secret_enc``) are stored ONLY as Fernet
    # blobs (never plaintext), encrypted at the service boundary
    # (app.services.crypto_tokens, SOCIAL_TOKEN_KEY). Likewise a SCIM bearer token
    # is stored ONLY as its SHA-256 digest (``token_hash``), never the raw secret.
    #
    # TENANT ISOLATION is enforced by schema: ``sso_connections.workspace_id`` is
    # UNIQUE (one IdP per workspace); a ``scim_tokens`` row carries the single
    # workspace it may provision into; ``security_policies.workspace_id`` is the
    # PK (one policy per workspace); and ``external_identities`` is UNIQUE on
    # ``(workspace_id, idp_subject)`` so a subject maps to at most one identity per
    # workspace and can never be resolved cross-tenant.

    # 1) SSO_CONNECTIONS — one IdP connection per workspace (SAML | OIDC).
    op.create_table(
        'sso_connections',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('workspace_id', sa.String(length=32), nullable=False),
        sa.Column('protocol', sa.String(length=10), server_default=sa.text("'saml'"), nullable=False),
        sa.Column('idp_entity_id', sa.String(length=512), server_default=sa.text("('')"), nullable=False),
        sa.Column('idp_sso_url', sa.String(length=1024), server_default=sa.text("('')"), nullable=False),
        sa.Column('idp_x509_cert_enc', sa.Text(), nullable=True),
        sa.Column('sp_acs_url', sa.String(length=1024), server_default=sa.text("('')"), nullable=False),
        sa.Column('oidc_client_id', sa.String(length=512), nullable=True),
        sa.Column('oidc_client_secret_enc', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workspace_id', name='uq_sso_connections_workspace'),
    )
    op.create_index(op.f('ix_sso_connections_workspace_id'), 'sso_connections', ['workspace_id'], unique=False)

    # 2) SCIM_TOKENS — per-workspace bearer tokens (only the SHA-256 digest stored).
    op.create_table(
        'scim_tokens',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('workspace_id', sa.String(length=32), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('prefix', sa.String(length=16), server_default=sa.text("('')"), nullable=False),
        sa.Column('revoked', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash', name='uq_scim_tokens_token_hash'),
    )
    op.create_index(op.f('ix_scim_tokens_workspace_id'), 'scim_tokens', ['workspace_id'], unique=False)
    op.create_index(op.f('ix_scim_tokens_revoked'), 'scim_tokens', ['revoked'], unique=False)

    # 3) SECURITY_POLICIES — one login policy per workspace (workspace_id is PK).
    op.create_table(
        'security_policies',
        sa.Column('workspace_id', sa.String(length=32), nullable=False),
        sa.Column('require_sso', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('session_timeout_min', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('allowed_email_domains', sa.JSON(), nullable=True),
        sa.Column('mfa_required', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('ip_allowlist', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ),
        sa.PrimaryKeyConstraint('workspace_id'),
    )

    # 4) EXTERNAL_IDENTITIES — IdP subject <-> user link, unique per workspace.
    op.create_table(
        'external_identities',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('workspace_id', sa.String(length=32), nullable=False),
        sa.Column('idp_subject', sa.String(length=512), nullable=False),
        sa.Column('email', sa.String(length=320), server_default=sa.text("('')"), nullable=False),
        sa.Column('provisioned', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workspace_id', 'idp_subject', name=_UQ_EXTID_WS_SUBJECT),
    )
    op.create_index(op.f('ix_external_identities_user_id'), 'external_identities', ['user_id'], unique=False)
    op.create_index(op.f('ix_external_identities_workspace_id'), 'external_identities', ['workspace_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_external_identities_workspace_id'), table_name='external_identities')
    op.drop_index(op.f('ix_external_identities_user_id'), table_name='external_identities')
    op.drop_table('external_identities')

    op.drop_table('security_policies')

    op.drop_index(op.f('ix_scim_tokens_revoked'), table_name='scim_tokens')
    op.drop_index(op.f('ix_scim_tokens_workspace_id'), table_name='scim_tokens')
    op.drop_table('scim_tokens')

    op.drop_index(op.f('ix_sso_connections_workspace_id'), table_name='sso_connections')
    op.drop_table('sso_connections')
