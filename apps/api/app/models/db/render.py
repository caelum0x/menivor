"""Async-GPU render job persistence (P6).

Durable record of an async render job's unified envelope (``services/render``):
which backend + workflow version served it, its envelope state + poll cursor, the
held/settled cost (integer microdollars), and the output refs. A poll worker
advances ``state`` toward a terminal value; the wallet settles/releases on the
transition (success-only billing). Import this module (done in ``migrations/env.py``
and ``models/db/__init__``) so the table registers on ``Base.metadata``.

Nullability follows the repo rule: ``Mapped[str]`` with ``default=""`` is NOT
NULL (server_default ''), timestamps are NOT NULL with a server default.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class RenderJob(Base):
    """An async GPU render job tracked through the unified envelope."""

    __tablename__ = "render_jobs"

    # 64 wide: the id is the backend spec ``job_id`` (a request correlation id
    # or a ``film-<project>-<shot>-<nonce>`` id), which can exceed a bare uuid.
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(
        String(64), default="", server_default=text("''"), nullable=False
    )
    # Who started the job: ``render`` (the /render studio) or ``film`` (a film
    # shot render). ``label`` is a short human title for history lists.
    source: Mapped[str] = mapped_column(
        String(20), default="render", server_default=text("'render'"), index=True, nullable=False
    )
    label: Mapped[str] = mapped_column(
        String(200), default="", server_default=text("''"), nullable=False
    )
    # Which backend + workflow version served this job.
    backend: Mapped[str] = mapped_column(String(40), nullable=False)
    workflow_version: Mapped[str] = mapped_column(
        String(120), default="", server_default=text("''"), nullable=False
    )
    # Unified envelope: IN_QUEUE | IN_PROGRESS | COMPLETED | FAILED | CANCELLED.
    state: Mapped[str] = mapped_column(
        String(20), default="IN_QUEUE", server_default=text("'IN_QUEUE'"),
        index=True, nullable=False,
    )
    progress: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )  # 0..100 (persisted as int; envelope carries the 0..1 float)
    # Backend job id + opaque paging state between polls.
    provider_ref: Mapped[str] = mapped_column(
        String(200), default="", server_default=text("''"), nullable=False
    )
    poll_cursor: Mapped[str] = mapped_column(
        String(500), default="", server_default=text("''"), nullable=False
    )
    # Money: held on reserve, settled to actual on COMPLETED (micros).
    held_cost_micros: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    actual_cost_micros: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    # Result output refs (R2 keys / URLs), newline-joined; empty until COMPLETED.
    output_refs: Mapped[str] = mapped_column(
        Text, default="", server_default=text("''"), nullable=False
    )
    error: Mapped[str] = mapped_column(
        Text, default="", server_default=text("''"), nullable=False
    )
    attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
