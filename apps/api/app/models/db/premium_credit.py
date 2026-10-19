"""Premium credit ledger: the SKUs a standard credit never pays for.

Two kinds, each its own append-only balance (``SUM(delta)`` per user and kind):

* ``premium_voice`` - 1 credit = one reel narrated with a premium (ElevenLabs)
  voice; premium dubbing spends several.
* ``ai_video``      - 1 credit = 1 US cent of AI-video / AI-presenter value,
  spent at 3x the measured provider cost.

Kept apart from ``credit_ledger`` so the standard reel balance (and every
query that sums it) is untouched. Imported by :mod:`app.models.db.models` so
the table registers on the shared metadata.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base

KIND_PREMIUM_VOICE: str = "premium_voice"
KIND_AI_VIDEO: str = "ai_video"
KINDS: tuple[str, ...] = (KIND_PREMIUM_VOICE, KIND_AI_VIDEO)


class PremiumCreditLedger(Base):
    """Append-only premium credit ledger (one row per grant or debit)."""

    __tablename__ = "premium_credit_ledger"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    # premium_voice | ai_video
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    # purchase:<provider>:<ref> | premium_debit:<job> | premium_refund:<job> | ...
    reason: Mapped[str] = mapped_column(String(80), nullable=False)
    job_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_premium_credit_ledger_user_kind", "user_id", "kind"),)


__all__ = ["KINDS", "KIND_AI_VIDEO", "KIND_PREMIUM_VOICE", "PremiumCreditLedger"]
