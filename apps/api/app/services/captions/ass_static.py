"""Static sentence subtitles (ASS): whole sentences, no karaoke, no pop, no emphasis.

The karaoke builder (``ass_karaoke``) highlights word by word; this one shows a
whole sentence for its whole time span, the way a game cutscene or a fashion
lookbook subtitles a line. Two styles:

* ``game_yellow``: sentence case, yellow ``#FFE14D``, thin black outline,
  bottom-centre, ``MarginV`` 700 at 1080x1920 (above the Reels/TikTok bottom UI,
  inside the safe zone). Scaled with the canvas height (467 at 720x1280).
* ``serif_lower_third``: small serif, warm white with a soft shadow, lower
  third, left-aligned, same safe-zone margin.

Pure string builders: no I/O, no ffmpeg. Text is escaped so it can never open an
override block or a line break escape; Turkish letters pass through unchanged
(the style declares ``Encoding`` 1, as the karaoke styles do).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.services.captions.ass_karaoke import _format_ts

__all__ = ["STATIC_STYLES", "StaticStyle", "build_static_ass", "escape_text", "sentence_case", "static_style"]

BASE_W, BASE_H = 1080, 1920
# U+2060 WORD JOINER after a literal backslash keeps ``\N`` / ``\n`` / ``\h`` from forming.
_WORD_JOINER = "⁠"


@dataclass(frozen=True)
class StaticStyle:
    """One static subtitle style, sized for a 1080x1920 canvas (scaled per render)."""

    id: str
    font: str
    fontsize: float
    primary: str  # &HAABBGGRR
    outline_col: str
    back_col: str
    outline: float
    shadow: float
    alignment: int  # numpad layout: 2 bottom-centre, 1 bottom-left
    margin_v: int
    margin_lr: int
    bold: bool = False
    italic: bool = False
    sentence_case: bool = False


STATIC_STYLES: dict[str, StaticStyle] = {
    "game_yellow": StaticStyle(
        id="game_yellow", font="Inter", fontsize=52, primary="&H004DE1FF", outline_col="&H00000000",
        back_col="&H00000000", outline=2.5, shadow=0, alignment=2, margin_v=700, margin_lr=90, bold=True,
        sentence_case=True,
    ),
    "serif_lower_third": StaticStyle(
        id="serif_lower_third", font="Georgia", fontsize=44, primary="&H00F2EEE9", outline_col="&H00000000",
        back_col="&H8C000000", outline=0, shadow=2, alignment=1, margin_v=700, margin_lr=90, italic=False,
    ),
}


def static_style(style_id: str) -> StaticStyle:
    try:
        return STATIC_STYLES[style_id]
    except KeyError as exc:
        raise ValueError(f"unknown static caption style: {style_id}") from exc


def escape_text(text: str) -> str:
    """Make caption text inert for libass: no override blocks, no ``\\N``-style escapes, one line."""
    cleaned = " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())
    return (cleaned.replace("\\", "\\" + _WORD_JOINER)
            .replace("{", "(").replace("}", ")"))


def sentence_case(text: str, language: str = "") -> str:
    """Capitalise the first letter only; the rest stays as written (Turkish ``i`` -> ``İ``)."""
    for index, char in enumerate(text):
        if char.isalpha():
            if language.lower().startswith("tr"):
                upper = {"i": "İ", "ı": "I"}.get(char, char.upper())
            else:
                upper = char.upper()
            return text[:index] + upper + text[index + 1:]
    return text


def _scaled(value: float, factor: float) -> str:
    scaled = round(float(value) * factor, 2)
    return str(int(scaled)) if scaled == int(scaled) else f"{scaled:g}"


def _header(style: StaticStyle, play_w: int, play_h: int) -> str:
    factor = play_h / BASE_H
    fields = [
        "Static", style.font, _scaled(style.fontsize, factor), style.primary, style.primary, style.outline_col,
        style.back_col, "-1" if style.bold else "0", "-1" if style.italic else "0", "0", "0", "100", "100", "0",
        "0", "1", _scaled(style.outline, factor), _scaled(style.shadow, factor), str(style.alignment),
        str(round(style.margin_lr * factor)), str(round(style.margin_lr * factor)),
        str(round(style.margin_v * factor)), "1",
    ]
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {int(play_w)}\n"
        f"PlayResY: {int(play_h)}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        f"Style: {','.join(fields)}\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def build_static_ass(lines: Sequence[tuple[str, float, float]], style_id: str, play_w: int = BASE_W,
                     play_h: int = BASE_H, *, language: str = "") -> str:
    """ASS file text: one ``Dialogue`` per ``(text, start_s, end_s)``, whole sentence, no tags."""
    style = static_style(style_id)
    events = []
    for text, start, end in lines:
        body = escape_text(text)
        if not body or float(end) <= float(start):
            continue
        if style.sentence_case:
            body = sentence_case(body, language)
        events.append(f"Dialogue: 0,{_format_ts(float(start))},{_format_ts(float(end))},Static,,0,0,0,,{body}")
    return _header(style, play_w, play_h) + "".join(f"{event}\n" for event in events)
