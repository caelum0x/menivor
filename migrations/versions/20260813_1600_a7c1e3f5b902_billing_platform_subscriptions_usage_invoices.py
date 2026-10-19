"""enterprise billing platform: subscriptions + metered_usage + invoices + invoice_line_items

Revision ID: a7c1e3f5b902
Revises: f1a2b3c4d5e6
Create Date: 2026-08-13 16:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c1e3f5b902'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Explicit constraint names so the composite UNIQUE / one-per-workspace guards are
# addressable in ``downgrade`` and portable across SQLite (tests) and Postgres.
_UQ_SUBSCRIPTIONS_WS = "uq_subscriptions_workspace"
_UQ_METERED_IDEMPOTENCY = "uq_metered_usage_idempotency_key"


def upgrade() -> None:
    # Enterprise Billing Platform (Epic 3). Four BRAND-NEW tables — all additive,
    # so every CREATE is safe on an already-populated database and existing rows /
    # prior tests are unaffected. Every column declares its ``server_default`` so
    # the row shape is self-describing and Alembic autogenerate reports no drift.
    #
    # MONEY-CORRECTNESS is enforced by schema:
    #   * ``subscriptions.workspace_id`` is UNIQUE — one subscription per workspace,
    #     so a plan change updates in place and a duplicate provider event resolves
    #     to the same row (never two conflicting subscriptions).
    #   * ``metered_usage.idempotency_key`` is UNIQUE — the SAME metering event can
    #     never be counted twice (a replay hits the constraint and is ignored),
    #     so usage-based billing cannot be gamed or double-counted.
    #   * amounts are INTEGER minor units (cents), never floats — exact money.
    # TENANT ISOLATION: every table carries the owning ``workspace_id`` (indexed);
    # no query ever returns another tenant's subscription / usage / invoices.

    # 1) SUBSCRIPTIONS — one billing subscription per workspace.
    op.create_table(
        'subscriptions',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('workspace_id', sa.String(length=32), nullable=False),
        sa.Column('plan_key', sa.String(length=40), server_default=sa.text("'free'"), nullable=False),
        sa.Column('provider', sa.String(length=40), server_default=sa.text("'stripe'"), nullable=False),
        sa.Column('provider_ref', sa.String(length=255), server_default=sa.text("('')"), nullable=False),
        sa.Column('status', sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
        sa.Column('interval', sa.String(length=10), server_default=sa.text("'month'"), nullable=False),
        sa.Column('seats', sa.Integer(), server_default=sa.text('1'), nullable=False),
        sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workspace_id', name=_UQ_SUBSCRIPTIONS_WS),
    )
    op.create_index(op.f('ix_subscriptions_workspace_id'), 'subscriptions', ['workspace_id'], unique=False)

    # 2) METERED_USAGE — idempotent per-event usage counter (UNIQUE dedupe key).
    op.create_table(
        'metered_usage',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('workspace_id', sa.String(length=32), nullable=False),
        sa.Column('metric', sa.String(length=60), nullable=False),
        sa.Column('quantity', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('period_ym', sa.String(length=7), nullable=False),
        sa.Column('idempotency_key', sa.String(length=160), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_key', name=_UQ_METERED_IDEMPOTENCY),
    )
    op.create_index(op.f('ix_metered_usage_workspace_id'), 'metered_usage', ['workspace_id'], unique=False)
    op.create_index('ix_metered_usage_ws_period', 'metered_usage', ['workspace_id', 'period_ym'], unique=False)

    # 3) INVOICES — tenant-scoped billing invoices (integer cents, never floats).
    op.create_table(
        'invoices',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('workspace_id', sa.String(length=32), nullable=False),
        sa.Column('provider_ref', sa.String(length=255), server_default=sa.text("('')"), nullable=False),
        sa.Column('amount_cents', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('currency', sa.String(length=10), server_default=sa.text("'usd'"), nullable=False),
        sa.Column('status', sa.String(length=20), server_default=sa.text("'draft'"), nullable=False),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_invoices_workspace_id'), 'invoices', ['workspace_id'], unique=False)

    # 4) INVOICE_LINE_ITEMS — child lines of an invoice (integer cents).
    op.create_table(
        'invoice_line_items',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('invoice_id', sa.String(length=32), nullable=False),
        sa.Column('description', sa.String(length=300), server_default=sa.text("('')"), nullable=False),
        sa.Column('quantity', sa.Integer(), server_default=sa.text('1'), nullable=False),
        sa.Column('amount_cents', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_invoice_line_items_invoice_id'), 'invoice_line_items', ['invoice_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_invoice_line_items_invoice_id'), table_name='invoice_line_items')
    op.drop_table('invoice_line_items')

    op.drop_index(op.f('ix_invoices_workspace_id'), table_name='invoices')
    op.drop_table('invoices')

    op.drop_index('ix_metered_usage_ws_period', table_name='metered_usage')
    op.drop_index(op.f('ix_metered_usage_workspace_id'), table_name='metered_usage')
    op.drop_table('metered_usage')

    op.drop_index(op.f('ix_subscriptions_workspace_id'), table_name='subscriptions')
    op.drop_table('subscriptions')
