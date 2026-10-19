"""OTT CMS request bodies (MV1). No field accepts a key, token or credential."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ChannelUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    tagline: str | None = Field(default=None, max_length=160)
    handle: str | None = Field(default=None, max_length=40)
    layout: str | None = Field(default=None, max_length=16)
    brand_colors: list[str] | None = Field(default=None, max_length=4)


class Credit(BaseModel):
    """One cast or crew line (Wave Q QM1.5, U4)."""

    name: str = Field(..., min_length=1, max_length=80)
    role: str = Field(..., min_length=1, max_length=40)


class TitleUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    synopsis: str | None = Field(default=None, max_length=2000)
    genres: list[str] | None = Field(default=None, max_length=6)
    rating: str | None = Field(default=None, max_length=12)
    kind: str | None = Field(default=None, max_length=16)
    series_id: str | None = Field(default=None, max_length=32)
    season: int | None = Field(default=None, ge=1, le=99)
    episode: int | None = Field(default=None, ge=1, le=999)
    available_from: datetime | None = None
    available_until: datetime | None = None
    access_tier: str | None = Field(default=None, max_length=12)
    geo_mode: str | None = Field(default=None, max_length=8)
    geo_countries: list[str] | None = Field(default=None, max_length=250)
    position: int | None = Field(default=None, ge=0, le=100000)
    credits: list[Credit] | None = Field(default=None, max_length=30)


class AddTitles(BaseModel):
    job_ids: list[str] = Field(..., min_length=1, max_length=50)


class SeriesCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    synopsis: str = Field("", max_length=2000)


class CollectionCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=80)
    title_ids: list[str] = Field(default_factory=list, max_length=100)


class PublishAll(BaseModel):
    limit: int = Field(12, ge=1, le=50)
