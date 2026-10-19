"""enterprise API platform: webhook_subscriptions + webhook_deliveries

Revision ID: b3e9d1c47a52
Revises: a7c1e3f5b902
Create Date: 2026-08-13 17:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3e9d1c47a52'
down_revision: Union[str, None] = 'a7c1e3f5b902'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Explicit constraint name so the composite UNIQUE idempotency guard is
# addressable in ``downgrade`` and portable across SQLite (tests) and Postgres.
_UQ_DELIVERY_IDEMPOTENCY = "uq_webhook_deliveries_sub_event"


def upgrade() -> None:
    # Enterprise API Platform (Epic 4). Two BRAND-NEW tables — all additive, so
    # every CREATE is safe on an already-populated database and existing rows /
    # prior tests are unaffected. Every column declares its ``server_default`` so
    # the row shape is self-describing and Alembic autogenerate reports no drift.
    #
    # SECURITY invariants enforced by / around this schema:
    #   * ``webhook_subscriptions.secret_enc`` stores ONLY the Fernet-encrypted
    #     HMAC signing secret (plaintext shown once at create, never persisted).
    #   * a subscription ``url`` is validated through the SAME SSRF guard used by
    #     app.services.webhooks.deliver_webhook BEFORE insert (service layer), so
    #     an internal/private/loopback target can never be registered.
    #   * ``webhook_deliveries`` is idempotent: UNIQUE(subscription_id, event_id)
    #     means the SAME event is delivered to a given subscription at most once
    #     (a replay hits the constraint and is ignored).
    # TENANT ISOLATION: ``webhook_subscriptions.workspace_id`` (indexed) owns the
    # subscription; no query ever returns another tenant's subscription/deliveries.

    # 1) WEBHOOK_SUBSCRIPTIONS — a workspace's outbound-event subscription.
    op.create_table(
        'webhook_subscriptions',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('workspace_id', sa.String(length=32), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('event_types', sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column('secret_enc', sa.Text(), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_webhook_subscriptions_workspace_id'), 'webhook_subscriptions', ['workspace_id'], unique=False)

    # 2) WEBHOOK_DELIVERIES — idempotent per-(subscription, event) delivery record.
    op.create_table(
        'webhook_deliveries',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('subscription_id', sa.String(length=32), nullable=False),
        sa.Column('event_type', sa.String(length=80), nullable=False),
        sa.Column('event_id', sa.String(length=160), nullable=False),
        sa.Column('payload', sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column('status', sa.String(length=20), server_default=sa.text("'pending'"), nullable=False),
        sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('response_code', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['subscription_id'], ['webhook_subscriptions.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('subscription_id', 'event_id', name=_UQ_DELIVERY_IDEMPOTENCY),
    )
    op.create_index(op.f('ix_webhook_deliveries_subscription_id'), 'webhook_deliveries', ['subscription_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_webhook_deliveries_subscription_id'), table_name='webhook_deliveries')
    op.drop_table('webhook_deliveries')

    op.drop_index(op.f('ix_webhook_subscriptions_workspace_id'), table_name='webhook_subscriptions')
    op.drop_table('webhook_subscriptions')
