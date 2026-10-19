"""Beat-synced cut snapping (anime/movie-edit genres).

Editors trim clips to STORY BEATS and land cuts on the audio beat, nudged -2/-3
frames so the cut reads as *on* the beat (a cut exactly on the transient feels
slightly late). Given detected beat timestamps (from an onset/tempo probe — the
seam) and desired raw cut points, this snaps each cut to the nearest beat and
applies the frame nudge.

Pure + deterministic; the audio beat detector lives elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SnappedCut:
    """A raw cut snapped to the nearest beat, with the frame nudge applied."""

    raw_s: float
    beat_s: float
    nudged_s: float
    nudge_frames: int


def _nearest_beat(t: float, beats: list[float]) -> float:
    return min(beats, key=lambda b: abs(b - t))


def snap_cuts_to_beats(
    cuts: list[float],
    beats: list[float],
    *,
    fps: float = 30.0,
    nudge_frames: int = 2,
    max_snap_s: float = 0.4,
) -> list[SnappedCut]:
    """Snap each raw cut to its nearest beat (within ``max_snap_s``) minus a nudge.

    A cut with no beat inside ``max_snap_s`` is left where it is (beat_s = raw).
    The nudge pulls the cut EARLIER by ``nudge_frames`` frames so it lands on the
    beat perceptually; the result is clamped to be non-negative and monotonic.
    """
    if fps <= 0:
        raise ValueError("fps must be positive")
    nudge_s = nudge_frames / fps
    out: list[SnappedCut] = []
    prev = 0.0
    for raw in cuts:
        if beats:
            nearest = _nearest_beat(raw, beats)
            if abs(nearest - raw) <= max_snap_s:
                beat = snapped = nearest
            else:
                beat = snapped = raw  # no beat close enough — leave the cut in place
        else:
            beat = snapped = raw
        nudged = max(prev, round(snapped - nudge_s, 4))
        out.append(
            SnappedCut(
                raw_s=round(raw, 4),
                beat_s=round(beat, 4),
                nudged_s=nudged,
                nudge_frames=nudge_frames if snapped != raw else 0,
            )
        )
        prev = nudged
    return out


def preview_beat_fits(
    cuts: list[float], beats: list[float], *, fps: float = 30.0, options: tuple[int, ...] = (2, 3, 4)
) -> dict[int, float]:
    """"Preview 3 template fits": mean snap error per nudge option (lower = tighter).

    Returns ``{nudge_frames: mean_abs_error_seconds}`` so the UI can offer the
    tightest-fitting nudge for the chosen track.
    """
    fits: dict[int, float] = {}
    for opt in options:
        snapped = snap_cuts_to_beats(cuts, beats, fps=fps, nudge_frames=opt)
        if not snapped:
            fits[opt] = 0.0
            continue
        err = sum(abs(s.nudged_s - s.beat_s) for s in snapped) / len(snapped)
        fits[opt] = round(err, 4)
    return fits
