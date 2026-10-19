"""Transcode-lane tables (MV2/MV3, migration c2e4a6b8d0f3): nodes, encode jobs, content keys."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base

LANE_BOX1 = "box1"
LANE_MAC = "mac"
LANE_BURST = "burst"
LANES = (LANE_BOX1, LANE_MAC, LANE_BURST)
QUEUED, CLAIMED, DONE, FAILED = "queued", "claimed", "done", "failed"


def _id() -> str:
    return uuid.uuid4().hex


class OttNode(Base):
    """A worker that pulls encode jobs (the owner's Mac, or a burst box)."""

    __tablename__ = "ott_nodes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    free_gb: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cores: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OttEncodeJob(Base):
    __tablename__ = "ott_encode_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    title_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    source_key: Mapped[str] = mapped_column(String(512), nullable=False)
    source_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source_height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paid_plan: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lane: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=QUEUED)
    node_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cpu_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    output_prefix: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    manifest_key: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    packager_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_ott_encode_jobs_lane_status", "lane", "status", "created_at"),)


class OttContentKey(Base):
    """The tier-1 content key of a title, encrypted at rest; released only by the key server."""

    __tablename__ = "ott_content_keys"

    title_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    key_id_hex: Mapped[str] = mapped_column(String(32), nullable=False)
    key_enc: Mapped[str] = mapped_column(Text, nullable=False)
    #: Wave Q QM1.2 (P-M7): bumped on every rotation; playlists name it and older versions are refused.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
