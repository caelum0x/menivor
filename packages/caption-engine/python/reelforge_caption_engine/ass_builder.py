"""ASS document builder (mirror of ``src/ass/*.ts``).

``build_ass(words, style)`` turns word-level timestamps into a full ASS subtitle
string with ``\\k`` karaoke timing per word, grouped into 1-2-word display
chunks. Deterministic, pure string assembly → byte-identical to the TypeScript
port (verified by the golden ``.ass`` fixtures). ``services/captions`` burns the
exact string the client previews.
"""

from __future__ import annotations

from typing import Iterable

from .color import hex_to_ass
from .style import CaptionStyle

PLAY_RES_X = 1080
PLAY_RES_Y = 1920

_STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
    "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
    "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
)
_EVENT_FORMAT = (
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
)


def format_time(seconds: float) -> str:
    """Seconds → ASS ``H:MM:SS.cc`` (centisecond precision)."""
    cs_total = int(round(max(0.0, seconds) * 100))
    h = cs_total // 360000
    m = (cs_total % 360000) // 6000
    s = (cs_total % 6000) // 100
    cs = cs_total % 100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _style_line(style: CaptionStyle) -> str:
    bold = -1 if style.bold else 0
    return (
        f"Style: Default,{style.font},{style.size},"
        f"{hex_to_ass(style.primary_hex)},{hex_to_ass(style.highlight_hex)},"
        f"{hex_to_ass(style.outline_hex)},&H00000000,"
        f"{bold},0,0,0,100,100,0,0,1,"
        f"{style.outline},{style.shadow},{style.alignment},60,60,{style.margin_v},1"
    )


def _group(words: list[dict], size: int) -> Iterable[list[dict]]:
    size = max(1, int(size))
    for i in range(0, len(words), size):
        yield words[i:i + size]


def _dialogue_line(group: list[dict], style: CaptionStyle) -> str:
    start = format_time(group[0]["start"])
    end = format_time(group[-1]["end"])
    parts = []
    for w in group:
        dur_cs = int(round((float(w["end"]) - float(w["start"])) * 100))
        dur_cs = max(0, dur_cs)
        text = str(w["text"])
        if style.uppercase:
            text = text.upper()
        parts.append(f"{{\\k{dur_cs}}}{text}")
    body = " ".join(parts)
    return f"Dialogue: 0,{start},{end},Default,,0,0,0,,{body}"


def build_ass(words: list[dict], style: CaptionStyle | None = None) -> str:
    """Build a complete ASS document string from word timestamps + a style."""
    style = style or CaptionStyle()
    lines: list[str] = []
    lines.append("[Script Info]")
    lines.append("ScriptType: v4.00+")
    lines.append(f"PlayResX: {PLAY_RES_X}")
    lines.append(f"PlayResY: {PLAY_RES_Y}")
    lines.append("")
    lines.append("[V4+ Styles]")
    lines.append(_STYLE_FORMAT)
    lines.append(_style_line(style))
    lines.append("")
    lines.append("[Events]")
    lines.append(_EVENT_FORMAT)
    for group in _group(list(words), style.words_per_group):
        if group:
            lines.append(_dialogue_line(group, style))
    return "\n".join(lines) + "\n"
