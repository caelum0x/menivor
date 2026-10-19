"""access & governance: users.is_staff + append-only audit_log

Revision ID: e5f2a9c74b13
Revises: d4e8c1b9f6a2
Create Date: 2026-08-13 14:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f2a9c74b13'
down_revision: Union[str, None] = 'd4e8c1b9f6a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Explicit name so the composite index is addressable in ``downgrade`` and
# portable across SQLite (tests) and Postgres/Neon (prod).
_IX_AUDIT_WS_CREATED = "ix_audit_log_workspace_id_created_at"


def upgrade() -> None:
    # Enterprise Access & Governance (Epic 1).
    #
    # 1) PLATFORM-ADMIN flag on ``users``: ``is_staff`` marks a ReelForge staff
    #    operator who may reach the hard-gated platform-admin surface
    #    (cross-tenant listing + impersonation). It is additive + NOT NULL with a
    #    ``server_default`` of '0' so the ADD COLUMN is safe on an
    #    already-populated users table (every existing row backfills to a
    #    NON-staff account) and existing rows / prior tests are unaffected.
    #    SQLite cannot ALTER TABLE ADD COLUMN with a non-constant default, so the
    #    column is added via batch mode (copy-and-move on SQLite, a plain ALTER
    #    on Postgres). The per-workspace role vocabulary expands to
    #    owner|admin|editor|viewer|billing but needs NO DDL — the existing
    #    ``workspace_members.role`` String(20) already accommodates every token.
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_staff",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )

    # 2) APPEND-ONLY AUDIT TRAIL: a brand-new ``audit_log`` table. Rows are only
    #    ever INSERTed and read (there is deliberately no update/delete API), so
    #    the trail is tamper-evident. ``workspace_id`` is NULLABLE (a
    #    platform-level action may leave it NULL); the opaque JSON column is named
    #    ``metadata`` (the ORM attribute is ``meta`` because ``metadata`` is
    #    reserved on the declarative Base). A composite ``(workspace_id,
    #    created_at)`` index backs the hot tenant-scoped, newest-first listing;
    #    ``actor_user_id`` is indexed for actor-scoped review. A brand-new table,
    #    so the CREATE is safe on an already-populated database and existing rows
    #    / prior tests are unaffected.
    op.create_table(
        "audit_log",
        sa.Column(
            "id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True, nullable=False,
        ),
        sa.Column("workspace_id", sa.String(length=32), nullable=True),
        sa.Column("actor_user_id", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column(
            "target_type",
            sa.String(length=80),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_audit_log_actor_user_id"),
        "audit_log",
        ["actor_user_id"],
        unique=False,
    )
    op.create_index(
        _IX_AUDIT_WS_CREATED,
        "audit_log",
        ["workspace_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(_IX_AUDIT_WS_CREATED, table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_actor_user_id"), table_name="audit_log")
    op.drop_table("audit_log")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("is_staff")
