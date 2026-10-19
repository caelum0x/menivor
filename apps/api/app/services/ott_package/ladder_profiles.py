"""The OTT bitrate ladder (MV3). One set of CMAF segments serves both HLS and DASH.

Every rung uses the same 2 s GOP (closed, no scene-cut keyframes), so segment
boundaries line up across rungs and a player can switch at any segment.
Rungs above the source height are dropped (no upscaling); the lowest rung is
always kept. Audio is one AAC stereo rendition; audio-only titles get just it.
"""

from __future__ import annotations

from dataclasses import dataclass

SEGMENT_SECONDS = 2
GOP_SECONDS = 2


@dataclass(frozen=True)
class Rung:
    name: str
    height: int
    video_kbps: int
    max_kbps: int
    profile: str = "high"


LADDER: tuple[Rung, ...] = (
    Rung("1080p", 1080, 4500, 6000),
    Rung("720p", 720, 2800, 3800),
    Rung("480p", 480, 1400, 1900, "main"),
    Rung("360p", 360, 800, 1100, "main"),
)
AUDIO_KBPS = 128


def rungs_for(source_height: int) -> tuple[Rung, ...]:
    """Rungs at or below the source height (the lowest is always kept)."""
    keep = tuple(r for r in LADDER if r.height <= max(int(source_height), 0))
    return keep or (LADDER[-1],)


def scaled_width(source_w: int, source_h: int, height: int) -> int:
    """Even width for ``height`` keeping the source aspect (vertical or landscape)."""
    width = round(int(source_w) * int(height) / max(int(source_h), 1))
    return max(2, width - width % 2)


__all__ = ["AUDIO_KBPS", "GOP_SECONDS", "LADDER", "Rung", "SEGMENT_SECONDS", "rungs_for", "scaled_width"]
