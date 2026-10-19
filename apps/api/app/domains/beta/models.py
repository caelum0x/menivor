"""Private-beta waitlist persistence.

One :class:`BetaAccessRequest` per normalised email. ``status`` moves
``pending -> approved`` (operator action) and may be ``revoked``. An approved
row is what lets a brand-new account be created while the API runs in
``internal_pilot`` launch mode. Created by migration ``c9d0e1f2a3b4``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REVOKED = "revoked"
STATUSES = frozenset({STATUS_PENDING, STATUS_APPROVED, STATUS_REVOKED})


def _uuid() -> str:
    return uuid.uuid4().hex


class BetaAccessRequest(Base):
    __tablename__ = "beta_access_requests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True, nullable=False)
    use_case: Mapped[str] = mapped_column(Text, default="", server_default=text("''"), nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="", server_default=text("''"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=STATUS_PENDING, server_default=text("'pending'"), index=True, nullable=False
    )
    request_count: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
