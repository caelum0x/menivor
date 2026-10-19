"""QoE beacons and hourly rollups (MV12); migration c9f1b3d5e7a0.

Numbers come only from our own player beacons: no third-party tracker. The
viewer is stored as a salted hash (never an email, IP or account id) and raw
beacons are kept 30 days; the hourly rollups keep the totals.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base

EVENTS = ("start", "heartbeat", "stall", "bitrate", "error", "end")


def _id() -> str:
    return uuid.uuid4().hex


class OttBeacon(Base):
    __tablename__ = "ott_beacons"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    title_id: Mapped[str] = mapped_column(String(32), nullable=False)
    session_id: Mapped[str] = mapped_column(String(40), nullable=False)
    viewer_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    event: Mapped[str] = mapped_column(String(12), nullable=False)
    hour: Mapped[str] = mapped_column(String(13), nullable=False)
    watched_s: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    startup_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stall_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bitrate_kbps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    device: Mapped[str] = mapped_column(String(12), nullable=False, default="web")
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="XX")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_ott_beacons_title_hour", "title_id", "hour"),
                      Index("ix_ott_beacons_received", "received_at"))


class OttQoeHourly(Base):
    __tablename__ = "ott_qoe_hourly"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    title_id: Mapped[str] = mapped_column(String(32), nullable=False)
    hour: Mapped[str] = mapped_column(String(13), nullable=False)
    plays: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    viewers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    watch_s: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    startup_p50_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    startup_p95_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stalls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stall_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    beacons: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (UniqueConstraint("title_id", "hour", name="uq_ott_qoe_hourly_title_hour"),
                      Index("ix_ott_qoe_hourly_channel_hour", "channel_id", "hour"))


__all__ = ["EVENTS", "OttBeacon", "OttQoeHourly"]
