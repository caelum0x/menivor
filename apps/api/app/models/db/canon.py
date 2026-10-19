"""Canon persistence — a locked brand/character "book" + its immutable history.

Two tables mirror the ``characters`` split (a mutable owned header row + a
content-hash lock) but add EXPLICIT version retention instead of overwrite:

* ``canons`` — a mutable, user-owned header pointing at the *active* locked
  version (``current_canon_hash`` / ``current_version``) for O(index)
  verify/dedupe. May optionally bind a Wave-4 character.
* ``canon_versions`` — an APPEND-ONLY chain of immutable snapshots. Each row is
  the exact ``CanonValues`` payload that was hashed plus its content address;
  rows are never UPDATEd (no ``updated_at``), so any historical asset stays
  verifiable and regeneratable forever.

``canon_hash`` is ``String(80)`` — it safely holds ``"cv1|"`` + 64 hex = 68
chars (the existing ``characters.identity_key String(64)`` is under-sized for
its own ``"v2|"`` + 64 hex = 67-char keys; canon avoids that latent bug).

Registered on ``Base.metadata`` via ``migrations/env.py``. Additive ADD TABLE
with ``server_default`` discipline like ``models.py`` so a migration is safe on
a populated DB.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class Canon(Base):
    """Mutable, owned header pointing at the active locked version."""

    __tablename__ = "canons"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # A canon MAY bind a Wave-4 character (its identity_key is folded into values).
    character_id: Mapped[str | None] = mapped_column(
        ForeignKey("characters.id"), nullable=True
    )
    # Active locked version — indexed for O(index) verify/dedupe.
    current_canon_hash: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    current_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CanonVersion(Base):
    """Append-only, immutable snapshot of one locked canon version.

    Rows are never UPDATEd — a change locks a NEW row with the next version — so
    there is deliberately no ``updated_at``.
    """

    __tablename__ = "canon_versions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    canon_id: Mapped[str] = mapped_column(ForeignKey("canons.id"), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)  # monotonic per canon
    # Content address of ``values``; indexed for O(index) provenance lookups.
    canon_hash: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    # The exact CanonValues payload that was hashed (integrity recompute + regen).
    values: Mapped[dict] = mapped_column(JSON, nullable=False)
    # The folded identity component, for cross-checking the bound character.
    character_identity_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    locked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("canon_id", "version", name="uq_canon_versions_canon_version"),
    )
