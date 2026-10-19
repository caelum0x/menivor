"""Outbox of Dodo Payments usage events (``reel.rendered``) for metered plans.

One row per metered reel render (``event_id = reel_<job_id>``, UNIQUE, which is
also Dodo's idempotency key). Rows start ``pending`` and are flushed to
``POST /events/ingest`` by :mod:`app.services.billing.dodo_usage` (immediately
after the render, then by a Celery beat sweep): transient failures (5xx / 429 /
transport) stay ``pending`` with a backoff; other 4xx become
``failed_permanent``. Imported by :mod:`app.models.db.models` so the table
registers on the shared metadata.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Integer,
    String,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base

STATUS_PENDING: str = "pending"
STATUS_SENT: str = "sent"
STATUS_FAILED: str = "failed_permanent"


class DodoUsageEvent(Base):
    """A usage event queued for (or already accepted by) Dodo Payments."""

    __tablename__ = "dodo_usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    customer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_name: Mapped[str] = mapped_column(String(80), nullable=False)
    # When the render finished (UTC); the plan-period window counts on this.
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=STATUS_PENDING, server_default=text("'pending'"), nullable=False, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(
        String(300), default="", server_default=text("''"), nullable=False
    )
    overage: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = ["DodoUsageEvent", "STATUS_FAILED", "STATUS_PENDING", "STATUS_SENT"]
