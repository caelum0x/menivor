"""Per-owner approvals feed preferences (table created by migration ``b8e4f0a2c3d5``).

``auto_sources`` lists the scanned producers the owner opted into. Capture and
store-catalog suggestions are off until the owner turns them on from the
approvals page: every finished capture or imported product would otherwise
become a pending item, which is noise for most accounts.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import models as _core_models  # noqa: F401  (registers users)
from app.models.db.base import Base


class ApprovalFeedSettings(Base):
    __tablename__ = "approval_feed_settings"

    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), primary_key=True)
    auto_sources: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
