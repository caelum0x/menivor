"""Wave 4 character identity lock: character_references + identity_key rehash

Revision ID: wave4_char_idlock
Revises: c31f3047fac6
Create Date: 2026-08-19 00:00:00.000000+00:00

Additive migration (no destructive drops):

1. Create the ``character_references`` table — one OWNED ``uploads/`` reference
   image bound to a character (face/body/outfit/pose/sheet), the IP-Adapter /
   LoRA conditioning inputs for the identity lock.
2. One-time backfill of ``characters.identity_key`` for every existing row that
   carries reference images, folding the sorted reference-key digest into the
   key behind the ``v2|`` version prefix. Image-less characters keep their v1
   (unprefixed) key untouched, so the ``ix_characters_identity_key`` index and
   ``find_duplicate`` are never orphaned by the new hashing scheme.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "wave4_char_idlock"
down_revision: Union[str, None] = "c31f3047fac6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. New table (additive, safe on a populated DB) -------------------- #
    op.create_table(
        "character_references",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("character_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("r2_key", sa.String(length=512), nullable=False),
        sa.Column("role", sa.String(length=16), server_default=sa.text("'sheet'"), nullable=False),
        sa.Column("content_type", sa.String(length=80), server_default=sa.text("''"), nullable=False),
        sa.Column("width", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("height", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("embedding_key", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_character_references_character_id"),
        "character_references",
        ["character_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_character_references_user_id"),
        "character_references",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_character_references_created_at"),
        "character_references",
        ["created_at"],
        unique=False,
    )

    # --- 2. One-time identity_key rehash (fold reference digest -> v2) ------- #
    _backfill_identity_keys()


def _backfill_identity_keys() -> None:
    """Recompute the v2 identity_key for every character that has reference images.

    Uses the SAME pure hashing algorithm as
    ``app.domains.characters.consistency`` so stored keys match runtime keys.
    Guarded so an offline/SQL-emit migration (no live bind) never blocks; the
    rehash is idempotent (re-running yields the same v2 keys).
    """
    try:
        from app.domains.characters.consistency import CharacterProfile
    except Exception:  # noqa: BLE001 - app not importable in this context; skip
        return

    bind = op.get_bind()
    if bind is None:  # offline mode — nothing to backfill
        return

    characters = sa.table(
        "characters",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("descriptors", sa.JSON),
        sa.column("reference_images", sa.JSON),
        sa.column("style", sa.String),
        sa.column("lora_ref", sa.String),
        sa.column("identity_key", sa.String),
    )
    rows = bind.execute(
        sa.select(
            characters.c.id,
            characters.c.name,
            characters.c.descriptors,
            characters.c.reference_images,
            characters.c.style,
            characters.c.lora_ref,
        )
    ).fetchall()

    for row in rows:
        reference_images = tuple(row.reference_images or ())
        if not reference_images:
            continue  # image-less rows keep their v1 key — no orphaning
        profile = CharacterProfile(
            character_id=row.id,
            name=row.name or "",
            descriptors=tuple(row.descriptors or ()),
            reference_images=reference_images,
            style=row.style or "",
            lora_ref=row.lora_ref or "",
        )
        bind.execute(
            sa.update(characters)
            .where(characters.c.id == row.id)
            .values(identity_key=profile.identity_key())
        )


def downgrade() -> None:
    # Note: the identity_key rehash is intentionally NOT reversed on downgrade —
    # the v2 keys remain valid content hashes and reversing would require the old
    # (image-excluding) algorithm; only the additive table is dropped.
    op.drop_index(
        op.f("ix_character_references_created_at"), table_name="character_references"
    )
    op.drop_index(
        op.f("ix_character_references_user_id"), table_name="character_references"
    )
    op.drop_index(
        op.f("ix_character_references_character_id"),
        table_name="character_references",
    )
    op.drop_table("character_references")
