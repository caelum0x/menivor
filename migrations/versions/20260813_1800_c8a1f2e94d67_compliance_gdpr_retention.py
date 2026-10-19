"""compliance / GDPR: retention_policies + consent_records + erasure_requests

Revision ID: c8a1f2e94d67
Revises: b3e9d1c47a52
Create Date: 2026-08-13 18:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8a1f2e94d67'
down_revision: Union[str, None] = 'b3e9d1c47a52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Data Governance / Compliance (Epic 5). Three BRAND-NEW tables — all
    # additive, so every CREATE is safe on an already-populated database and
    # existing rows / prior tests are unaffected. Every column declares its
    # ``server_default`` (where NOT NULL) so the row shape is self-describing and
    # Alembic autogenerate reports no drift.
    #
    # Invariants enforced by / around this schema:
    #   * ``retention_policies`` is keyed on ``workspace_id`` (PK) — exactly one
    #     policy per workspace; NULL windows mean keep-forever (never swept). The
    #     sweep (app.services.compliance.retention) only ever touches rows owned
    #     by that workspace's members and older than that workspace's own window.
    #   * ``consent_records`` is APPEND-ONLY — a consent change inserts a new row;
    #     the current decision is the newest row per (user_id, kind).
    #   * ``erasure_requests`` tracks a GDPR Art. 17 request; the erasure
    #     ANONYMIZES PII in place (never cascade-deletes) preserving financial /
    #     audit records and referential integrity.

    # 1) RETENTION_POLICIES — one retention window per workspace.
    op.create_table(
        'retention_policies',
        sa.Column('workspace_id', sa.String(length=32), nullable=False),
        sa.Column('jobs_retention_days', sa.Integer(), nullable=True),
        sa.Column('assets_retention_days', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ),
        sa.PrimaryKeyConstraint('workspace_id'),
    )

    # 2) CONSENT_RECORDS — append-only consent decisions per user.
    op.create_table(
        'consent_records',
        sa.Column(
            'id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'),
            autoincrement=True, nullable=False,
        ),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('kind', sa.String(length=60), nullable=False),
        sa.Column('granted', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('version', sa.String(length=40), server_default=sa.text("''"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_consent_records_user_id'), 'consent_records', ['user_id'], unique=False)
    op.create_index(op.f('ix_consent_records_created_at'), 'consent_records', ['created_at'], unique=False)

    # 3) ERASURE_REQUESTS — GDPR Art. 17 right-to-erasure lifecycle.
    op.create_table(
        'erasure_requests',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=20), server_default=sa.text("'requested'"), nullable=False),
        sa.Column('scope', sa.String(length=40), server_default=sa.text("'user'"), nullable=False),
        sa.Column('requested_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_erasure_requests_user_id'), 'erasure_requests', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_erasure_requests_user_id'), table_name='erasure_requests')
    op.drop_table('erasure_requests')

    op.drop_index(op.f('ix_consent_records_created_at'), table_name='consent_records')
    op.drop_index(op.f('ix_consent_records_user_id'), table_name='consent_records')
    op.drop_table('consent_records')

    op.drop_table('retention_policies')
