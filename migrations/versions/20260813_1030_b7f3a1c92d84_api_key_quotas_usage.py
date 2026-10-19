"""per-api-key quotas + monthly usage counter

Revision ID: b7f3a1c92d84
Revises: 9c1e7a4b2f60
Create Date: 2026-08-13 10:30:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7f3a1c92d84'
down_revision: Union[str, None] = '9c1e7a4b2f60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # POWER-USER TIER per-API-key quotas + rate limits.
    #
    # 1) Two NULLABLE controls added to ``user_api_keys``. Both are ADD COLUMN
    #    ... NULL so the change is safe on an already-populated table and a key
    #    minted before this feature simply inherits the plan default:
    #      * ``rate_limit_per_min`` — max requests/minute (NULL => plan default).
    #      * ``monthly_quota``      — max requests/calendar-month (NULL => unlimited).
    #    Nullable with no server_default, mirroring the growth-referral columns —
    #    existing rows backfill to NULL, which the enforcement layer reads as
    #    "inherit the plan default / unlimited".
    op.add_column(
        'user_api_keys',
        sa.Column('rate_limit_per_min', sa.Integer(), nullable=True),
    )
    op.add_column(
        'user_api_keys',
        sa.Column('monthly_quota', sa.Integer(), nullable=True),
    )

    # 2) A brand-new ``api_key_usage`` table: one row per (api_key, calendar
    #    month) holding the request count enforced against ``monthly_quota``. A
    #    composite UNIQUE on ``(api_key_id, period_ym)`` guarantees a single
    #    counter row per month (an atomic increment updates it in place); a new
    #    month inserts a fresh row and prior months are retained for audit.
    #    ``api_key_id`` is indexed for owner-scoped usage listing; ``count``
    #    declares ``server_default`` '0' so a freshly-inserted period row is
    #    valid. A brand-new table, so the CREATE is safe on an already-populated
    #    database and existing rows / prior tests are unaffected.
    op.create_table(
        'api_key_usage',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('api_key_id', sa.String(length=32), nullable=False),
        sa.Column('period_ym', sa.String(length=7), nullable=False),
        sa.Column('count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['api_key_id'], ['user_api_keys.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('api_key_id', 'period_ym', name='uq_api_key_usage_key_period'),
    )
    op.create_index(op.f('ix_api_key_usage_api_key_id'), 'api_key_usage', ['api_key_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_api_key_usage_api_key_id'), table_name='api_key_usage')
    op.drop_table('api_key_usage')
    op.drop_column('user_api_keys', 'monthly_quota')
    op.drop_column('user_api_keys', 'rate_limit_per_min')
