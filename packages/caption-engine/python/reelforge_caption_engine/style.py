"""``CaptionStyle`` + preset registry (mirror of ``src/style.ts`` + ``src/presets``).

Presets are plain data; the ASS builder consumes them. Kept identical to the
TypeScript presets so previews and burned captions match.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CaptionStyle:
    font: str = "Montserrat Black"
    size: int = 120
    primary_hex: str = "#FFFFFF"       # base fill
    highlight_hex: str = "#FFD93D"     # karaoke reveal / keyword colour
    outline_hex: str = "#000000"
    outline: int = 4
    shadow: int = 2
    alignment: int = 5                 # ASS numpad: 5 = middle-center
    margin_v: int = 0
    bold: bool = True
    uppercase: bool = True
    words_per_group: int = 2


_PRESETS: dict[str, CaptionStyle] = {
    "hormozi": CaptionStyle(),  # defaults ARE Hormozi
    "karaoke-classic": CaptionStyle(
        font="Arial", size=90, primary_hex="#FFFFFF", highlight_hex="#35D9FF",
        alignment=2, margin_v=120, uppercase=False, words_per_group=4),
    "minimal-top-label": CaptionStyle(
        font="Helvetica", size=64, primary_hex="#FFFFFF", highlight_hex="#FFFFFF",
        outline=2, shadow=1, alignment=8, margin_v=120, bold=False,
        uppercase=False, words_per_group=1),
    "brainrot-popin": CaptionStyle(
        font="Impact", size=140, primary_hex="#FFFFFF", highlight_hex="#39FF14",
        outline=6, shadow=0, alignment=5, uppercase=True, words_per_group=2),
}


def get_preset(name: str) -> CaptionStyle:
    if name not in _PRESETS:
        raise KeyError(f"unknown caption preset {name!r}; one of {sorted(_PRESETS)}")
    return _PRESETS[name]


def list_presets() -> list[str]:
    return sorted(_PRESETS)
