"""AI-film project persistence (P9).

A :class:`FilmProject` is a character-consistent multi-shot film; its
:class:`FilmShot`s carry the identity-locked prompt + seed + per-shot render state
(each shot is an async generation job that advances independently). Created from a
``film.orchestrator.FilmPlan``. Registered on ``Base.metadata`` via
``migrations/env.py``. Nullability follows the repo rule.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class FilmProject(Base):
    """A multi-shot AI film owned by a creator."""

    __tablename__ = "film_projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="", server_default=text("''"), nullable=False)
    character_id: Mapped[str] = mapped_column(String(32), default="", server_default=text("''"), nullable=False)
    total_runtime_s: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    shot_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    # planned | rendering | shots_ready | exporting | exported | failed
    # (legacy rows may still read ``assembled`` == shots_ready)
    status: Mapped[str] = mapped_column(
        String(20), default="planned", server_default=text("'planned'"), index=True, nullable=False
    )
    # Final stitched export: '' (never) | queued | running | done | failed.
    export_state: Mapped[str] = mapped_column(
        String(20), default="", server_default=text("''"), nullable=False
    )
    export_error: Mapped[str] = mapped_column(Text, default="", server_default=text("''"), nullable=False)
    # Private R2 key of the stitched MP4 (presigned on read).
    final_key: Mapped[str] = mapped_column(String(512), default="", server_default=text("''"), nullable=False)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class FilmShot(Base):
    """One shot in a film project with its locked prompt + render state."""

    __tablename__ = "film_shots"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("film_projects.id"), index=True, nullable=False)
    shot_key: Mapped[str] = mapped_column(String(64), nullable=False)  # storyboard shot id
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(30), default="", server_default=text("''"), nullable=False)
    camera_motion: Mapped[str] = mapped_column(String(40), default="none", server_default=text("'none'"), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, default="", server_default=text("''"), nullable=False)
    negative_prompt: Mapped[str] = mapped_column(Text, default="", server_default=text("''"), nullable=False)
    seed: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    render_job_id: Mapped[str] = mapped_column(String(64), default="", server_default=text("''"), nullable=False)
    # pending | rendering | done | failed
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default=text("'pending'"), index=True, nullable=False
    )
