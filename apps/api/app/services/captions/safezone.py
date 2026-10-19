"""Per-platform caption safe-zone sizing.

Each platform overlays its own UI chrome (right-rail actions, bottom caption/CTA)
over different regions, so caption height + vertical position must adapt: TikTok
captions sit at ~12-20% frame height in the lower third (Y≈63%), YouTube Shorts
smaller (~9%) to clear the title bar, Reels in between. Returns concrete pixel
values for a given frame height so the ASS builder places captions in the clear
zone on every surface.
"""

from __future__ import annotations

from dataclasses import dataclass

# fraction-of-frame-height sizing per surface.
_SURFACE = {
    "tiktok": {"height_frac": 0.16, "y_frac": 0.63},
    "reels": {"height_frac": 0.14, "y_frac": 0.62},
    "shorts": {"height_frac": 0.09, "y_frac": 0.64},
    "x": {"height_frac": 0.12, "y_frac": 0.60},
}
_DEFAULT = "tiktok"


@dataclass(frozen=True)
class SafeZone:
    """Resolved caption placement for a specific frame height."""

    surface: str
    fontsize: int      # px, derived from height_frac × play_h
    margin_v: int      # px from the TOP edge (ASS alignment 8 = top-center)
    y_frac: float
    height_frac: float


def safezone_for(surface: str | None, play_h: int = 1920) -> SafeZone:
    """Resolve the caption safe-zone for ``surface`` at ``play_h`` pixels tall.

    ``margin_v`` is measured from the top (matching the ASS top-center alignment
    the karaoke builder uses), computed from ``y_frac`` so captions land in the
    platform's clear lower-third band.
    """
    cfg = _SURFACE.get(str(surface or "").strip().lower(), _SURFACE[_DEFAULT])
    fontsize = max(24, int(round(cfg["height_frac"] * play_h * 0.5)))
    margin_v = int(round(cfg["y_frac"] * play_h)) - fontsize
    return SafeZone(
        surface=str(surface or _DEFAULT).lower(),
        fontsize=fontsize,
        margin_v=max(0, margin_v),
        y_frac=cfg["y_frac"],
        height_frac=cfg["height_frac"],
    )


def supported_surfaces() -> tuple[str, ...]:
    return tuple(_SURFACE)
