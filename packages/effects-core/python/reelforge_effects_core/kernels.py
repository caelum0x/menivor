"""Camera + VFX preset kernels (Python parity of ``src/camera/*`` + ``src/vfx/*``).

Each kernel is a pure function ``apply(t, **params) -> dict`` returning the
transform / filter parameters at normalized time ``t in [0,1]``. These feed
``app/services/compose/vfx.py`` on the executor and the live preview on the
client — identical math both sides (see ``easing``). Params have defaults; the
returned dicts are the canonical kernel output compared in the golden fixtures.
"""

from __future__ import annotations

from . import easing


def _round(d: dict) -> dict:
    # Stable rounding so TS≡Python golden comparison is exact.
    return {k: round(v, 9) for k, v in d.items()}


# --- Camera -------------------------------------------------------------- #
def push_in(t: float, *, intensity: float = 0.3) -> dict:
    """Slow push-in zoom: 1.0 → 1.0+intensity, eased."""
    return _round({"zoom": 1.0 + intensity * easing.ease_in_out(t)})


def ken_burns(t: float, *, zoom: float = 0.2, pan_x: float = 0.1, pan_y: float = 0.05) -> dict:
    """Linear pan + zoom over a still."""
    return _round({"zoom": 1.0 + zoom * easing.linear(t),
                   "x": pan_x * easing.linear(t),
                   "y": pan_y * easing.linear(t)})


def handheld(t: float, *, intensity: float = 0.02, seed: int = 1) -> dict:
    """Noise-driven micro-shake (dx, dy, rotation)."""
    n = int(round(t * 1000))
    return _round({"dx": intensity * easing.noise1(n, seed),
                   "dy": intensity * easing.noise1(n, seed + 7),
                   "rot": intensity * 0.5 * easing.noise1(n, seed + 13)})


# --- VFX ----------------------------------------------------------------- #
def rgb_split(t: float, *, intensity: float = 4.0) -> dict:
    """Chromatic-aberration shift in pixels, peaking mid-clip."""
    return _round({"shift_px": intensity * easing.peak(t)})


def film_grain(t: float, *, intensity: float = 0.15, vignette: float = 0.3) -> dict:
    """Constant grain + vignette strength."""
    return _round({"grain": intensity, "vignette": vignette})


def shake(t: float, *, intensity: float = 8.0, decay: int = 3) -> dict:
    """Impact shake amplitude decaying over the clip ((1-t)^decay)."""
    amp = intensity
    u = 1.0 - easing.clamp01(t)
    for _ in range(int(decay)):
        amp *= u
    return _round({"amplitude": amp})
