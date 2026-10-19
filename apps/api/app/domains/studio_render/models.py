"""Studio render rows (migration ``b2d4f6a8c0e1``).

A render is ``planned`` (priced, nothing spent) -> ``pending_approval`` (an
``approval_items`` row of source ``studio_render``) -> ``queued`` (approved:
AI-video credits debited, worker queued) -> ``running`` -> ``done`` / ``failed``
(credits refunded once) or ``rejected``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import models as _core_models  # noqa: F401  (registers users)
from app.models.db.base import Base

KIND_ACTOR_SHOT = "actor_shot"
KIND_LIPSYNC = "lipsync_translation"
KINDS = frozenset({KIND_ACTOR_SHOT, KIND_LIPSYNC})

STATUS_PLANNED = "planned"
STATUS_PENDING = "pending_approval"
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_REJECTED = "rejected"


def _uuid() -> str:
    return uuid.uuid4().hex


class StudioRender(Base):
    __tablename__ = "studio_renders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=STATUS_PLANNED)
    title: Mapped[str] = mapped_column(String(300), nullable=False, server_default="")
    plan: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    quote_usd: Mapped[float] = mapped_column(Float, nullable=False, server_default=sql_text("0"))
    credits: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    approval_item_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(),
                                                 onupdate=func.now())


__all__ = ["KINDS", "KIND_ACTOR_SHOT", "KIND_LIPSYNC", "STATUS_DONE", "STATUS_FAILED", "STATUS_PENDING",
           "STATUS_PLANNED", "STATUS_QUEUED", "STATUS_REJECTED", "STATUS_RUNNING", "StudioRender"]
