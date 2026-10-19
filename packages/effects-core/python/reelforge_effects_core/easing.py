"""Pure easing + deterministic-noise primitives shared by every kernel.

Everything here is **pure polynomial / integer** math (no ``sin``/``pow``/float
transcendentals) so the TypeScript and Python ports are bit-identical — the whole
point of ``effects-core`` is that the preview UI and the render executor apply the
same numbers. Mirrors ``packages/effects-core/src/keyframe.ts`` + ``curve.ts``.
"""

from __future__ import annotations


def clamp01(t: float) -> float:
    return 0.0 if t < 0.0 else 1.0 if t > 1.0 else t


def linear(t: float) -> float:
    return clamp01(t)


def ease_in_out(t: float) -> float:
    """Quadratic ease-in-out on [0,1]."""
    t = clamp01(t)
    if t < 0.5:
        return 2.0 * t * t
    u = 1.0 - t
    return 1.0 - 2.0 * u * u


def peak(t: float) -> float:
    """Parabola peaking at 1.0 at t=0.5, 0.0 at the ends (mid-emphasis)."""
    t = clamp01(t)
    return 4.0 * t * (1.0 - t)


_HASH = 2654435761  # Knuth multiplicative hash constant
_MOD = 4294967296  # 2**32


def noise1(n: int, seed: int = 0) -> float:
    """Deterministic pseudo-noise in [-1, 1] from an integer step + seed.

    Pure 32-bit integer arithmetic → identical in JS (values stay < 2**53) and
    Python. Used for handheld/shake jitter so previews are reproducible.
    """
    h = ((int(n) + int(seed)) * _HASH) % _MOD
    return (h / _MOD) * 2.0 - 1.0
