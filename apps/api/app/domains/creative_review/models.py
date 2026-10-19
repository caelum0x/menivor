"""Creative review decisions (migration ``b2d4f6a8c0e1``).

One row per reviewed Brand Agent library item. The approval itself lives in
``approval_items`` (source ``creative_review``); this row keeps what the
approvals feed does not: the reason chip and the regenerate action.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import models as _core_models  # noqa: F401  (registers users)
from app.models.db.base import Base

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_REGENERATED = "regenerated"


def _uuid() -> str:
    return uuid.uuid4().hex


class CreativeReview(Base):
    __tablename__ = "creative_reviews"
    __table_args__ = (UniqueConstraint("library_item_id", name="uq_creative_reviews_item"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    library_item_id: Mapped[str] = mapped_column(String(32), nullable=False)
    space_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False, server_default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=STATUS_PENDING)
    reason: Mapped[str] = mapped_column(String(32), nullable=False, server_default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    regenerate_action_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


__all__ = ["CreativeReview", "STATUS_APPROVED", "STATUS_PENDING", "STATUS_REGENERATED", "STATUS_REJECTED"]
