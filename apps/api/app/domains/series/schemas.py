"""Clipfarm (unattended channel-runner) HTTP DTOs + public view builders.

Request models for the read+trigger endpoints exposed by
:mod:`app.domains.series.router`, plus typed ``_view`` builders that mirror the
ORM rows (:class:`ChannelRun` / :class:`ChannelClip`) into the JSON ``data``
payload the mobile Clipfarm console renders. Responses ride the shared MPT
envelope, so these describe the ``data`` payload only.

The request models intentionally mirror :class:`ChannelRunConfig`'s public
surface (minus ``channel_id`` / ``user_id`` which come from the path + the
authenticated principal) so the router can build a config without duplicating
field knowledge.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SourceItemIn(BaseModel):
    """One source row expanded into a narration script by the runner."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", description="Optional headline for the item")
    url: str = Field(default="", description="Optional source URL")
    body: str = Field(default="", description="Narration body text")


class RunChannelRequest(BaseModel):
    """Trigger one unattended render pass over an inline source list.

    Mirrors the publicly-configurable surface of ``ChannelRunConfig``; the
    ``channel_id`` comes from the path and ``user_id`` from the caller.
    """

    model_config = ConfigDict(extra="forbid")

    source_items: list[SourceItemIn] = Field(
        default_factory=list, description="Inline source rows to expand + render"
    )
    hooks: list[str] = Field(default_factory=list)
    aspects: list[str] = Field(default_factory=list)
    accounts: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(
        default_factory=list, description="Cross-post targets (publish only)"
    )
    subject: str = Field(default="")
    voice_id: str | None = Field(default=None)
    template_slug: str = Field(default="")
    max_words: int | None = Field(default=None, ge=1, le=1000)
    max_per_account: int | None = Field(
        default=None, ge=0, description="Per-account daily render cap override"
    )


class ChannelCreateRequest(BaseModel):
    """Create a named channel: render matrix + source list + autorun switch."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=120)
    autorun: bool = Field(
        default=False, description="Render new source items automatically every hour"
    )
    source_items: list[SourceItemIn] = Field(default_factory=list, max_length=500)
    hooks: list[str] = Field(default_factory=list)
    aspects: list[str] = Field(default_factory=list)
    accounts: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    subject: str = Field(default="")
    voice_id: str | None = Field(default=None)
    template_slug: str = Field(default="")
    max_words: int | None = Field(default=None, ge=1, le=1000)
    max_per_account: int | None = Field(default=None, ge=0)


class ChannelUpdateRequest(BaseModel):
    """Partial update of a channel (omitted fields are left unchanged)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=120)
    autorun: bool | None = None
    source_items: list[SourceItemIn] | None = Field(default=None, max_length=500)
    hooks: list[str] | None = None
    aspects: list[str] | None = None
    accounts: list[str] | None = None
    platforms: list[str] | None = None
    subject: str | None = None
    voice_id: str | None = None
    template_slug: str | None = None
    max_words: int | None = Field(default=None, ge=1, le=1000)
    max_per_account: int | None = Field(default=None, ge=0)


class ScheduleChannelRequest(BaseModel):
    """Trigger one publish-pacing pass over a channel's COMPLETE clips.

    ``platforms`` seeds the cross-post targets for clips whose stored platform is
    blank (mirrors the runner's fallback to ``config.platforms[0]``).
    """

    model_config = ConfigDict(extra="forbid")

    platforms: list[str] = Field(default_factory=list)
    accounts: list[str] = Field(default_factory=list)


def _iso(value: Any) -> str | None:
    """Serialize a datetime to ISO-8601, or ``None`` when absent."""
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def run_view(run: Any) -> dict:
    """Public view of one ``channel_runs`` row (run bookkeeping)."""
    return {
        "id": getattr(run, "id", ""),
        "channel_id": getattr(run, "channel_id", ""),
        "user_id": getattr(run, "user_id", ""),
        "params": dict(getattr(run, "params", {}) or {}),
        "created_at": _iso(getattr(run, "created_at", None)),
    }


def clip_view(clip: Any) -> dict:
    """Public view of one ``channel_clips`` row (pacing / pending publish)."""
    return {
        "id": getattr(clip, "id", ""),
        "channel_id": getattr(clip, "channel_id", ""),
        "run_id": getattr(clip, "run_id", ""),
        "spec_hash": getattr(clip, "spec_hash", ""),
        "job_id": getattr(clip, "job_id", ""),
        "account": getattr(clip, "account", "") or "",
        "platform": getattr(clip, "platform", "") or "",
        "status": getattr(clip, "status", ""),
        "scheduled_publish_id": getattr(clip, "scheduled_publish_id", None),
        "created_at": _iso(getattr(clip, "created_at", None)),
    }


__all__ = [
    "SourceItemIn",
    "RunChannelRequest",
    "ScheduleChannelRequest",
    "run_view",
    "clip_view",
]
