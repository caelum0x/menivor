"""Character reference-image persistence (Wave 4 — identity lock).

A :class:`CharacterReference` binds one OWNED ``uploads/`` object (a face / body
/ outfit / pose still, or a full character sheet) to a saved
:class:`~app.models.db.characters.Character`. The bound references are the
IP-Adapter / LoRA conditioning inputs that keep a recurring AI character visually
identical across shots, and their sorted digest folds into the character's
``identity_key`` (drift/dupe detection).

Only an owned upload key is ever stored here (ownership validated at the domain
boundary via ``media.service.require_owned_asset``) — never a new upload path and
never a raw client URL (SSRF §8). Registered on ``Base.metadata`` via
``migrations/env.py`` like ``media_jobs``. Nullability follows the repo rule.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class CharacterReference(Base):
    """One owned reference image bound to a character for identity conditioning."""

    __tablename__ = "character_references"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    character_id: Mapped[str] = mapped_column(
        ForeignKey("characters.id"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    # The OWNED ``uploads/`` R2 key (ownership checked before insert).
    r2_key: Mapped[str] = mapped_column(String(512), nullable=False)
    # face | body | outfit | pose | sheet
    role: Mapped[str] = mapped_column(
        String(16), default="sheet", server_default=text("'sheet'"), nullable=False
    )
    content_type: Mapped[str] = mapped_column(
        String(80), default="", server_default=text("''"), nullable=False
    )
    width: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    height: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    # Optional precomputed identity-embedding object key (nullable — filled later).
    embedding_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
