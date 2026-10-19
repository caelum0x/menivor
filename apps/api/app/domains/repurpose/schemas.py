"""Repurpose DTOs + public views."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CreateRepurposeRequest(BaseModel):
    """Start a repurpose job from an uploaded recording or an external URL."""

    model_config = ConfigDict(extra="forbid")

    source_kind: str = Field(default="upload", description="'upload' (R2 key) or 'url'")
    source_ref: str = Field(..., description="R2 object key or external video URL")
    language: str = Field(default="auto", description="Source language hint")
    title: str = Field(default="", description="Optional display title")


class TranscriptSegment(BaseModel):
    """One transcript window; ``score`` optional (the ranker fills it in)."""

    model_config = ConfigDict(extra="allow")

    start_s: int
    end_s: int
    text: str = ""
    score: int | None = None
    title: str = ""
    hook: str = ""
    reason: str = ""


class RankRequest(BaseModel):
    """Rank a job's transcript into highlight clips.

    Pass pre-scored ``segments`` for deterministic selection, or unscored
    segments to have the ranker score them. ``max_clips`` / length band /
    ``min_score`` tune the selection.
    """

    model_config = ConfigDict(extra="forbid")

    segments: list[TranscriptSegment] = Field(default_factory=list)
    max_clips: int = Field(default=5, ge=1, le=50)
    min_len_s: int = Field(default=15, ge=1)
    max_len_s: int = Field(default=60, ge=1)
    min_score: int = Field(default=50, ge=0, le=100)


def job_view(job: object) -> dict:
    created = getattr(job, "created_at", None)
    return {
        "id": getattr(job, "id", ""),
        "source_kind": getattr(job, "source_kind", ""),
        "source_ref": getattr(job, "source_ref", ""),
        "language": getattr(job, "language", "auto"),
        "status": getattr(job, "status", "created"),
        "title": getattr(job, "title", ""),
        "duration_s": int(getattr(job, "duration_s", 0) or 0),
        "clip_count": int(getattr(job, "clip_count", 0) or 0),
        "error": getattr(job, "error", ""),
        "created_at": created.isoformat() if hasattr(created, "isoformat") else None,
    }


def clip_view(clip: object) -> dict:
    return {
        "id": getattr(clip, "id", ""),
        "repurpose_job_id": getattr(clip, "repurpose_job_id", ""),
        "start_s": int(getattr(clip, "start_s", 0) or 0),
        "end_s": int(getattr(clip, "end_s", 0) or 0),
        "length_s": int(getattr(clip, "end_s", 0) or 0) - int(getattr(clip, "start_s", 0) or 0),
        "title": getattr(clip, "title", ""),
        "hook": getattr(clip, "hook", ""),
        "transcript": getattr(clip, "transcript", ""),
        "virality_score": int(getattr(clip, "virality_score", 0) or 0),
        "reason": getattr(clip, "reason", ""),
        "status": getattr(clip, "status", "suggested"),
        "reel_job_id": getattr(clip, "reel_job_id", None),
    }
