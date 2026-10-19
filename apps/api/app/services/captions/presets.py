"""CapCut-style caption STYLE PRESETS as frozen :class:`KaraokeStyle` variants.

Each preset is an immutable :class:`~app.services.captions.ass_karaoke.KaraokeStyle`
built by :func:`dataclasses.replace` off the library default, so presets share the
default font/layout and differ only in colours, outline/shadow, and (optionally)
fontsize. Preset ids match the identifiers the Next.js wizard already emits
(``web/components/wizard/types.ts`` → ``CAPTION_STYLE_OPTIONS``):

- ``karaoke_yellow`` — white spoken / yellow upcoming (the current default).
- ``karaoke_green``  — white spoken / neon-green upcoming.
- ``clean_white``    — all-white, subtle outline, no highlight colour flip.
- ``bold_violet``    — white spoken / brand-violet upcoming, heavier outline.

Every preset also carries a keyword ``emphasis`` colour (M2.4): one word per
2-4 word line is drawn in it, and it always differs from the line colours.

Colours are ASS ``&HAABBGGRR`` (alpha-blue-green-red, ``00`` alpha = opaque).

Public API:
- ``CAPTION_STYLE_PRESETS: dict[str, KaraokeStyle]`` — id → style registry.
- ``DEFAULT_CAPTION_STYLE: str`` — id of the fallback style.
- :func:`get_caption_style` — resolve an id (or ``None``) to a ``KaraokeStyle``.
- :func:`list_caption_styles` — catalogue metadata for the styles API.
"""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType
from typing import Mapping, Optional

from app.services.captions.ass_karaoke import KaraokeStyle

__all__ = [
    "CAPTION_STYLE_PRESETS",
    "DEFAULT_CAPTION_STYLE",
    "get_caption_style",
    "list_caption_styles",
]

# --- ASS &HAABBGGRR colour constants ---------------------------------------
_WHITE = "&H00FFFFFF"  # opaque white  (rgb #ffffff)
_YELLOW = "&H0000FFFF"  # opaque yellow (rgb #ffff00) — classic karaoke pending
_NEON_GREEN = "&H0014FF39"  # opaque green  (rgb #39ff14)
_VIOLET = "&H00FA8BA7"  # opaque violet (rgb #a78bfa)
_LIGHT_GREY = "&H00C8C8C8"  # opaque grey   (rgb #c8c8c8)
_BLACK = "&H00000000"  # opaque black outline
_SHADOW_BACK = "&H64000000"  # semi-transparent shadow / back colour
_PINK = "&H00C77BFF"  # opaque pink   (rgb #ff7bc7)
_GOLD = "&H0047C8F5"  # opaque gold   (rgb #f5c847), the Menivor mark colour

# ASS numpad alignments used by the style presets.
_ALIGN_BOTTOM = 2
_ALIGN_MIDDLE = 5

# Base style = the library default (Montserrat ExtraBold, 88px, top-center).
_BASE: KaraokeStyle = KaraokeStyle()


def _preset(**overrides: object) -> KaraokeStyle:
    """Return a frozen ``KaraokeStyle`` copy of ``_BASE`` with ``overrides`` applied."""
    return replace(_BASE, **overrides)  # type: ignore[arg-type]


