"""Title embeddings for search and "ask this video" (MV19). Vectors are stored as JSON lists (portable);
with a few thousand titles per box the search runs in memory (numpy) well inside the target."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base


class OttTitleEmbedding(Base):
    __tablename__ = "ott_title_embeddings"

    title_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(60), nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[list] = mapped_column(JSON, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())


__all__ = ["OttTitleEmbedding"]
