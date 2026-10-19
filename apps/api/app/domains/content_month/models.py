"""Content Month persistence (tables created by migration ``c3e5a7b9d1f2``).

* :class:`ContentPlan` - one website read for one user: the site brief, the
  brand style the slides use, and when it was made.
* :class:`ContentIdea` - one post idea in a plan: its viral format, hook,
  slides / reel beats, caption, the user's swipe decision, and what has been
  rendered for it (design doc + PNG/PDF/MP4 keys for carousels, the reel job
  id for reels).

Every read and write is scoped to the owning ``user_id``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import models as _core_models  # noqa: F401  (registers users)
from app.models.db.base import Base

DECISION_PENDING = "pending"
DECISION_KEPT = "kept"
DECISION_SKIPPED = "skipped"
DECISIONS = frozenset({DECISION_PENDING, DECISION_KEPT, DECISION_SKIPPED})

RENDER_NONE = "none"
RENDER_DONE = "done"
RENDER_FAILED = "failed"
RENDER_QUEUED = "queued"  # a reel job was created; the job page tracks it


def _uuid() -> str:
    return uuid.uuid4().hex


class ContentPlan(Base):
    __tablename__ = "content_plans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(String(120), default="", server_default=sql_text("''"), nullable=False)
    brief_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    style_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ContentIdea(Base):
    __tablename__ = "content_ideas"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    plan_id: Mapped[str] = mapped_column(ForeignKey("content_plans.id", ondelete="CASCADE"), index=True,
                                         nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default=sql_text("0"), nullable=False)
    format: Mapped[str] = mapped_column(String(40), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    hook: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    slides: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    script: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    caption: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="rules", server_default=sql_text("'rules'"),
                                        nullable=False)
    decision: Mapped[str] = mapped_column(String(16), default=DECISION_PENDING,
                                          server_default=sql_text("'pending'"), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    render_status: Mapped[str] = mapped_column(String(16), default=RENDER_NONE, server_default=sql_text("'none'"),
                                               nullable=False)
    #: {"size", "design_id", "png_keys", "pdf_key", "mp4_key", "job_id", "error"}
    outputs: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
