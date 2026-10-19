"""Premium credit ledger: ``premium_credit_ledger``

Separate append-only balances for premium voice credits and AI-video credits,
so a standard reel credit never pays for ElevenLabs or AI-video/presenter
provider calls. Purely additive.

Revision ID: b7d2e4f6a8c1
Revises: a1c7e3f9b5d2
Create Date: 2026-09-28 09:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b7d2e4f6a8c1'
down_revision: Union[str, None] = 'a1c7e3f9b5d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "premium_credit_ledger",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=80), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=True),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_premium_credit_ledger_user_id", "premium_credit_ledger", ["user_id"])
    op.create_index("ix_premium_credit_ledger_job_id", "premium_credit_ledger", ["job_id"])
    op.create_index("ix_premium_credit_ledger_user_kind", "premium_credit_ledger", ["user_id", "kind"])


def downgrade() -> None:
    op.drop_index("ix_premium_credit_ledger_user_kind", table_name="premium_credit_ledger")
    op.drop_index("ix_premium_credit_ledger_job_id", table_name="premium_credit_ledger")
    op.drop_index("ix_premium_credit_ledger_user_id", table_name="premium_credit_ledger")
    op.drop_table("premium_credit_ledger")
