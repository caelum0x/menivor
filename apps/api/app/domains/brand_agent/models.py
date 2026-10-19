"""Brand Agent tables (migration ``f7b9d1e3a5c8``).

* :class:`AgentBrandSpace` - one brand per space (a user may run several brands).
  ``brain_seen_version`` drives the Brain "unseen updates" badge.
* :class:`AgentBrandMemory` - versioned brand memory. Every write appends a row
  with the next ``version`` for the space (``UNIQUE(space_id, version)``); the
  current memory is the newest row per ``section``. Rows are never updated.
* :class:`AgentSession` / :class:`AgentMessage` - chat sessions and their ordered
  messages (``UNIQUE(session_id, seq)``). ``state`` holds the setup step machine.
* :class:`AgentAction` - the approval gate: anything that spends credits or
  publishes is a row here, ``pending`` until the owner approves or rejects it.
* :class:`AgentRoutine` - scheduled jobs ("3 new ad variations every Monday").
* :class:`AgentInspiration` - saved reference ads / TikTok links (feed Ad Clone).
* :class:`AgentSkill` - user-defined skills (built-ins live in code).
* :class:`AgentFolder` / :class:`AgentLibraryItem` - generated assets and folders.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import models as _core_models  # noqa: F401  (registers users/workspaces for the FKs)
from app.models.db.base import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AgentBrandSpace(Base):
    __tablename__ = "agent_brand_spaces"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    website_url: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    brain_seen_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 server_default=func.now(), onupdate=func.now())


class AgentBrandMemory(Base):
    __tablename__ = "agent_brand_memory"
    __table_args__ = (
        UniqueConstraint("space_id", "version", name="uq_agent_brand_memory_space_version"),
        Index("ix_agent_brand_memory_space_section", "space_id", "section"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(ForeignKey("agent_brand_spaces.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[str] = mapped_column(String(32), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default="agent")
    created_at: Mapped[datetime] = _created()


class AgentSession(Base):
    __tablename__ = "agent_sessions"
    __table_args__ = (Index("ix_agent_sessions_user_updated", "user_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    space_id: Mapped[str] = mapped_column(ForeignKey("agent_brand_spaces.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 server_default=func.now(), onupdate=func.now())


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    __table_args__ = (UniqueConstraint("session_id", "seq", name="uq_agent_messages_session_seq"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("agent_sessions.id"), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    card: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    chips: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    action_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = _created()


class AgentAction(Base):
    __tablename__ = "agent_actions"
    __table_args__ = (Index("ix_agent_actions_user_status", "user_id", "status"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    space_id: Mapped[str] = mapped_column(ForeignKey("agent_brand_spaces.id"), index=True, nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    routine_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    title: Mapped[str] = mapped_column(String(300), nullable=False, server_default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    credits_estimate: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = _created()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentRoutine(Base):
    __tablename__ = "agent_routines"
    __table_args__ = (Index("ix_agent_routines_due", "enabled", "next_run_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    space_id: Mapped[str] = mapped_column(ForeignKey("agent_brand_spaces.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    skill: Mapped[str] = mapped_column(String(64), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("1"))
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0=Monday; NULL = daily
    hour: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("9"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sql_text("true"))
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created()


class AgentInspiration(Base):
    __tablename__ = "agent_inspirations"
    __table_args__ = (UniqueConstraint("space_id", "url", name="uq_agent_inspirations_space_url"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    space_id: Mapped[str] = mapped_column(ForeignKey("agent_brand_spaces.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, server_default="link")
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default="user")
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False, server_default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    thumbnail_url: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = _created()


class AgentSkill(Base):
    __tablename__ = "agent_skills"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = _created()


class AgentFolder(Base):
    __tablename__ = "agent_folders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    space_id: Mapped[str] = mapped_column(ForeignKey("agent_brand_spaces.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = _created()


class AgentLibraryItem(Base):
    __tablename__ = "agent_library_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    space_id: Mapped[str] = mapped_column(ForeignKey("agent_brand_spaces.id"), nullable=False)
    folder_id: Mapped[str | None] = mapped_column(ForeignKey("agent_folders.id"), nullable=True)
    action_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    ref: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    url: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    title: Mapped[str] = mapped_column(String(300), nullable=False, server_default="")
    created_at: Mapped[datetime] = _created()


__all__ = [
    "AgentAction",
    "AgentBrandMemory",
    "AgentBrandSpace",
    "AgentFolder",
    "AgentInspiration",
    "AgentLibraryItem",
    "AgentMessage",
    "AgentRoutine",
    "AgentSession",
    "AgentSkill",
]
