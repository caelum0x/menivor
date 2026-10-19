"""Seamless-loop point finder (ASMR / loop-back genres).

Rewatch rate is weighted above likes; a frame-perfect loop inflates completion by
making the last frame flow invisibly into the first. Given per-candidate-frame
*discontinuity* scores (how different each candidate end frame is from the start
frame — computed upstream by a cheap perceptual-hash / SSIM probe, the injectable
seam), this finds the end frame that (a) is close to the target duration and
(b) minimizes the visible seam, and reports whether it clears the acceptance gate.

Pure + deterministic — the numeric probe does the pixel work; this owns the
selection policy so it is unit-testable without real video.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.loops import policy


@dataclass(frozen=True)
class LoopResult:
    """The chosen loop point + whether it is seam-free enough to ship."""

    end_frame: int
    end_s: float
    discontinuity: float          # 0 (perfect) .. 1 (hard seam)
    accepted: bool
    reason: str = ""


def find_loop_point(
    discontinuities: list[float],
    *,
    fps: float,
    target_s: float | None = None,
    min_s: float = 1.0,
    max_s: float | None = None,
    max_discontinuity: float | None = None,
) -> LoopResult:
    """Pick the best loop end frame from per-frame discontinuity scores.

    ``discontinuities[i]`` = normalized difference between frame ``i`` and frame 0
    (0 = identical). Only frames in ``[min_s, max_s]`` are candidates; the score
    balances seam quality against proximity to ``target_s`` so a slightly-worse
    seam near the target beats a marginally-better seam far from it.
    """
    if fps <= 0:
        raise ValueError("fps must be positive")
    if not discontinuities:
        raise ValueError("no candidate frames")
    cap_s = max_s if max_s is not None else policy.LOOP_MAX_DURATION_S
    gate = max_discontinuity if max_discontinuity is not None else policy.LOOP_MAX_DISCONTINUITY
    tgt = target_s if target_s is not None else cap_s

    lo = max(1, int(round(min_s * fps)))
    hi = min(len(discontinuities) - 1, int(round(cap_s * fps)))
    if hi < lo:
        hi = len(discontinuities) - 1

    best_i = lo
    best_cost = float("inf")
    for i in range(lo, hi + 1):
        seam = max(0.0, min(1.0, float(discontinuities[i])))
        # Proximity penalty grows with |duration - target|, gentle vs. seam.
        dur = i / fps
        proximity = abs(dur - tgt) / max(tgt, 1e-6)
        cost = seam + 0.15 * proximity
        if cost < best_cost:
            best_cost = cost
            best_i = i

    seam = max(0.0, min(1.0, float(discontinuities[best_i])))
    accepted = seam <= gate
    return LoopResult(
        end_frame=best_i,
        end_s=round(best_i / fps, 3),
        discontinuity=round(seam, 4),
        accepted=accepted,
        reason="" if accepted else f"seam {seam:.3f} exceeds gate {gate:.3f}; not seamless",
    )
