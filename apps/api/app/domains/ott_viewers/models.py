"""Viewer accounts per channel (MV6) and hourly OTT usage rows (MV7); migration f6c8e0a2b4d7.

A viewer row is the pair (channel, Scribase Auth subject): the same person
signing in on two channels has two rows, so a viewer of channel A is not a
viewer of channel B until they sign in there. Deleting a viewer deletes their
watch history (``ott_watch_progress``) in the same transaction.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Index, Integer, SmallInteger, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base


def _id() -> str:
    return uuid.uuid4().hex


class OttViewer(Base):
    __tablename__ = "ott_viewers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    auth_subject: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False, default="")
    display_name: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    #: Bumped on sign-out everywhere; a session token with an older version is refused.
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("channel_id", "auth_subject", name="uq_ott_viewers_channel_subject"),
        Index("ix_ott_viewers_channel", "channel_id"),
    )


class OttWatchProgress(Base):
    """Where a viewer stopped in a title; one row per (viewer, title), read by web, mobile and TV."""

    __tablename__ = "ott_watch_progress"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    viewer_id: Mapped[str] = mapped_column(String(32), nullable=False)
    title_id: Mapped[str] = mapped_column(String(32), nullable=False)
    position_s: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    duration_s: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    device: Mapped[str] = mapped_column(String(16), nullable=False, default="web")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("viewer_id", "title_id", name="uq_ott_watch_progress_viewer_title"),
    )


class OttUsageHour(Base):
    """One meter reading for one creator and one UTC hour (MV7). Unique, so a re-run changes nothing."""

    __tablename__ = "ott_usage_hours"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    hour: Mapped[str] = mapped_column(String(13), nullable=False)  # YYYY-MM-DDTHH (UTC)
    meter: Mapped[str] = mapped_column(String(40), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    billable: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "hour", "meter", name="uq_ott_usage_hours_user_hour_meter"),
        Index("ix_ott_usage_hours_user_hour", "user_id", "hour"),
    )


class OttWatchlistItem(Base):
    """A title a viewer saved for later on one channel (Wave Q QM1.5, U37). Erased with the viewer."""

    __tablename__ = "ott_watchlist"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    viewer_id: Mapped[str] = mapped_column(String(32), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    title_id: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("viewer_id", "title_id", name="uq_ott_watchlist_viewer_title"),
        Index("ix_ott_watchlist_viewer", "viewer_id"),
    )


class OttRating(Base):
    """One to five stars from one viewer for one title (U37). Erased with the viewer."""

    __tablename__ = "ott_ratings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    viewer_id: Mapped[str] = mapped_column(String(32), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    title_id: Mapped[str] = mapped_column(String(32), nullable=False)
    stars: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("viewer_id", "title_id", name="uq_ott_ratings_viewer_title"),
        Index("ix_ott_ratings_title", "title_id"),
    )


class OttViewerPush(Base):
    """A viewer's opt-in to push on one channel: an Expo token and the topics they chose (U37)."""

    __tablename__ = "ott_viewer_push"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    viewer_id: Mapped[str] = mapped_column(String(32), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    token: Mapped[str] = mapped_column(String(200), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False, default="ios")
    topics: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("viewer_id", "token", name="uq_ott_viewer_push_viewer_token"),
        Index("ix_ott_viewer_push_channel", "channel_id"),
    )


__all__ = ["OttRating", "OttUsageHour", "OttViewer", "OttViewerPush", "OttWatchProgress", "OttWatchlistItem"]
