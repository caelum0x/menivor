"""Caption cards: full-frame transparent PNG overlays rendered with Pillow.

Text is rasterized here instead of with FFmpeg ``drawtext`` so rendering does
not depend on an FFmpeg build with libfreetype and so Turkish glyphs, wrapping
and emphasis are controlled precisely. Cards respect platform safe zones: text
sits in the middle band on vertical video (clear of TikTok/Reels UI at the
bottom and top) and in the lower third on square/landscape video.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

ACCENT = (255, 214, 10, 255)
INK = (17, 17, 17, 255)
WHITE = (255, 255, 255, 255)
PANEL = (0, 0, 0, 178)
_FONT_FILES = ("Inter-Bold.ttf", "Montserrat-ExtraBold.ttf", "BeVietnamPro-Bold.ttf")


@dataclass(frozen=True)
class Card:
    """One on-screen caption. ``style``: hook | body | label | price | cta."""

    text: str
    style: str = "body"
    label: str = ""
    subtext: str = ""


@lru_cache(maxsize=32)
def _font(size: int) -> Any:
    from PIL import ImageFont

    try:
        from app.utils import utils

        directory = utils.font_dir()
    except Exception:  # noqa: BLE001 - fall back to Pillow's bundled font
        directory = ""
    for name in _FONT_FILES:
        path = os.path.join(directory, name)
        if directory and os.path.isfile(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def _wrap(draw: Any, text: str, font: Any, max_width: int, max_lines: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .,") + "…"
    return lines


def _band_center(width: int, height: int) -> int:
    if height > width:  # vertical: centre-lower band, clear of platform chrome
        return int(height * 0.60)
    return int(height * 0.76)


def render_card(card: Card, width: int, height: int, path: str) -> str:
    """Rasterize ``card`` into a transparent ``width``x``height`` PNG at ``path``."""
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    short = min(width, height)
    size = {"hook": 0.078, "cta": 0.074, "price": 0.09, "label": 0.07}.get(card.style, 0.06)
    font = _font(max(18, int(short * size)))
    pad = int(short * 0.04)
    max_width = int(width * (0.84 if height > width else 0.7))
    lines = _wrap(draw, card.text, font, max_width - 2 * pad, 4 if card.style != "price" else 2)
    line_h = int(font.size * 1.22)
    sub_font = _font(max(14, int(short * 0.042)))
    sub_lines = _wrap(draw, card.subtext, sub_font, max_width - 2 * pad, 2) if card.subtext else []
    sub_h = int(sub_font.size * 1.25) * len(sub_lines)
    block_w = max([draw.textlength(line, font=font) for line in lines] + [draw.textlength(s, font=sub_font) for s in sub_lines] + [0])
    box_w = int(block_w) + 2 * pad
    box_h = line_h * len(lines) + sub_h + 2 * pad
    cx = width // 2
    top = _band_center(width, height) - box_h // 2
    left = cx - box_w // 2

    fill, text_color = PANEL, WHITE
    if card.style in ("price", "cta"):
        fill, text_color = ACCENT, INK
    elif card.style == "hook":
        fill, text_color = WHITE, INK
    draw.rounded_rectangle((left, top, left + box_w, top + box_h), radius=int(pad * 0.9), fill=fill)

    if card.label:
        label_font = _font(max(16, int(short * 0.045)))
        label_w = int(draw.textlength(card.label, font=label_font)) + pad
        label_h = int(label_font.size * 1.5)
        lx, ly = cx - label_w // 2, top - label_h - int(pad * 0.5)
        draw.rounded_rectangle((lx, ly, lx + label_w, ly + label_h), radius=label_h // 2, fill=ACCENT)
        draw.text((cx, ly + label_h // 2), card.label, font=label_font, fill=INK, anchor="mm")

    y = top + pad
    for line in lines:
        draw.text((cx, y + line_h // 2), line, font=font, fill=text_color, anchor="mm")
        y += line_h
    for sub in sub_lines:
        sub_line_h = int(sub_font.size * 1.25)
        draw.text((cx, y + sub_line_h // 2), sub, font=sub_font, fill=text_color, anchor="mm")
        y += sub_line_h
    image.save(path, "PNG")
    return path


__all__ = ["Card", "render_card"]
