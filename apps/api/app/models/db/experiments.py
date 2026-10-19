"""1-body/N-hooks A/B experiment persistence (P7).

Backs the retention flywheel's measure→winner step: an :class:`Experiment` holds
N hook :class:`ExperimentVariant`s; retention metrics are ingested per variant
(from the publishing analytics pull), then ``experiments.select_winner`` picks the
retention-weighted winner once the sample is conclusive. Registered on
``Base.metadata`` via ``migrations/env.py``. Nullability follows the repo rule.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class Experiment(Base):
    """A 1-body/N-hooks experiment for one reel body."""

    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    experiment_key: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    body_ref: Mapped[str] = mapped_column(String(120), default="", server_default=text("''"), nullable=False)
    # running | conclusive | inconclusive
    status: Mapped[str] = mapped_column(
        String(20), default="running", server_default=text("'running'"), index=True, nullable=False
    )
    winner_variant_id: Mapped[str] = mapped_column(String(32), default="", server_default=text("''"), nullable=False)
    winner_hook_ref: Mapped[str] = mapped_column(String(120), default="", server_default=text("''"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ExperimentVariant(Base):
    """One hook variant with its accumulated retention metrics."""

    __tablename__ = "experiment_variants"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"), index=True, nullable=False)
    hook_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    views: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    # NULL = not measured (no platform reported it) — distinct from a measured 0%.
    completion_rate: Mapped[float | None] = mapped_column(Float, default=None, nullable=True)
    avg_watch_frac: Mapped[float] = mapped_column(Float, default=0.0, server_default=text("0"), nullable=False)
    rewatch_rate: Mapped[float | None] = mapped_column(Float, default=None, nullable=True)
    engagement_rate: Mapped[float] = mapped_column(Float, default=0.0, server_default=text("0"), nullable=False)
