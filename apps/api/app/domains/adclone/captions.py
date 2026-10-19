"""Burned-in game-subtitle captions for the Ad Clone cut, styled after the source ad's captions.

The brief measures the source's caption style (position, letter case, words per caption). The plan
carries it as ``plan["captions"]``; here each spoken line becomes a transparent full-canvas PNG
(white text with a dark outline and a soft shadow, the mid-2000s game-cutscene subtitle look),
overlaid by ffmpeg only while that line is heard. PIL draws the text, so no ffmpeg text filter
(drawtext / ass / libass) is needed on the worker.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
)
TEXT = (255, 255, 255, 255)
STROKE = (12, 10, 8, 255)
SHADOW = (0, 0, 0, 150)
POSITIONS = {"top": 0.14, "middle": 0.5, "bottom": 0.8}
MAX_CHARS_PER_ROW = {"9:16": 26, "16:9": 44}


def style_from_brief(caption_style: Mapping[str, Any] | None, aspect: str) -> dict[str, Any]:
    """Plan caption style: keep the source's position and case; game-subtitle look on our side."""
    cs = dict(caption_style or {})
    position = cs.get("position") if cs.get("position") in POSITIONS else "bottom"
    case = cs.get("case") if cs.get("case") in ("lower", "upper", "sentence") else "sentence"
    return {"style": "game", "position": position, "case": case, "enabled": True,
            "max_chars": MAX_CHARS_PER_ROW.get(aspect, 26), "source_present": bool(cs.get("present"))}


def apply_case(text: str, case: str) -> str:
    if case == "lower":
        return text.lower()
    if case == "upper":
        return text.upper()
    return text


def wrap(text: str, max_chars: int) -> list[str]:
    rows: list[str] = []
    for word in text.split():
        if rows and len(rows[-1]) + 1 + len(word) <= max_chars:
            rows[-1] = f"{rows[-1]} {word}"
        else:
            rows.append(word)
    return rows or [""]


def _font(size: int):
    from PIL import ImageFont

    for path in [os.getenv("ADCLONE_CAPTION_FONT") or "", *FONT_CANDIDATES]:
        if path and os.path.isfile(path):
            return ImageFont.truetype(path, size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def render_png(text: str, out_path: str, size: tuple[int, int], style: Mapping[str, Any],
               center_y: float | None = None) -> str:
    """A transparent canvas-size PNG with one caption (centre at ``center_y`` px, else the style position)."""
    from PIL import Image, ImageDraw

    w, h = size
    font_px = max(int(min(w, h) * 0.052), 14)
    font = _font(font_px)
    rows = wrap(apply_case(text, str(style.get("case", "sentence"))), int(style.get("max_chars", 26)))
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    line_h = int(font_px * 1.25)
    cy = center_y if center_y is not None else h * POSITIONS.get(str(style.get("position")), 0.8)
    top = int(cy - line_h * len(rows) / 2)
    stroke = max(font_px // 12, 2)
    for i, row in enumerate(rows):
        box = draw.textbbox((0, 0), row, font=font, stroke_width=stroke)
        x = (w - (box[2] - box[0])) / 2
        y = top + i * line_h
        draw.text((x + stroke, y + stroke * 1.5), row, font=font, fill=SHADOW)
        draw.text((x, y), row, font=font, fill=TEXT, stroke_width=stroke, stroke_fill=STROKE)
    img.save(out_path)
    return out_path


def windows(seg: Mapping[str, Any], line_len: Mapping[str, float], shot_onsets: Mapping[str, Mapping[str, float]],
            still_lead: float) -> list[tuple[str, float, float]]:
    """(line id, start, end) inside a segment's own time for every line it voices."""
    out = []
    if seg["type"] == "clip":
        for lid in seg["lines"]:
            a = shot_onsets[seg["shot"]][lid] - seg["start"]
            out.append((lid, round(max(a, 0.0), 3), round(min(a + float(line_len[lid]), seg["len"]), 3)))
    elif seg["type"] == "still":
        t = still_lead
        for lid in seg["lines"]:
            out.append((lid, round(t, 3), round(min(t + float(line_len[lid]), seg["len"]), 3)))
            t += float(line_len[lid]) + 0.3
    return [w for w in out if w[2] > w[1]]
