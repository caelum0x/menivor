"""durable idempotency keys for job creation

Revision ID: e6c4f9a12b73
Revises: d9b2c4e17f38
Create Date: 2026-08-14 03:00:00.000000+00:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6c4f9a12b73"
down_revision: Union[str, None] = "d9b2c4e17f38"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UQ_USER_KEY = "uq_job_requests_user_idempotency_key"


def upgrade() -> None:
    """Create the user-scoped uniqueness guard before any debit can occur."""
    op.create_table(
        "job_requests",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_data", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name=_UQ_USER_KEY),
    )
    op.create_index(
        op.f("ix_job_requests_user_id"), "job_requests", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_job_requests_user_id"), table_name="job_requests")
    op.drop_table("job_requests")
