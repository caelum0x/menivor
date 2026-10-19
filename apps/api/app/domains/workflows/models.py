"""Workflow canvas tables (migration ``b2d4f6a8c0e1``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import models as _core_models  # noqa: F401  (registers users)
from app.models.db.base import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class AgentWorkflow(Base):
    __tablename__ = "agent_workflows"
    __table_args__ = (Index("ix_agent_workflows_due", "schedule_enabled", "next_run_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    space_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    graph: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sql_text("false"))
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0=Monday; NULL = daily
    hour: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("9"))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(),
                                                 onupdate=func.now())


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("agent_workflows.id", ondelete="CASCADE"), index=True,
                                             nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, server_default="manual")
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="running")
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    error: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


__all__ = ["AgentWorkflow", "WorkflowRun"]
