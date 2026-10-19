"""Activation funnel tables (migration ``e5f9b3c7d1a2``).

``FunnelEvent``: one row per (user, step), the FIRST time the user reached the
step. ``FunnelReport``: one row per ISO week the owner funnel email was sent.
Written only by :mod:`app.services.funnel`. Imported by
:mod:`app.models.db.models` so the tables register on the shared metadata.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base


class FunnelEvent(Base):
    __tablename__ = "funnel_events"

    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    step: Mapped[str] = mapped_column(String(40), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FunnelReport(Base):
    __tablename__ = "funnel_reports"

    # ISO date (YYYY-MM-DD) of the Monday the report covers.
    week_start: Mapped[str] = mapped_column(String(10), primary_key=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
