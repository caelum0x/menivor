"""Trend observation persistence (P10).

Each ingestion tick records a :class:`TrendObservation` — the raw usage-count
series plus the scored opportunity/phase (from ``trends.scoring``) — so the trends
feed can surface rising-but-not-peaked sounds/hashtags to build to now. Rows are
append-only observations (a trend is re-observed over time). Registered on
``Base.metadata`` via ``migrations/env.py``. Nullability follows the repo rule.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class TrendObservation(Base):
    """One scored observation of a trend at a point in time."""

    __tablename__ = "trend_observations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    trend_id: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), default="sound", server_default=text("'sound'"), nullable=False)
    label: Mapped[str] = mapped_column(String(200), default="", server_default=text("''"), nullable=False)
    counts: Mapped[list] = mapped_column(JSON, default=list)
    # scored fields (0..10000 basis-point ints for opportunity/saturation/velocity).
    opportunity_bps: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    saturation_bps: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    phase: Mapped[str] = mapped_column(String(20), default="emerging", server_default=text("'emerging'"), index=True, nullable=False)
    recommend: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), index=True, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )


class DiffusionForecastRecord(Base):
    """One caller-owned forecast bound to an exact durable trend observation.

    The submitted graph assumptions and deterministic model output are stored
    together, so later render/publish/performance events can reference an
    immutable forecast id instead of reconstructing or relabeling a forecast.
    """

    __tablename__ = "diffusion_forecasts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    trend_observation_id: Mapped[str] = mapped_column(
        ForeignKey("trend_observations.id"), index=True, nullable=False
    )
    content_type: Mapped[str] = mapped_column(
        String(40), default="short_video", server_default=text("'short_video'"), nullable=False
    )
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    assumptions: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
