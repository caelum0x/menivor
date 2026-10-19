"""Public DTOs for editor export commands (single-trim + timeline EDL)."""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EditorExportRequest(BaseModel):
    """Create an exact cut of a completed, caller-owned reel."""

    in_point: float = Field(ge=0, le=21_600, description="Inclusive start in seconds")
    out_point: float = Field(gt=0, le=21_600, description="Exclusive end in seconds")

    @model_validator(mode="after")
    def validate_range(self):
        if self.out_point - self.in_point < 0.1:
            raise ValueError("the selected range must be at least 0.1 seconds")
        return self


class TimelineSegmentInput(BaseModel):
    """One source trim on the timeline (segments may reuse source ranges)."""

    model_config = ConfigDict(extra="forbid")

    source_in: float = Field(ge=0, le=21_600)
    source_out: float = Field(gt=0, le=21_600)
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    caption: str | None = Field(default=None, max_length=200)


class TextOverlayInput(BaseModel):
    """A time-anchored text overlay over the produced output."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=200)
    start_s: float = Field(ge=0, le=21_600)
    end_s: float = Field(gt=0, le=21_600)
    position: str = Field(default="bottom", pattern="^(top|center|bottom)$")


class MusicTrackInput(BaseModel):
    """A curated background-music track mixed under the produced output.

    ``music_id`` is a slug from the deployment catalog (``GET /catalog/music``);
    it is validated for shape here (the same ``[a-z0-9-]`` slug the catalog can
    mint) and resolved to a real file at render time. ``volume`` is a linear mix
    gain (``1.0`` = unity); the renderer degrades to no music for an unknown id.
    """

    model_config = ConfigDict(extra="forbid")

    music_id: str = Field(min_length=1, max_length=128)
    volume: float = Field(default=1.0, ge=0.0, le=2.0)

    @field_validator("music_id")
    @classmethod
    def validate_music_id(cls, value: str) -> str:
        import re

        slug = value.strip()
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            raise ValueError(
                "invalid music_id; expected a lowercase '[a-z0-9-]' track slug "
                "(see GET /api/v1/catalog/music)"
            )
        return slug


class TimelineExportRequest(BaseModel):
    """A multi-segment, caption + overlay export (OpenCut-style EDL)."""

    model_config = ConfigDict(extra="forbid")

    segments: list[TimelineSegmentInput] = Field(min_length=1, max_length=200)
    overlays: list[TextOverlayInput] = Field(default_factory=list, max_length=50)
    music: MusicTrackInput | None = Field(default=None)


__all__ = [
    "EditorExportRequest",
    "TimelineSegmentInput",
    "TextOverlayInput",
    "MusicTrackInput",
    "TimelineExportRequest",
]