# --- Preset registry --------------------------------------------------------
# NOTE: ``karaoke_yellow`` intentionally mirrors ``KaraokeStyle()`` so the
# default id and the dataclass default render identically.
_PRESETS: dict[str, KaraokeStyle] = {
    "karaoke_yellow": _preset(
        primary=_WHITE,
        secondary=_YELLOW,
        outline_col=_BLACK,
        back_col=_SHADOW_BACK,
        outline=5,
        shadow=1,
    ),
    "karaoke_green": _preset(
        emphasis=_YELLOW,
        primary=_WHITE,
        secondary=_NEON_GREEN,
        outline_col=_BLACK,
        back_col=_SHADOW_BACK,
        outline=5,
        shadow=1,
    ),
    "clean_white": _preset(
        emphasis=_GOLD,
        primary=_WHITE,
        secondary=_WHITE,  # no colour flip: spoken == upcoming
        outline_col=_BLACK,
        back_col=_SHADOW_BACK,
        outline=3,  # subtle outline
        shadow=0,
        pop=False,  # minimal, no bounce
    ),
    "bold_violet": _preset(
        emphasis=_GOLD,
        primary=_WHITE,
        secondary=_VIOLET,
        outline_col=_BLACK,
        back_col=_SHADOW_BACK,
        fontsize=92,  # slightly larger for punchy CTAs
        outline=7,  # heavier outline
        shadow=2,
    ),
    # Style presets (app.domains.styles): placed for their scene layouts.
    # Split-screen seam: centred on the join between the two halves.
    "split_center": _preset(
        emphasis=_NEON_GREEN,
        primary=_WHITE,
        secondary=_GOLD,
        outline_col=_BLACK,
        back_col=_SHADOW_BACK,
        fontsize=84,
        outline=7,
        shadow=2,
        alignment=_ALIGN_MIDDLE,
        margin_v=0,
    ),
    # Meme hook: the hook lives in the white band up top, captions sit low.
    "meme_clean": _preset(
        emphasis=_YELLOW,
        primary=_WHITE,
        secondary=_WHITE,
        outline_col=_BLACK,
        back_col=_SHADOW_BACK,
        fontsize=76,
        outline=5,
        shadow=1,
        pop=False,
        alignment=_ALIGN_BOTTOM,
        margin_v=420,
    ),
    # Anime style: soft pink highlight in the lower third, over the art.
    "anime_pop": _preset(
        emphasis=_GOLD,
        primary=_WHITE,
        secondary=_PINK,
        outline_col=_BLACK,
        back_col=_SHADOW_BACK,
        fontsize=84,
        outline=6,
        shadow=2,
        alignment=_ALIGN_BOTTOM,
        margin_v=460,
    ),
}

#: Immutable id → :class:`KaraokeStyle` registry.
CAPTION_STYLE_PRESETS: Mapping[str, KaraokeStyle] = MappingProxyType(_PRESETS)

#: Fallback preset id for unknown/None requests (the current default look).
DEFAULT_CAPTION_STYLE: str = "karaoke_yellow"

# --- Catalogue metadata (id -> human-facing name/description) ---------------
_METADATA: dict[str, dict[str, str]] = {
    "karaoke_yellow": {
        "name": "Karaoke (yellow)",
        "description": "White spoken words, yellow upcoming — classic CapCut pop.",
    },
    "karaoke_green": {
        "name": "Karaoke (green)",
        "description": "High-energy neon highlight for gaming and tech reels.",
    },
    "clean_white": {
        "name": "Clean white",
        "description": "Minimal all-white captions with a subtle outline, no colour flip.",
    },
    "bold_violet": {
        "name": "Bold violet",
        "description": "Brand-violet highlight with a heavier outline for strong CTAs.",
    },
    "split_center": {
        "name": "Split seam",
        "description": "Gold highlight centred on the seam of a split-screen reel.",
    },
    "meme_clean": {
        "name": "Meme clean",
        "description": "Plain white lower-third captions under a meme-caption hook.",
    },
    "anime_pop": {
        "name": "Anime pop",
        "description": "Soft pink highlight in the lower third, made for illustrated scenes.",
    },
}


def get_caption_style(style_id: Optional[str]) -> KaraokeStyle:
    """Resolve ``style_id`` to a :class:`KaraokeStyle`, falling back to the default.

    Args:
        style_id: A preset id (e.g. ``"karaoke_green"``). ``None``, empty, or
            unknown ids fall back to :data:`DEFAULT_CAPTION_STYLE`.

    Returns:
        The frozen :class:`KaraokeStyle` for the requested (or default) preset.
    """
    if style_id:
        preset = CAPTION_STYLE_PRESETS.get(style_id)
        if preset is not None:
            return preset
    return CAPTION_STYLE_PRESETS[DEFAULT_CAPTION_STYLE]


def list_caption_styles() -> list[dict[str, str]]:
    """Return catalogue metadata for every preset (for the styles API).

    Returns:
        One dict per preset with keys ``id``, ``name``, ``description``,
        ``primary`` and ``secondary`` (the latter two as ASS ``&HAABBGGRR``),
        ordered as declared in the registry with the default preset first.
    """
    ordered_ids = [DEFAULT_CAPTION_STYLE] + [
        style_id
        for style_id in CAPTION_STYLE_PRESETS
        if style_id != DEFAULT_CAPTION_STYLE
    ]
    catalog: list[dict[str, str]] = []
    for style_id in ordered_ids:
        style = CAPTION_STYLE_PRESETS[style_id]
        meta = _METADATA.get(style_id, {})
        catalog.append(
            {
                "id": style_id,
                "name": meta.get("name", style_id),
                "description": meta.get("description", ""),
                "primary": style.primary,
                "secondary": style.secondary,
            }
        )
    return catalog
