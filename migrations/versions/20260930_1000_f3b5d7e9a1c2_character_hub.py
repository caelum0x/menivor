"""My characters and brands: ``character_hub_profiles``, ``character_identity_scores`` (Wave P PM1.4, MH4)

A profile row records what kind of character it is (an original narrator or
your own face) and, for a real face, the consent phrase result and the
Identity Lock passport. A score row records one render's appearance
similarity to the character's reference. Purely additive and idempotent.

Revision ID: f3b5d7e9a1c2
Revises: e2a4c6d8f0b1
Create Date: 2026-09-30 10:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f3b5d7e9a1c2'
down_revision: Union[str, None] = 'e2a4c6d8f0b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    tables = _tables()
    if "character_hub_profiles" not in tables:
        op.create_table(
            "character_hub_profiles",
            sa.Column("character_id", sa.String(length=32), nullable=False),
            sa.Column("user_id", sa.String(length=32), nullable=False),
            sa.Column("kind", sa.String(length=20), nullable=False),
            sa.Column("narrator_id", sa.String(length=40), nullable=False, server_default=""),
            sa.Column("consent_verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("consent_words_heard", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("consent_words_total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("passport_id", sa.String(length=80), nullable=False, server_default=""),
            sa.Column("passport_version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.PrimaryKeyConstraint("character_id"),
        )
    if "ix_character_hub_profiles_user_id" not in _indexes("character_hub_profiles"):
        op.create_index("ix_character_hub_profiles_user_id", "character_hub_profiles", ["user_id"])
    if "character_identity_scores" not in tables:
        op.create_table(
            "character_identity_scores",
            sa.Column("id", sa.String(length=32), nullable=False),
            sa.Column("character_id", sa.String(length=32), nullable=False),
            sa.Column("user_id", sa.String(length=32), nullable=False),
            sa.Column("job_id", sa.String(length=32), nullable=False),
            sa.Column("preset_id", sa.String(length=80), nullable=False, server_default=""),
            sa.Column("model", sa.String(length=80), nullable=False, server_default=""),
            sa.Column("score", sa.Float(), nullable=False),
            sa.Column("method", sa.String(length=40), nullable=False, server_default="appearance-v1"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    if "ix_character_identity_scores_character_id" not in _indexes("character_identity_scores"):
        op.create_index("ix_character_identity_scores_character_id", "character_identity_scores", ["character_id"])


def downgrade() -> None:
    tables = _tables()
    if "character_identity_scores" in tables:
        op.drop_table("character_identity_scores")
    if "character_hub_profiles" in tables:
        op.drop_table("character_hub_profiles")
