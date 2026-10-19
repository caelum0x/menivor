"""Clone brief schema: what we learned from the winning ad (structure only, never its assets)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

ShotType = Literal["talking", "reaction", "insert", "establishing", "product_card", "text_card"]
Framing = Literal["close", "medium", "wide", "unknown"]
CameraMove = Literal["static", "push_in", "pull_out", "pan", "handheld", "unknown"]
HookPattern = Literal["price_shock", "question", "pov", "bold_claim", "list", "statement"]
Speaker = Literal["narrator", "on_camera", "none"]

MAX_BEATS = 40
MAX_TEXT = 300


class Beat(BaseModel):
    index: int = Field(ge=0)
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)
    shot_type: ShotType = "talking"
    framing: Framing = "unknown"
    camera_move: CameraMove = "unknown"
    speaker: Speaker = "none"
    # What the source SAYS / SHOWS here, for analysis only. Plans never copy it verbatim (ipguard).
    line: str = Field("", max_length=MAX_TEXT)
    on_screen_text: str = Field("", max_length=MAX_TEXT)
    role: str = Field("", max_length=40)  # hook / setup / escalation / turn / payoff / cta

    @property
    def duration_s(self) -> float:
        return round(self.end_s - self.start_s, 3)

    @model_validator(mode="after")
    def _order(self) -> "Beat":
        if self.end_s <= self.start_s:
            raise ValueError("beat end_s must be after start_s")
        return self


class Hook(BaseModel):
    end_s: float = Field(gt=0, le=3.5)
    pattern: HookPattern = "statement"
    summary: str = Field("", max_length=MAX_TEXT)  # e.g. "price complaint caption over a deadpan close-up"
    framing: Framing = "unknown"


class Pacing(BaseModel):
    shot_count: int = Field(ge=1)
    avg_shot_s: float = Field(gt=0)
    cuts_per_10s: float = Field(ge=0)
    beat_count: int = Field(ge=1)
    avg_beat_s: float = Field(gt=0)
    music_bpm: float | None = None
    onsets_s: list[float] = Field(default_factory=list)


class CaptionStyle(BaseModel):
    present: bool = False
    position: Literal["top", "middle", "bottom", "none"] = "none"
    case: Literal["lower", "sentence", "upper", "mixed", "none"] = "none"
    words_per_caption: float = 0.0
    burned_in: bool = False


class SourceInfo(BaseModel):
    url: str = Field(max_length=500)
    platform: str = Field(max_length=20)
    source_ref: str = Field(max_length=120)
    duration_s: float = Field(gt=0)
    width: int = Field(ge=0)
    height: int = Field(ge=0)
    language: str = Field("en", max_length=12)
    # Names that must never appear in our plan (uploader, brand on the card, etc.).
    avoid_terms: list[str] = Field(default_factory=list)


class CloneBrief(BaseModel):
    version: Literal[1] = 1
    source: SourceInfo
    hook: Hook
    beats: list[Beat] = Field(min_length=1, max_length=MAX_BEATS)
    pacing: Pacing
    caption_style: CaptionStyle
    transcript: str = Field("", max_length=4000)
    setting: str = Field("", max_length=200)
    keeps: list[str] = Field(default_factory=lambda: ["hook", "shot structure", "pacing"])
    analysis: Literal["heuristic", "llm"] = "heuristic"
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _beats_ordered(self) -> "CloneBrief":
        last = -1.0
        for i, b in enumerate(self.beats):
            if b.index != i:
                raise ValueError("beats must be indexed 0..n-1 in order")
            if b.start_s < last - 1e-6:
                raise ValueError("beats must not overlap or go backwards")
            last = b.end_s
        return self
