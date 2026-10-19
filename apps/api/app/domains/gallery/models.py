"""Gallery tables (MH3): opt-in items and the remix links that count toward them."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base


def _id() -> str:
    return uuid.uuid4().hex


class GalleryItem(Base):
    """One finished output its owner chose to show. Never stores the script or references."""

    __tablename__ = "gallery_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    job_id: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    #: ``shelf:<preset id>``, ``style:<style id>`` or ``reel``.
    preset_id: Mapped[str] = mapped_column(String(80), nullable=False, default="reel")
    #: Only the whitelisted render settings (see ``service.SAFE_PARAM_KEYS``).
    safe_params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    remix_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wall_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hidden_reason: Mapped[str] = mapped_column(String(40), nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("job_id", name="uq_gallery_items_job"),
        Index("ix_gallery_items_visible", "hidden_at", "published_at"),
    )


class GalleryRemix(Base):
    """A job someone made with Recreate; counted once when it is kept."""

    __tablename__ = "gallery_remixes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    item_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    job_id: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    counted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("job_id", name="uq_gallery_remixes_job"),)
