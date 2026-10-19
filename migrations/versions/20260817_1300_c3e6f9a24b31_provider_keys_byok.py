"""byok: customer provider credentials (encrypted at rest)

Creates ``provider_keys`` (PROVIDER_MARKETPLACE_PLAN.md §4.2/§8.4): a
user/workspace-owned upstream API key stored as a Fernet ciphertext, with a
non-secret display prefix, routing priority, active/revoked status, and per-use
audit counters. The raw secret is never stored or returned.

Revision ID: c3e6f9a24b31
Revises: b2d5e8f13a20
Create Date: 2026-08-17 13:00:00.000000+00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3e6f9a24b31"
down_revision: Union[str, None] = "b2d5e8f13a20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _micros() -> sa.types.TypeEngine:
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "provider_keys",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=True),
        sa.Column("workspace_id", sa.String(length=32), nullable=True),
        sa.Column("provider_key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("key_prefix", sa.String(length=40), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column(
            "scope",
            sa.String(length=40),
            server_default=sa.text("'generation'"),
            nullable=False,
        ),
        sa.Column(
            "priority", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "use_count", _micros(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_provider_keys_user_id"), "provider_keys", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_provider_keys_workspace_id"),
        "provider_keys",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_provider_keys_provider_key"),
        "provider_keys",
        ["provider_key"],
        unique=False,
    )
    op.create_index(
        "ix_provider_keys_user_provider",
        "provider_keys",
        ["user_id", "provider_key", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_provider_keys_user_provider", table_name="provider_keys")
    op.drop_index(op.f("ix_provider_keys_provider_key"), table_name="provider_keys")
    op.drop_index(op.f("ix_provider_keys_workspace_id"), table_name="provider_keys")
    op.drop_index(op.f("ix_provider_keys_user_id"), table_name="provider_keys")
    op.drop_table("provider_keys")
