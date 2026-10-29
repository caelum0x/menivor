"""scheduler_connections: per-user Buffer and Typefully API keys

Revision ID: f8b0d2e4a6c1
Revises: c6e8a0b2d4f6
Create Date: 2026-10-29 21:30:00.000000+00:00

The plaintext key is never stored. ``encrypted_secret`` is a Fernet blob
(SOCIAL_TOKEN_KEY, app.services.crypto_tokens). ``key_hint`` is a display suffix.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8b0d2e4a6c1"
down_revision: Union[str, None] = "c6e8a0b2d4f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scheduler_connections",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("key_hint", sa.String(length=16), server_default=sa.text("('')"), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "provider", name="uq_scheduler_connection_user_provider"),
    )
    op.create_index(op.f("ix_scheduler_connections_user_id"), "scheduler_connections", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_scheduler_connections_user_id"), table_name="scheduler_connections")
    op.drop_table("scheduler_connections")
