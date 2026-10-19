"""Pure timeline / edit-decision-list (EDL) policy for the OpenCut-style editor.

The browser editor is a non-destructive front end; the server stays
render-authoritative. A timeline is a list of source segments (trims, each with
an optional per-segment speed and caption override) plus time-anchored text
overlays. This module validates and normalizes an EDL and computes the output
duration — no DB, no render, fully unit-testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Guardrails (mirror the single-trim export bounds).
MAX_SOURCE_S = 21_600
MIN_SEGMENT_S = 0.1
MIN_SPEED = 0.25
MAX_SPEED = 4.0
MAX_SEGMENTS = 200
MAX_OVERLAYS = 50
MAX_OVERLAY_CHARS = 200
MIN_MUSIC_VOLUME = 0.0
MAX_MUSIC_VOLUME = 2.0
_POSITIONS = {"top", "center", "bottom"}
_MUSIC_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class TimelineError(ValueError):
    """Invalid timeline (surfaced by the service as a 422)."""


@dataclass(frozen=True)
class Segment:
    source_in: float
    source_out: float
    speed: float = 1.0
    caption: str | None = None

    @property
    def output_len_s(self) -> float:
        return (self.source_out - self.source_in) / self.speed


@dataclass(frozen=True)
class Overlay:
    text: str
    start_s: float
    end_s: float
    position: str = "bottom"


@dataclass(frozen=True)
class Music:
    """A curated background-music track mixed under the produced output."""

    music_id: str
    volume: float = 1.0


@dataclass(frozen=True)
class Timeline:
    segments: list[Segment]
    overlays: list[Overlay] = field(default_factory=list)
    music: Music | None = None

    @property
    def output_duration_s(self) -> float:
        return round(sum(s.output_len_s for s in self.segments), 3)


def _validate_segment(index: int, seg: Segment, *, source_duration_s: float | None) -> None:
    if seg.source_in < 0 or seg.source_out <= seg.source_in:
        raise TimelineError(f"segment {index}: out must be greater than in")
    if seg.source_out > MAX_SOURCE_S:
        raise TimelineError(f"segment {index}: exceeds the maximum source length")
    if source_duration_s is not None and seg.source_out > source_duration_s + 1e-6:
        raise TimelineError(f"segment {index}: extends past the source video")
    if (seg.source_out - seg.source_in) < MIN_SEGMENT_S:
        raise TimelineError(f"segment {index}: must be at least {MIN_SEGMENT_S}s")
    if not (MIN_SPEED <= seg.speed <= MAX_SPEED):
        raise TimelineError(
            f"segment {index}: speed must be within [{MIN_SPEED}, {MAX_SPEED}]"
        )
    if seg.caption is not None and len(seg.caption) > MAX_OVERLAY_CHARS:
        raise TimelineError(f"segment {index}: caption is too long")


def validate_timeline(timeline: Timeline, *, source_duration_s: float | None = None) -> float:
    """Validate an EDL and return its output duration (seconds).

    Raises :class:`TimelineError` for an empty/oversized timeline, an out-of-range
    segment, or an overlay that falls outside the produced output. Segments MAY
    reuse source ranges (b-roll repeats) — only per-segment bounds are enforced.
    """
    if not timeline.segments:
        raise TimelineError("a timeline needs at least one segment")
    if len(timeline.segments) > MAX_SEGMENTS:
        raise TimelineError(f"too many segments (max {MAX_SEGMENTS})")
    if len(timeline.overlays) > MAX_OVERLAYS:
        raise TimelineError(f"too many overlays (max {MAX_OVERLAYS})")

    for i, seg in enumerate(timeline.segments):
        _validate_segment(i, seg, source_duration_s=source_duration_s)

    output_duration = timeline.output_duration_s
    for j, ov in enumerate(timeline.overlays):
        if not ov.text.strip():
            raise TimelineError(f"overlay {j}: text is required")
        if len(ov.text) > MAX_OVERLAY_CHARS:
            raise TimelineError(f"overlay {j}: text is too long")
        if ov.position not in _POSITIONS:
            raise TimelineError(f"overlay {j}: position must be one of {_POSITIONS}")
        if ov.start_s < 0 or ov.end_s <= ov.start_s:
            raise TimelineError(f"overlay {j}: end must be greater than start")
        if ov.end_s > output_duration + 1e-6:
            raise TimelineError(f"overlay {j}: extends past the output ({output_duration}s)")

    if timeline.music is not None:
        music_id = str(timeline.music.music_id).strip()
        if not _MUSIC_ID_PATTERN.match(music_id):
            raise TimelineError("music: invalid track id")
        if not (MIN_MUSIC_VOLUME <= timeline.music.volume <= MAX_MUSIC_VOLUME):
            raise TimelineError(
                f"music: volume must be within [{MIN_MUSIC_VOLUME}, {MAX_MUSIC_VOLUME}]"
            )
    return output_duration


def normalize_edl(timeline: Timeline) -> dict:
    """A deterministic, JSON-safe EDL payload persisted on the export job."""
    edl: dict = {
        "segments": [
            {
                "source_in": round(float(s.source_in), 3),
                "source_out": round(float(s.source_out), 3),
                "speed": round(float(s.speed), 3),
                "caption": s.caption,
            }
            for s in timeline.segments
        ],
        "overlays": [
            {
                "text": o.text,
                "start_s": round(float(o.start_s), 3),
                "end_s": round(float(o.end_s), 3),
                "position": o.position,
            }
            for o in timeline.overlays
        ],
        "output_duration_s": timeline.output_duration_s,
    }
    if timeline.music is not None:
        edl["music"] = {
            "music_id": str(timeline.music.music_id).strip(),
            "volume": round(float(timeline.music.volume), 3),
        }
    return edl
