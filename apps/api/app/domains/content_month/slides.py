"""Carousel slides for an idea: hook cover, one big statement per slide, call to action.

The output is a Design Studio ``canvas_json`` (see :mod:`app.domains.design.models`),
so the same deck can be opened in the editor, rasterized on the server
(:mod:`.raster`) or rendered in the browser. Two sizes: ``tiktok`` (1080x1920,
photo-mode slideshow; text kept inside the platform safe zone) and
``instagram`` (1080x1350, 4:5 feed carousel).

Style: the brand's primary colour on the cover and closing slide, light body
slides with a slide counter in the accent colour, one statement per slide in
large type, the brand logo (or name) small on every slide.
"""

from __future__ import annotations

import math

from app.domains.design.layouts import BrandStyle, ellipse_layer, fit_font, image_layer, ink_on, rect_layer, text_layer

#: name -> (Design Studio size preset, width, height)
SIZES: dict[str, tuple[str, int, int]] = {
    "tiktok": ("story", 1080, 1920),
    "instagram": ("portrait", 1080, 1350),
}
DEFAULT_SIZE = "tiktok"
LINE_HEIGHT = 1.15
CHAR_W = 0.54


def _text_height(text: str, width: float, size: float) -> float:
    per_line = max(1, int(width / (size * CHAR_W)))
    lines, current = 1, 0
    for word in text.split():
        need = len(word) + (1 if current else 0)
        if current and current + need > per_line:
            lines, current = lines + 1, len(word)
        else:
            current += need
        if len(word) > per_line:
            lines += math.ceil(len(word) / per_line) - 1
    return lines * size * LINE_HEIGHT


def _centered(text: str, x: float, top: float, w: float, band_h: float, *, font: str, color: str,
              max_size: float, weight: int = 700, align: str = "center", name: str = "Text") -> dict:
    """A text layer vertically centred in the band ``[top, top + band_h]``."""
    size = fit_font(text, w, band_h, max_size=max_size, line_height=LINE_HEIGHT)
    used = min(band_h, _text_height(text, w, size) + size * 0.3)
    layer = text_layer(text, x, top + (band_h - used) / 2, w, used, font=font, color=color, max_size=size,
                       weight=weight, align=align, name=name)
    layer["props"]["fontSize"] = size
    return layer


def _brand_mark(style: BrandStyle, x: float, y: float, h: float, color: str) -> list[dict]:
    if style.logo_key:
        return [image_layer(style.logo_key, x, y, h * 2.6, h, fit="contain", name="Logo")]
    if style.name:
        return [text_layer(style.name, x, y, h * 8, h, font=style.heading_font, color=color, max_size=h * 0.8,
                           weight=700, name="Brand")]
    return []


def _safe_band(w: int, h: int) -> tuple[float, float]:
    """(top, height) of the area platform UI never covers."""
    if h / w > 1.6:  # 9:16: clear of the top bar and the caption/buttons area
        return h * 0.16, h * 0.56
    return h * 0.14, h * 0.66


def cover(hook: str, style: BrandStyle, w: int, h: int, total: int) -> dict:
    m = w * 0.08
    top, band = _safe_band(w, h)
    ink = ink_on(style.primary, style)
    return {"background": style.primary, "layers": [
        rect_layer(m, top - w * 0.05, w * 0.16, max(8, w * 0.012), fill=style.accent, name="Accent"),
        _centered(hook, m, top, w - 2 * m, band, font=style.heading_font, color=ink, max_size=w * 0.115,
                  align="left", name="Hook"),
        *_brand_mark(style, m, top + band + h * 0.02, w * 0.055, ink),
        *([text_layer("Swipe", w - m - w * 0.22, top + band + h * 0.02, w * 0.22, w * 0.06,
                      font=style.body_font, color=ink, max_size=w * 0.04, weight=700, align="right",
                      name="Swipe")] if total > 1 else []),
    ]}


def body(text: str, style: BrandStyle, w: int, h: int, index: int, total: int) -> dict:
    m = w * 0.08
    top, band = _safe_band(w, h)
    bg = style.light
    ink = ink_on(bg, style)
    dot = w * 0.035
    return {"background": bg, "layers": [
        text_layer(f"{index + 1:02d}/{total:02d}", m, top - w * 0.1, w * 0.4, w * 0.07, font=style.heading_font,
                   color=style.primary if ink != style.primary else style.accent, max_size=w * 0.05, weight=700,
                   name="Counter"),
        _centered(text, m, top, w - 2 * m, band, font=style.heading_font, color=ink, max_size=w * 0.09,
                  align="left", name="Statement"),
        ellipse_layer(w - m - dot, top - w * 0.085, dot, dot, fill=style.accent, name="Dot"),
        *_brand_mark(style, m, top + band + h * 0.02, w * 0.045, ink),
    ]}


def closing(text: str, style: BrandStyle, w: int, h: int) -> dict:
    m = w * 0.08
    top, band = _safe_band(w, h)
    ink = ink_on(style.primary, style)
    btn_h = w * 0.13
    btn_ink = ink_on(style.accent, style)
    return {"background": style.primary, "layers": [
        _centered(style.name or text, m, top, w - 2 * m, band * 0.45, font=style.heading_font, color=ink,
                  max_size=w * 0.13, name="Brand name"),
        rect_layer(m, top + band * 0.55, w - 2 * m, btn_h, fill=style.accent, radius=btn_h / 2, name="Button"),
        _centered(text, m + btn_h * 0.4, top + band * 0.55, w - 2 * m - btn_h * 0.8, btn_h, font=style.body_font,
                  color=btn_ink, max_size=btn_h * 0.36, name="Call to action"),
        *([image_layer(style.logo_key, w / 2 - w * 0.09, top + band * 0.55 + btn_h + h * 0.05, w * 0.18, w * 0.18,
                       fit="contain", name="Logo")] if style.logo_key else []),
    ]}


def deck(slides: list[str], style: BrandStyle, size: str = DEFAULT_SIZE) -> dict:
    """``canvas_json`` for a carousel (first slide = hook, last = call to action)."""
    if size not in SIZES:
        raise ValueError(f"unknown size {size!r}")
    _, w, h = SIZES[size]
    texts = [s for s in slides if s and s.strip()] or [style.name or "Untitled"]
    total = len(texts)
    pages = [cover(texts[0], style, w, h, total)]
    for index, text in enumerate(texts[1:-1], start=1):
        pages.append(body(text, style, w, h, index, total))
    if total > 1:
        pages.append(closing(texts[-1], style, w, h))
    return {"version": 1, "pages": pages}


__all__ = ["DEFAULT_SIZE", "SIZES", "deck"]
