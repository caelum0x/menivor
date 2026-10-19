"""Pure defaults + retention policy constants for the shot-template engine.

Encodes the research-backed thresholds (``docs/reelforge/vision2026``): the
first-3s hook gate, tension-bump cadence, caption safe-zones, and the standard
audio-duck gains. Kept as plain constants + tiny pure helpers so both the
compiler and the hook/retention analyzers share one source of truth.
"""

from __future__ import annotations

# Retention gates (fractions of viewers / seconds).
HOOK_WINDOW_S: float = 3.0            # the window that decides ~70% of retention
HOOK_MIN_CLEARANCE: float = 0.70      # completion of the first-3s test-audience to unlock reach
TENSION_BUMP_CADENCE_S: float = 5.0   # add a beat/tension bump at least this often in rising action
LOOP_MAX_DURATION_S: float = 6.0      # seamless-loop genres cap (ASMR ~5s)

# Caption safe-zone defaults per platform surface (fraction of frame height / Y).
CAPTION_SAFEZONE: dict[str, dict[str, float]] = {
    "tiktok": {"y_frac": 0.63, "height_frac": 0.16},
    "reels": {"y_frac": 0.62, "height_frac": 0.14},
    "shorts": {"y_frac": 0.64, "height_frac": 0.09},
}
DEFAULT_SURFACE: str = "tiktok"

# Hormozi highlight palette (the near-universal caption look).
HORMOZI_HIGHLIGHT: str = "#FFD93D"

# Audio-bus gains (dB) — narration/dialogue is always mixed above the rest.
FOREGROUND_GAIN_DB: float = 0.0
DUCKED_BGM_GAIN_DB: float = -14.0
GAMEPLAY_SFX_GAIN_DB: float = -18.0
TREND_AUDIO_GAIN_DB: float = -10.0


def safezone_for(surface: str | None) -> dict[str, float]:
    """Resolve the caption safe-zone for a platform surface (fallback: tiktok)."""
    return CAPTION_SAFEZONE.get(str(surface or "").strip().lower(), CAPTION_SAFEZONE[DEFAULT_SURFACE])


def gain_for(layer: str, *, ducked: bool) -> float:
    """Default mix gain (dB) for an audio layer."""
    if layer in ("narration", "dialogue", "trigger"):
        return FOREGROUND_GAIN_DB
    if layer == "gameplay_sfx":
        return GAMEPLAY_SFX_GAIN_DB
    if layer == "trend_audio":
        return TREND_AUDIO_GAIN_DB
    if layer == "bgm":
        return DUCKED_BGM_GAIN_DB if ducked else -6.0
    return -12.0
