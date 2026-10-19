"""AI panel outputs per title (MV16): transcript, subtitles per language, chapters, metadata, dubs."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base

KINDS = ("transcript", "subtitles", "chapters", "metadata", "dub")
QUEUED, DONE, FAILED = "queued", "done", "failed"


class OttAiOutput(Base):
    __tablename__ = "ott_ai_outputs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    title_id: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(8), nullable=False, default=QUEUED)
    key: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())

    __table_args__ = (UniqueConstraint("title_id", "kind", "language", name="uq_ott_ai_outputs_title_kind_lang"),)


__all__ = ["DONE", "FAILED", "KINDS", "OttAiOutput", "QUEUED"]
