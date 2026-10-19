"""Character/style-lock persistence (P9 moat).

A saved :class:`Character` is the durable form of
``app.domains.characters.consistency.CharacterProfile`` — reusable across shots,
episodes, and projects so a recurring AI character stays visually identical. The
``identity_key`` (content hash of the locked descriptors) is stored so a lookup
can detect drift/duplicates. Registered on ``Base.metadata`` via
``migrations/env.py``. Nullability follows the repo rule.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class Character(Base):
    """A reusable, identity-locked character owned by a creator."""

    __tablename__ = "characters"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    descriptors: Mapped[list] = mapped_column(JSON, default=list)
    reference_images: Mapped[list] = mapped_column(JSON, default=list)
    negative: Mapped[list] = mapped_column(JSON, default=list)
    style: Mapped[str] = mapped_column(String(200), default="", server_default=text("''"), nullable=False)
    lora_ref: Mapped[str] = mapped_column(String(200), default="", server_default=text("''"), nullable=False)
    # Content hash of the locked identity (drift/dupe detection); indexed.
    identity_key: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
