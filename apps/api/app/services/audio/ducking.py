"""Auto-duck — sidechain gain envelope for music/SFX under dialogue.

Narration/dialogue must always sit above the mix. Given the dialogue's active
spans (from VAD/word timings — the injectable seam) and a track duration, this
computes a per-segment gain envelope for a background track: full level in the
gaps, ducked (attenuated) under speech, with attack/release ramps so the dips are
smooth rather than clicky. The compose stage renders the envelope as an FFmpeg
volume automation (or a sidechaincompress equivalent).

Pure + deterministic; no ffmpeg here.
"""

from __future__ import annotations

from dataclasses import dataclass

_DUCK_DB = -14.0       # attenuation under speech
_ATTACK_S = 0.15       # ramp down into speech
_RELEASE_S = 0.4       # ramp back up after speech


@dataclass(frozen=True)
class GainPoint:
    """A gain automation point: at ``t`` seconds the track is ``gain_db`` dB."""

    t: float
    gain_db: float


def _merge_spans(spans: list[tuple[float, float]], *, join_gap: float) -> list[tuple[float, float]]:
    """Sort + merge overlapping/near-adjacent speech spans."""
    if not spans:
        return []
    ordered = sorted((max(0.0, a), max(0.0, b)) for a, b in spans if b > a)
    merged = [ordered[0]]
    for a, b in ordered[1:]:
        la, lb = merged[-1]
        if a - lb <= join_gap:
            merged[-1] = (la, max(lb, b))
        else:
            merged.append((a, b))
    return merged


def build_duck_envelope(
    speech_spans: list[tuple[float, float]],
    duration_s: float,
    *,
    duck_db: float = _DUCK_DB,
    attack_s: float = _ATTACK_S,
    release_s: float = _RELEASE_S,
) -> list[GainPoint]:
    """Compute the background-track gain envelope over ``[0, duration_s]``.

    0 dB (full) in the gaps, ``duck_db`` under speech, with attack/release ramps.
    Adjacent speech spans closer than ``attack_s + release_s`` are merged so the
    track doesn't pump between rapid words.
    """
    if duration_s <= 0:
        return [GainPoint(0.0, 0.0)]
    spans = _merge_spans(speech_spans, join_gap=attack_s + release_s)
    points: list[GainPoint] = [GainPoint(0.0, 0.0)]
    for a, b in spans:
        duck_start = max(0.0, a - attack_s)
        duck_end = min(duration_s, b + release_s)
        points.append(GainPoint(round(duck_start, 3), 0.0))       # start ramp down
        points.append(GainPoint(round(a, 3), duck_db))            # fully ducked at speech start
        points.append(GainPoint(round(min(b, duration_s), 3), duck_db))  # hold under speech
        points.append(GainPoint(round(duck_end, 3), 0.0))         # ramp back to full
    points.append(GainPoint(round(duration_s, 3), 0.0))
    # De-dup consecutive identical points, keep monotonic time.
    cleaned: list[GainPoint] = []
    for p in points:
        if cleaned and p.t < cleaned[-1].t:
            continue
        if cleaned and p.t == cleaned[-1].t and p.gain_db == cleaned[-1].gain_db:
            continue
        cleaned.append(p)
    return cleaned
