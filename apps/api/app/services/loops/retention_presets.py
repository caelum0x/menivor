"""Retention-optimized export preset builder.

Bundles the export-time retention levers into one preset the compose stage
applies: a **loop-back seam** (last frame ≈ first frame) for loopable genres so
the reel replays invisibly (rewatch rate is weighted above likes), a **burned-in
keyword overlay** in a corner (on-screen text is a discovery/search signal and
survives sound-off viewing), and the per-platform caption **safe-zone**. Pure —
combines ``policy`` + ``safezone`` + the caller's keywords into a serializable
plan; the composer renders it. Deterministic + unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.captions.safezone import safezone_for
from app.services.loops import policy


@dataclass(frozen=True)
class KeywordOverlay:
    """A small burned-in keyword line (top-corner, out of the caption safe-zone)."""

    text: str
    position: str = "top_left"      # kept clear of the lower-third caption band
    max_chars: int = 40


@dataclass(frozen=True)
class RetentionPreset:
    """The export-time retention plan the compose stage consumes."""

    loop_back: bool                 # match last frame to first for a seamless replay
    max_discontinuity: float        # accept the loop only under this seam threshold
    caption_y_frac: float           # caption band placement (safe-zone)
    caption_height_frac: float
    keyword_overlay: KeywordOverlay | None
    enforce_hook_gate: bool         # block export if the first-3s hook misses the gate
    notes: tuple[str, ...] = field(default_factory=tuple)


def build_retention_preset(
    *,
    genre: str,
    loopable: bool,
    surface: str = "tiktok",
    keywords: list[str] | None = None,
    enforce_hook_gate: bool = True,
) -> RetentionPreset:
    """Assemble the retention export preset for a genre + platform.

    ASMR/loop genres get an aggressive loop-back with a tight seam threshold; other
    loopable genres get a looser one. The top-2 keywords (if any) become the
    burned-in overlay. The caption band comes from the platform safe-zone.
    """
    zone = safezone_for(surface)
    kws = [k for k in (keywords or []) if k][:2]
    overlay = (
        KeywordOverlay(text=" ".join(kws).upper()) if kws else None
    )

    is_asmr = str(genre or "").strip().lower() == "asmr"
    seam = (
        policy.LOOP_MAX_DISCONTINUITY * 0.5 if is_asmr else policy.LOOP_MAX_DISCONTINUITY
    )
    notes: list[str] = []
    if loopable:
        notes.append("loop-back seam enabled — replay inflates completion/rewatch")
    if overlay:
        notes.append("keyword overlay burned in — searchable + sound-off legible")

    return RetentionPreset(
        loop_back=bool(loopable),
        max_discontinuity=round(seam, 4),
        caption_y_frac=zone.y_frac,
        caption_height_frac=zone.height_frac,
        keyword_overlay=overlay,
        enforce_hook_gate=enforce_hook_gate,
        notes=tuple(notes),
    )


def preset_to_dict(preset: RetentionPreset) -> dict:
    """JSON-safe view of the preset (for the export API / compose worker)."""
    return {
        "loop_back": preset.loop_back,
        "max_discontinuity": preset.max_discontinuity,
        "caption_y_frac": preset.caption_y_frac,
        "caption_height_frac": preset.caption_height_frac,
        "keyword_overlay": (
            {
                "text": preset.keyword_overlay.text,
                "position": preset.keyword_overlay.position,
                "max_chars": preset.keyword_overlay.max_chars,
            }
            if preset.keyword_overlay
            else None
        ),
        "enforce_hook_gate": preset.enforce_hook_gate,
        "notes": list(preset.notes),
    }
