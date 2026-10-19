"""OTT catalog tables (MV1, migration b1d3f5a7c9e2): channels, series, titles, rails.

A channel belongs to one creator. Titles point at the creator's own finished
render (``source_job_id``) or an uploaded long-form file (``source_key``, MV2);
nothing here stores a key, token or third-party credential.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base

STATUS_DRAFT = "draft"
STATUS_PUBLISHED = "published"
STATUS_HIDDEN = "hidden"
HIDDEN_OWNER = "owner"
HIDDEN_TAKEDOWN = "takedown"
HIDDEN_GATE = "compliance"
LAYOUTS = ("grid", "rails", "course")
KINDS = ("short", "episode", "movie", "audio")
ACCESS_TIERS = ("free", "paid")
GEO_MODES = ("all", "allow", "deny")


def _id() -> str:
    return uuid.uuid4().hex


class OttChannel(Base):
    __tablename__ = "ott_channels"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    handle: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    tagline: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    layout: Mapped[str] = mapped_column(String(16), nullable=False, default="grid")
    brand_colors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    artwork_key: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_DRAFT)
    custom_domain: Mapped[str | None] = mapped_column(String(253), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_ott_channels_user"),
        UniqueConstraint("handle", name="uq_ott_channels_handle"),
        UniqueConstraint("custom_domain", name="uq_ott_channels_domain"),
    )


class OttSeries(Base):
    __tablename__ = "ott_series"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    synopsis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    artwork_key: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OttTitle(Base):
    __tablename__ = "ott_titles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    series_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="short")
    source_job_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_key: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    synopsis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    artwork_key: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    duration_s: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    genres: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    rating: Mapped[str] = mapped_column(String(12), nullable=False, default="")
    #: Cast and crew (Wave Q QM1.5, U4): ``[{"name": ..., "role": ...}]``, shown in the studio and MRSS out.
    credits: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    available_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    available_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    access_tier: Mapped[str] = mapped_column(String(12), nullable=False, default="free")
    geo_mode: Mapped[str] = mapped_column(String(8), nullable=False, default="all")
    geo_countries: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_DRAFT)
    hidden_reason: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    package_status: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    manifest_key: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("channel_id", "source_job_id", name="uq_ott_titles_channel_job"),
        Index("ix_ott_titles_channel_status", "channel_id", "status", "position"),
        Index("ix_ott_titles_source_job", "source_job_id"),
    )


class OttCollection(Base):
    """A home rail or a collection on the storefront."""

    __tablename__ = "ott_collections"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="rail")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Wave Q QM1.2: register ``ott_upload_checks`` with every import of the OTT models
# (the publish gate reads it). Imported last: it needs OttTitle above.
from . import upload_check as _upload_check  # noqa: E402,F401
