"""Social inbox persistence (tables created by migration ``d0e1f2a3b4c5``).

* :class:`InboxPost` - one Menivor-published post per (owner, platform, post id)
  with its poll schedule, inbox availability state and observed counts.
* :class:`InboxThread` - one top-level comment or DM conversation pulled from the
  platform, with a bounded message history and reply/done state.

Every read and write is owner-scoped by ``user_id`` in :mod:`.repository`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import models as _core_models  # noqa: F401  (registers users for the FKs)
from app.models.db.base import Base

# Post inbox states.
STATE_OK = "ok"
STATE_NOT_CONNECTED = "not_connected"
STATE_MISSING_PERMISSION = "missing_permission"
STATE_NOT_OFFERED = "not_offered"
STATE_ERROR = "error"
POST_STATES = frozenset({STATE_OK, STATE_NOT_CONNECTED, STATE_MISSING_PERMISSION, STATE_NOT_OFFERED, STATE_ERROR})

# Thread kinds + statuses.
KIND_COMMENT = "comment"
KIND_DM = "dm"
THREAD_KINDS = frozenset({KIND_COMMENT, KIND_DM})

STATUS_NEEDS_REPLY = "needs_reply"
STATUS_REPLIED = "replied"
STATUS_DONE = "done"
THREAD_STATUSES = frozenset({STATUS_NEEDS_REPLY, STATUS_REPLIED, STATUS_DONE})

# Bounded message history kept per thread (oldest dropped first).
MAX_THREAD_MESSAGES = 50


def _uuid() -> str:
    return uuid.uuid4().hex


class InboxPost(Base):
    __tablename__ = "social_inbox_posts"
    __table_args__ = (
        UniqueConstraint("user_id", "platform", "external_id", name="uq_social_inbox_posts_owner_post"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    job_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    url: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), default="", server_default=sql_text("''"), nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    inbox_state: Mapped[str] = mapped_column(
        String(24), default=STATE_OK, server_default=sql_text("'ok'"), nullable=False
    )
    state_note: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    platform_comment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    platform_like_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    platform_view_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    synced_comment_count: Mapped[int] = mapped_column(Integer, default=0, server_default=sql_text("0"), nullable=False)
    needs_reply_count: Mapped[int] = mapped_column(Integer, default=0, server_default=sql_text("0"), nullable=False)
    replied_count: Mapped[int] = mapped_column(Integer, default=0, server_default=sql_text("0"), nullable=False)
    poll_failures: Mapped[int] = mapped_column(Integer, default=0, server_default=sql_text("0"), nullable=False)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class InboxThread(Base):
    __tablename__ = "social_inbox_threads"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "platform", "kind", "external_thread_id", name="uq_social_inbox_threads_owner_thread"
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    post_id: Mapped[str | None] = mapped_column(
        ForeignKey("social_inbox_posts.id", ondelete="CASCADE"), index=True, nullable=True
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), default=KIND_COMMENT, server_default=sql_text("'comment'"), nullable=False)
    external_thread_id: Mapped[str] = mapped_column(String(160), nullable=False)
    author_name: Mapped[str] = mapped_column(String(200), default="", server_default=sql_text("''"), nullable=False)
    author_external_id: Mapped[str] = mapped_column(String(128), default="", server_default=sql_text("''"), nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    permalink: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    like_count: Mapped[int] = mapped_column(Integer, default=0, server_default=sql_text("0"), nullable=False)
    messages: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=STATUS_NEEDS_REPLY, server_default=sql_text("'needs_reply'"), nullable=False
    )
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reply_text: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    reply_external_id: Mapped[str] = mapped_column(String(160), default="", server_default=sql_text("''"), nullable=False)
    reply_via: Mapped[str] = mapped_column(String(12), default="", server_default=sql_text("''"), nullable=False)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
