"""canon: hash-locked brand/character books + immutable version history

Revision ID: c9a10canonlock
Revises: wave4_char_idlock
Create Date: 2026-08-19 12:00:00.000000+00:00

Additive migration (ADD TABLE only, safe on a populated DB with server_default
discipline so autogenerate reports no drift):

* ``canons`` — mutable, owned header pointing at the active locked version.
* ``canon_versions`` — append-only immutable snapshots (UNIQUE(canon_id, version)).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9a10canonlock"
down_revision: Union[str, None] = "wave4_char_idlock"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "canons",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("character_id", sa.String(length=32), nullable=True),
        sa.Column("current_canon_hash", sa.String(length=80), nullable=False),
        sa.Column("current_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_canons_user_id"), "canons", ["user_id"], unique=False)
    op.create_index(op.f("ix_canons_current_canon_hash"), "canons",
                    ["current_canon_hash"], unique=False)
    op.create_index(op.f("ix_canons_created_at"), "canons", ["created_at"], unique=False)

    op.create_table(
        "canon_versions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("canon_id", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("canon_hash", sa.String(length=80), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("character_identity_key", sa.String(length=80), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["canon_id"], ["canons.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canon_id", "version", name="uq_canon_versions_canon_version"),
    )
    op.create_index(op.f("ix_canon_versions_canon_id"), "canon_versions",
                    ["canon_id"], unique=False)
    op.create_index(op.f("ix_canon_versions_canon_hash"), "canon_versions",
                    ["canon_hash"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_canon_versions_canon_hash"), table_name="canon_versions")
    op.drop_index(op.f("ix_canon_versions_canon_id"), table_name="canon_versions")
    op.drop_table("canon_versions")
    op.drop_index(op.f("ix_canons_created_at"), table_name="canons")
    op.drop_index(op.f("ix_canons_current_canon_hash"), table_name="canons")
    op.drop_index(op.f("ix_canons_user_id"), table_name="canons")
    op.drop_table("canons")
