"""Live streams (MV10), live chat (MV11) and linear channels (MV15); migration b8e0a2c4d6f9.

A stream key is shown to the creator once; only its SHA-256 is stored. Chat
messages keep the viewer's display name at send time; a hidden message keeps
its row (with the reason) so moderation can be audited.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base

IDLE, LIVE, ENDED = "idle", "live", "ended"


def _id() -> str:
    return uuid.uuid4().hex


class OttLiveStream(Base):
    __tablename__ = "ott_live_streams"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    path: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    access_tier: Mapped[str] = mapped_column(String(8), nullable=False, default="free")
    status: Mapped[str] = mapped_column(String(8), nullable=False, default=IDLE)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    peak_viewers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_samples: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    recordings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    vod_title_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    chat_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    slow_mode_s: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    banned_viewer_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OttChatMessage(Base):
    __tablename__ = "ott_chat_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    stream_id: Mapped[str] = mapped_column(String(32), nullable=False)
    viewer_id: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(60), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hidden_reason: Mapped[str] = mapped_column(String(16), nullable=False, default="")

    __table_args__ = (Index("ix_ott_chat_messages_stream_created", "stream_id", "created_at"),)


class OttLinearChannel(Base):
    """A FAST channel: an ordered loop of a channel's free titles with ad breaks."""

    __tablename__ = "ott_linear_channels"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    title_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    ad_break_every: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    anchor_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("slug", name="uq_ott_linear_channels_slug"),)


__all__ = ["ENDED", "IDLE", "LIVE", "OttChatMessage", "OttLinearChannel", "OttLiveStream"]
