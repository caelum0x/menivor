"""Competitor tracker tables (migration ``b2d4f6a8c0e1``).

* :class:`CompetitorBrand` - a brand the user tracks: Meta page ids, TikTok
  advertiser ids and/or search terms, and the countries to query.
* :class:`CompetitorAd` - one ad seen in an official ad library, normalized.
  ``UNIQUE(brand_id, source, external_id)``; ``is_new`` marks ads first seen on
  the latest refresh until the alert is dismissed.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import models as _core_models  # noqa: F401  (registers users/workspaces)
from app.models.db.base import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class CompetitorBrand(Base):
    __tablename__ = "competitor_brands"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=True)
    space_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    meta_page_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    tiktok_advertiser_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    search_terms: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    countries: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CompetitorAd(Base):
    __tablename__ = "competitor_ads"
    __table_args__ = (
        UniqueConstraint("brand_id", "source", "external_id", name="uq_competitor_ads_brand_source_ext"),
        Index("ix_competitor_ads_user_new", "user_id", "is_new"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    brand_id: Mapped[str] = mapped_column(ForeignKey("competitor_brands.id", ondelete="CASCADE"), index=True,
                                          nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # meta | tiktok
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    advertiser: Mapped[str] = mapped_column(String(300), nullable=False, server_default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    title: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")
    page_url: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    media_url: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    thumbnail_url: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    platforms: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    languages: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sql_text("true"))
    is_new: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sql_text("false"))
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


__all__ = ["CompetitorAd", "CompetitorBrand"]
