"""Ad Studio persistence: a product ad project and its rendered ad variants.

* :class:`AdStudioProject` — one product (scraped from a URL or entered
  manually), its generated ad angles, and the product images imported into the
  owner's media library (``uploads/`` keys, so they are reusable elsewhere).
* :class:`AdVariant` — one (angle x format x aspect) ad. Local FFmpeg formats
  store their MP4 in ``output_key``; UGC-avatar variants store the rendered
  background montage in ``output_key`` and link the reel job that lip-syncs the
  avatar over it via ``job_id``.

Tables are created by migration ``a7b8c9d0e1f2``. Nullability follows the repo
rule: every column has a server default or is explicitly nullable.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import models as _core_models  # noqa: F401  (registers users for the FKs)
from app.models.db.base import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class AdStudioProject(Base):
    __tablename__ = "adstudio_projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="", server_default=text("''"), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, default="", server_default=text("''"), nullable=False)
    # trendyol | amazon | shopify | generic | manual
    source: Mapped[str] = mapped_column(String(20), default="generic", server_default=text("'generic'"), nullable=False)
    language: Mapped[str] = mapped_column(String(8), default="en", server_default=text("'en'"), nullable=False)
    product: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    angles: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # [{"key": "uploads/..", "origin_url": "..", "width": int, "height": int}]
    images: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AdVariant(Base):
    __tablename__ = "adstudio_variants"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("adstudio_projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    angle_id: Mapped[str] = mapped_column(String(16), nullable=False)
    # showcase | before_after | ugc_avatar
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    aspect: Mapped[str] = mapped_column(String(8), default="9:16", server_default=text("'9:16'"), nullable=False)
    # queued | rendering | ready | submitted | done | failed
    status: Mapped[str] = mapped_column(
        String(16), default="queued", server_default=text("'queued'"), index=True, nullable=False
    )
    script: Mapped[str] = mapped_column(Text, default="", server_default=text("''"), nullable=False)
    # Snapshot of the angle + render options used, so a re-render is reproducible
    # even after the project's angles are edited.
    spec: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    output_key: Mapped[str] = mapped_column(String(512), default="", server_default=text("''"), nullable=False)
    poster_key: Mapped[str] = mapped_column(String(512), default="", server_default=text("''"), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    job_id: Mapped[str] = mapped_column(String(32), default="", server_default=text("''"), index=True, nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", server_default=text("''"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


__all__ = ["AdStudioProject", "AdVariant"]
