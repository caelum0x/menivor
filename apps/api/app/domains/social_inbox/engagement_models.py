"""Engagement autopilot persistence (tables from migration ``6e135be697a8``).

* :class:`EngagementSettings` - the creator's autopilot rules per platform
  account. Off until the creator turns it on; replies need approval by default.
* :class:`EngagementAction` - every action the autopilot proposed or took
  (like, reply, hide, flag, lead) and every rule change: the approval queue
  and the audit log in one append-mostly table.
* :class:`EngagementLead` - a person whose comment or DM shows buying intent,
  routed to the Leads view.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import models as _core_models  # noqa: F401  (registers users for the FKs)
from app.models.db.base import Base

from . import models as _inbox_models  # noqa: F401  (registers social_inbox_threads for the FK)

# Reply modes.
REPLY_OFF = "off"
REPLY_APPROVE = "approve"
REPLY_AUTO = "auto"
REPLY_MODES = frozenset({REPLY_OFF, REPLY_APPROVE, REPLY_AUTO})

# Action kinds.
ACT_LIKE = "like"
ACT_REPLY = "reply"
ACT_HIDE = "hide"
ACT_FLAG = "flag"
ACT_LEAD = "lead"
ACT_SETTINGS = "settings"
ACTION_KINDS = frozenset({ACT_LIKE, ACT_REPLY, ACT_HIDE, ACT_FLAG, ACT_LEAD, ACT_SETTINGS})
# Kinds that call the platform and count toward the daily cap.
CAPPED_KINDS = frozenset({ACT_LIKE, ACT_REPLY, ACT_HIDE})

# Action statuses.
AS_PENDING = "pending_approval"
AS_QUEUED = "queued"          # claimed by a run, platform call in flight
AS_DONE = "done"
AS_REJECTED = "rejected"
AS_SKIPPED = "skipped"
AS_FAILED = "failed"
ACTION_STATUSES = frozenset({AS_PENDING, AS_QUEUED, AS_DONE, AS_REJECTED, AS_SKIPPED, AS_FAILED})

ACTOR_AUTOPILOT = "autopilot"
ACTOR_CREATOR = "creator"

# Lead statuses.
LEAD_NEW = "new"
LEAD_CONTACTED = "contacted"
LEAD_WON = "won"
LEAD_DISMISSED = "dismissed"
LEAD_STATUSES = frozenset({LEAD_NEW, LEAD_CONTACTED, LEAD_WON, LEAD_DISMISSED})

DEFAULT_DAILY_CAP = 50
MAX_DAILY_CAP = 500


def _uuid() -> str:
    return uuid.uuid4().hex


class EngagementSettings(Base):
    __tablename__ = "social_engagement_settings"
    __table_args__ = (UniqueConstraint("user_id", "platform", name="uq_social_engagement_settings_owner"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sql_text("false"), nullable=False)
    auto_like: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sql_text("true"), nullable=False)
    reply_mode: Mapped[str] = mapped_column(String(12), default=REPLY_APPROVE, server_default=sql_text("'approve'"),
                                            nullable=False)
    reply_to_questions: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sql_text("false"),
                                                     nullable=False)
    hide_spam: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sql_text("true"), nullable=False)
    hide_abuse: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sql_text("false"), nullable=False)
    route_leads: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sql_text("true"), nullable=False)
    daily_cap: Mapped[int] = mapped_column(Integer, default=DEFAULT_DAILY_CAP, server_default=sql_text("50"),
                                           nullable=False)
    blocked_words: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class EngagementAction(Base):
    __tablename__ = "social_engagement_actions"
    __table_args__ = (
        # One action of a kind per inbound message: re-runs never double-like or double-reply.
        UniqueConstraint("user_id", "thread_id", "kind", "message_key", name="uq_social_engagement_actions_once"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    thread_id: Mapped[str | None] = mapped_column(
        ForeignKey("social_inbox_threads.id", ondelete="SET NULL"), index=True, nullable=True
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str] = mapped_column(String(12), default=ACTOR_AUTOPILOT, server_default=sql_text("'autopilot'"),
                                       nullable=False)
    message_key: Mapped[str] = mapped_column(String(200), default="", server_default=sql_text("''"), nullable=False)
    label: Mapped[str] = mapped_column(String(20), default="", server_default=sql_text("''"), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    text_source: Mapped[str] = mapped_column(String(12), default="", server_default=sql_text("''"), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    author_name: Mapped[str] = mapped_column(String(200), default="", server_default=sql_text("''"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(300), default="", server_default=sql_text("''"), nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True,
                                                 nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EngagementLead(Base):
    __tablename__ = "social_engagement_leads"
    __table_args__ = (UniqueConstraint("user_id", "thread_id", name="uq_social_engagement_leads_thread"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    thread_id: Mapped[str | None] = mapped_column(
        ForeignKey("social_inbox_threads.id", ondelete="SET NULL"), index=True, nullable=True
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(12), default="dm", server_default=sql_text("'dm'"), nullable=False)
    author_name: Mapped[str] = mapped_column(String(200), default="", server_default=sql_text("''"), nullable=False)
    author_external_id: Mapped[str] = mapped_column(String(128), default="", server_default=sql_text("''"),
                                                    nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    signals: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0, server_default=sql_text("0"), nullable=False)
    status: Mapped[str] = mapped_column(String(12), default=LEAD_NEW, server_default=sql_text("'new'"), nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    permalink: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
