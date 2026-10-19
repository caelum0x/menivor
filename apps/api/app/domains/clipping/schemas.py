"""Clipping domain DTOs (boundary validation, fail-fast).

Pydantic request/response models for the long->short auto-clipping API. Input
validation happens at the system boundary per the coding-style rules: length band
sanity, count caps, and enum allow-lists are enforced here so a malformed request
is rejected with a clean 422 before any pipeline work or wallet reservation.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Hard caps so a client cannot request an unbounded amount of work.
MAX_TARGET_COUNT = 20
MIN_CLIP_LEN_S = 3
MAX_CLIP_LEN_S = 180

CaptionPreset = Literal["hormozi", "ass_karaoke"]
PublishTarget = Literal["tiktok", "instagram", "youtube", "x", "linkedin"]


class ClipJobCreateRequest(BaseModel):
    """Create a long->short auto-clipping job.

    Exactly one source must be supplied: ``source_video_key`` (an owned R2 object
    key) OR ``source_url`` (an external video URL).
    """

    model_config = ConfigDict(extra="forbid")

    source_video_key: str = Field(
        default="", max_length=1_024, description="Owned R2 object key"
    )
    source_url: str = Field(
        default="", max_length=2_048, description="Public HTTPS source video URL"
    )
    language: str = Field(default="auto", description="Source language hint")

    target_count: int = Field(
        default=3, ge=1, le=MAX_TARGET_COUNT, description="Max clips to produce"
    )
    min_len_s: int = Field(default=15, ge=MIN_CLIP_LEN_S, le=MAX_CLIP_LEN_S)
    max_len_s: int = Field(default=60, ge=MIN_CLIP_LEN_S, le=MAX_CLIP_LEN_S)
    score_floor: int = Field(
        default=50, ge=0, le=100, description="Minimum virality score to keep"
    )

    captions: CaptionPreset | None = Field(
        default="hormozi", description="Caption preset, or null to skip captions"
    )
    transitions: bool = Field(
        default=True, description="Cross-fade the clips into one stitched reel"
    )
    publish_targets: tuple[PublishTarget, ...] = Field(
        default=(), description="Optional publish handoff targets"
    )

    # Wallet-funding passthrough (see domains/reels/wallet_bridge). Opt-in: a
    # signed generation quote + profile funds the job from the USD wallet.
    generation_profile_id: str = Field(default="")
    quote: dict | None = Field(default=None)
    workspace_id: str = Field(default="")

    @model_validator(mode="after")
    def _validate(self) -> "ClipJobCreateRequest":
        key = (self.source_video_key or "").strip()
        url = (self.source_url or "").strip()
        if not key and not url:
            raise ValueError("one of source_video_key or source_url is required")
        if key and url:
            raise ValueError(
                "provide only one of source_video_key or source_url, not both"
            )
        if url:
            from app.domains.clipping.external_source import (
                ExternalSourceError,
                normalize_external_source_url,
            )

            try:
                self.source_url = normalize_external_source_url(url)
            except ExternalSourceError as exc:
                raise ValueError(exc.message) from exc

            # A recognized social-platform link (YouTube/TikTok/Vimeo/Twitch/X)
            # is ingested via yt_dlp, but only when the operator has opened that
            # path. Reject it here — at request time — so a disabled deployment
            # never creates a Job and reserves wallet funds only to die mid-worker
            # (raw-file URLs stay allowed; their content-type is checked in-worker).
            from app.domains.clipping.platform_source import (
                platform_ingest_enabled,
                recognize_platform,
            )

            if (
                recognize_platform(self.source_url) is not None
                and not platform_ingest_enabled()
            ):
                raise ValueError(
                    "platform link ingestion is not enabled for this deployment"
                )
        if self.min_len_s > self.max_len_s:
            raise ValueError(
                f"min_len_s ({self.min_len_s}) must not exceed max_len_s "
                f"({self.max_len_s})"
            )
        return self


class ClipResponse(BaseModel):
    """A single produced short clip."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    clip_job_id: str = ""
    start_s: float = 0.0
    end_s: float = 0.0
    length_s: float = 0.0
    score: int = 0
    title: str = ""
    hook: str = ""
    transcript: str = ""
    reason: str = ""
    aspect: str = "9:16"
    result_key: str = ""
    status: str = "draft"


class ClipJobResponse(BaseModel):
    """A clipping job's status envelope."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    state: str = "created"
    progress: int = 0
    language: str = "auto"
    target_count: int = 0
    clip_count: int = 0
    stitched_key: str = ""
    error: str = ""
    correlation_id: str = ""


class ClipListResponse(BaseModel):
    """A list of a job's produced clips."""

    model_config = ConfigDict(extra="allow")

    clips: list[ClipResponse] = Field(default_factory=list)
