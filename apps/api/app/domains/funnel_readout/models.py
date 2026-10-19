"""First-touch acquisition source per user (migration ``d8e1f3a5c7b9``).

One row per user, written once (first touch wins): the UTM fields and
referrer the web captured at sign-up, or a partner source (``scribase`` or
``rally``) recorded by the partner launch-video flow. First-party only; no
third-party tracker.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base


class FunnelAttribution(Base):
    __tablename__ = "funnel_attribution"

    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    utm_source: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    utm_medium: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    utm_campaign: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    referrer: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
