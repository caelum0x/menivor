"""workspace credits + shared presets

Revision ID: 633c3ca06e6c
Revises: c7fe3c8161bc
Create Date: 2026-08-11 21:12:52.035303+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '633c3ca06e6c'
down_revision: Union[str, None] = 'c7fe3c8161bc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Shared Workspace Credits + Brand Kits (additive; existing per-user credit
    # and preset flows are unchanged).
    #
    # ``credit_ledger.workspace_id`` (nullable, indexed, FK -> workspaces.id):
    # when set, a ledger row belongs to a workspace shared credit pool whose
    # balance is ``SUM(delta)``; when NULL it belongs to the ``user_id`` personal
    # pool. ``credit_ledger.user_id`` is relaxed to NULLable so a workspace-pool
    # row can exist without a personal owner (e.g. a system grant); every
    # pre-existing row keeps its non-null ``user_id`` and ``workspace_id`` NULL,
    # so personal balances read identically.
    #
    # ``user_presets.workspace_id`` (nullable, indexed, FK -> workspaces.id):
    # when set, a "brand kit" preset is shared to that workspace so all members
    # see it; when NULL it stays private to its owner.
    #
    # ``batch_alter_table`` (named constraints) is used so the ADD COLUMN + FK +
    # the ``user_id`` nullability change apply on Postgres/Neon *and* on the
    # SQLite verify/test engine (which cannot ADD FK / ALTER COLUMN in place).
    with op.batch_alter_table("credit_ledger", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("workspace_id", sa.String(length=32), nullable=True)
        )
        batch_op.alter_column(
            "user_id",
            existing_type=sa.String(length=32),
            nullable=True,
        )
        batch_op.create_index(
            batch_op.f("ix_credit_ledger_workspace_id"),
            ["workspace_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_credit_ledger_workspace_id_workspaces",
            "workspaces",
            ["workspace_id"],
            ["id"],
        )

    with op.batch_alter_table("user_presets", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("workspace_id", sa.String(length=32), nullable=True)
        )
        batch_op.create_index(
            batch_op.f("ix_user_presets_workspace_id"),
            ["workspace_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_user_presets_workspace_id_workspaces",
            "workspaces",
            ["workspace_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("user_presets", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_user_presets_workspace_id_workspaces", type_="foreignkey"
        )
        batch_op.drop_index(batch_op.f("ix_user_presets_workspace_id"))
        batch_op.drop_column("workspace_id")

    with op.batch_alter_table("credit_ledger", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_credit_ledger_workspace_id_workspaces", type_="foreignkey"
        )
        batch_op.drop_index(batch_op.f("ix_credit_ledger_workspace_id"))
        batch_op.alter_column(
            "user_id",
            existing_type=sa.String(length=32),
            nullable=False,
        )
        batch_op.drop_column("workspace_id")
