"""beta access requests: private-beta waitlist + operator approval

Additive: one new table ``beta_access_requests`` holding a waitlist entry per
(normalised, lower-cased) email with the requester's stated use case and an
approval state. An approved email may create an account while the API is in
``internal_pilot`` launch mode (see ``app.core.launch.policy``).

New table only; nothing existing is altered.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-09-24 15:10:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "beta_access_requests",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("use_case", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("source", sa.String(length=40), server_default=sa.text("''"), nullable=False),
        # pending | approved | revoked
        sa.Column("status", sa.String(length=16), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("request_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_beta_access_requests_email"), "beta_access_requests", ["email"], unique=True)
    op.create_index(op.f("ix_beta_access_requests_status"), "beta_access_requests", ["status"], unique=False)
    op.create_index(op.f("ix_beta_access_requests_created_at"), "beta_access_requests", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_beta_access_requests_created_at"), table_name="beta_access_requests")
    op.drop_index(op.f("ix_beta_access_requests_status"), table_name="beta_access_requests")
    op.drop_index(op.f("ix_beta_access_requests_email"), table_name="beta_access_requests")
    op.drop_table("beta_access_requests")
