"""Automatic performance tracking tables (migration ``a1c7e3f9b5d2``).

``TrackedPost`` - one row per (creator, platform, post id): a reel Menivor
published through a connected account, or a post the creator pasted a link to.
It carries the refresh schedule and the latest numbers the platform reported.

``PostSnapshot`` - append-only time series: one row per successful read of a
post's numbers. A counter the platform does not report is stored as ``NULL``
(unknown), never 0.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base

SOURCE_PUBLISHED = "published"  # posted through Menivor's connected accounts
SOURCE_LINK = "link"            # the creator pasted the post's link

STATE_TRACKING = "tracking"     # numbers are being read on a schedule
STATE_WAITING = "waiting"       # nothing read yet (just added, platform lagging)
STATE_NEEDS_ACCESS = "needs_access"  # connect / reconnect the account to read numbers
STATE_NO_STATS = "no_stats"     # the platform does not share numbers for this post
STATE_DONE = "done"             # old enough that the numbers stopped changing

COUNTERS: tuple[str, ...] = ("views", "likes", "comments", "shares", "saves")


def _uuid() -> str:
    return uuid.uuid4().hex


class TrackedPost(Base):
    __tablename__ = "tracked_posts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    job_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    external_id: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), default="", server_default=sql_text("''"), nullable=False)
    source: Mapped[str] = mapped_column(String(16), default=SOURCE_PUBLISHED,
                                        server_default=sql_text("'published'"), nullable=False)
    state: Mapped[str] = mapped_column(String(16), default=STATE_WAITING,
                                       server_default=sql_text("'waiting'"), nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    saves: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_watch_frac: Mapped[float | None] = mapped_column(Float, nullable=True)
    failures: Mapped[int] = mapped_column(Integer, default=0, server_default=sql_text("0"), nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "platform", "external_id", name="uq_tracked_posts_owner_post"),
        Index("ix_tracked_posts_next_check_at", "next_check_at"),
    )


class PostSnapshot(Base):
    __tablename__ = "post_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[str] = mapped_column(ForeignKey("tracked_posts.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    origin: Mapped[str] = mapped_column(String(16), default="platform", server_default=sql_text("'platform'"),
                                        nullable=False)
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    saves: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_watch_frac: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (Index("ix_post_snapshots_post_captured", "post_id", "captured_at"),)


__all__ = [
    "COUNTERS",
    "PostSnapshot",
    "SOURCE_LINK",
    "SOURCE_PUBLISHED",
    "STATE_DONE",
    "STATE_NEEDS_ACCESS",
    "STATE_NO_STATS",
    "STATE_TRACKING",
    "STATE_WAITING",
    "TrackedPost",
]
