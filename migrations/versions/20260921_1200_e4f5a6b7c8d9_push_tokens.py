"""push_tokens: Expo push tokens for out-of-app render notifications

Backs the mobile push backend. The client (``POST /api/v1/me/push-tokens``)
registers one Expo push token per install, keyed by the stable SecureStore
``install_id``; the job-completion path (``app.services.notifications`` ->
``app.services.push``) looks up an owner's *active* tokens and delivers a native
push via Expo so a finished render reaches a backgrounded device.

The model is declared in ``app.models.db.models.PushToken`` and registered on
``Base.metadata`` (imported by ``migrations/env.py``), but no migration created
the table. This is a straight, additive create matching the model definition:

* ``install_id`` is UNIQUE (the UPSERT key — one row per install), so a rotated
  token refreshes the row in place instead of duplicating it.
* ``user_id`` is nullable (a token may be seen before its owner resolves) with a
  FK to ``users.id`` and an index for the owner-scoped lookup; a composite
  ``(user_id, is_active)`` index backs the hot "active tokens for this owner"
  query the send path runs.
* ``is_active`` lets a dead token (Expo ``DeviceNotRegistered``) or a
  signed-out install be flipped off without losing the install<->token history.

A brand-new table, so the CREATE is safe on an already-populated database and
existing rows / prior tests are unaffected.

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-09-21 12:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4f5a6b7c8d9'
down_revision: Union[str, None] = 'd3e4f5a6b7c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "push_tokens",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("install_id", sa.String(length=64), nullable=False),
        # Opaque ExponentPushToken[...] string (sensitive).
        sa.Column("token", sa.String(length=512), nullable=False),
        sa.Column(
            "platform",
            sa.String(length=16),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(length=32), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # UNIQUE install index — the UPSERT key (one row per install).
    op.create_index(
        op.f("ix_push_tokens_install_id"),
        "push_tokens",
        ["install_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_push_tokens_user_id"),
        "push_tokens",
        ["user_id"],
        unique=False,
    )
    # Composite index backing the hot "active tokens for this owner" lookup.
    op.create_index(
        "ix_push_tokens_user_id_is_active",
        "push_tokens",
        ["user_id", "is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_push_tokens_user_id_is_active", table_name="push_tokens")
    op.drop_index(op.f("ix_push_tokens_user_id"), table_name="push_tokens")
    op.drop_index(op.f("ix_push_tokens_install_id"), table_name="push_tokens")
    op.drop_table("push_tokens")
