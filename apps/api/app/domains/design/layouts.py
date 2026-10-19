"""Built-in Design Studio templates: pure functions from (size, copy, brand) to canvas pages.

Every template returns a list of pages in the editor's ``canvas_json`` shape
(see :mod:`app.domains.design.models`). Layout is proportional to the canvas
so one template works for square, portrait, story, landscape, banner and app
store sizes. Text boxes carry a font size estimated to fit their box; the
editor re-wraps with real font metrics.

Nothing here invents claims: the copy comes from :mod:`.copy`, which only uses
what the user typed and what is in their brand kit.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Callable

DEFAULT_PRIMARY = "#111827"
DEFAULT_ACCENT = "#f59e0b"
DEFAULT_LIGHT = "#f8fafc"
DEFAULT_DARK = "#0f172a"
DEFAULT_FONT = "Inter"


@dataclass(frozen=True)
class Copy:
    headline: str
    subline: str = ""
    cta: str = ""
    badge: str = ""
    points: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BrandStyle:
    name: str = ""
    primary: str = DEFAULT_PRIMARY
    accent: str = DEFAULT_ACCENT
    light: str = DEFAULT_LIGHT
    dark: str = DEFAULT_DARK
    heading_font: str = DEFAULT_FONT
    body_font: str = DEFAULT_FONT
    #: R2 key of the brand logo imported into the caller's library ("" = no logo).
    logo_key: str = ""


@dataclass(frozen=True)
class Template:
    slug: str
    name: str
    description: str
    build: Callable[[int, int, Copy, BrandStyle], list[dict]]
    #: Size presets this template suits (empty = all).
    presets: tuple[str, ...] = ()


# --------------------------------------------------------------------------- #
# Colour + text helpers
# --------------------------------------------------------------------------- #
def _rgb(hex_color: str) -> tuple[int, int, int]:
    raw = hex_color.lstrip("#")
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def luminance(hex_color: str) -> float:
    def channel(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = _rgb(hex_color)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def ink_on(background: str, style: BrandStyle) -> str:
    """The brand's dark or light colour, whichever reads better on ``background``."""
    return style.dark if contrast(background, style.dark) >= contrast(background, style.light) else style.light


def fit_font(text: str, box_w: float, box_h: float, *, max_size: float, min_size: float = 14,
             line_height: float = 1.15, char_w: float = 0.54) -> int:
    """Largest font size (px) at which ``text`` is estimated to wrap inside the box."""
    words = text.split() or [""]
    size = max_size
    while size > min_size:
        per_line = max(1, int(box_w / (size * char_w)))
        lines, current = 1, 0
        for word in words:
            need = len(word) + (1 if current else 0)
            if current and current + need > per_line:
                lines, current = lines + 1, len(word)
            else:
                current += need
            lines += max(0, math.ceil(len(word) / per_line) - 1) if len(word) > per_line else 0
        if lines * size * line_height <= box_h:
            break
        size -= 2
    return int(max(min_size, size))


def _id() -> str:
    return uuid.uuid4().hex[:12]


def text_layer(text: str, x: float, y: float, w: float, h: float, *, font: str, color: str, max_size: float,
               weight: int = 400, align: str = "left", line_height: float = 1.15, name: str = "Text",
               uppercase: bool = False) -> dict:
    size = fit_font(text.upper() if uppercase else text, w, h, max_size=max_size, line_height=line_height)
    return {
        "id": _id(), "type": "text", "name": name, "x": round(x), "y": round(y), "width": round(w),
        "height": round(h), "rotation": 0, "opacity": 1,
        "props": {"text": text, "fontFamily": font, "fontSize": size, "fontWeight": weight, "color": color,
                  "align": align, "lineHeight": line_height, "uppercase": uppercase},
    }


def rect_layer(x: float, y: float, w: float, h: float, *, fill: str, radius: float = 0, stroke: str = "",
               stroke_width: float = 0, name: str = "Shape", opacity: float = 1) -> dict:
    return {
        "id": _id(), "type": "rect", "name": name, "x": round(x), "y": round(y), "width": round(w),
        "height": round(h), "rotation": 0, "opacity": opacity,
        "props": {"fill": fill, "radius": round(radius), "stroke": stroke, "strokeWidth": round(stroke_width)},
    }


def ellipse_layer(x: float, y: float, w: float, h: float, *, fill: str, name: str = "Circle") -> dict:
    return {
        "id": _id(), "type": "ellipse", "name": name, "x": round(x), "y": round(y), "width": round(w),
        "height": round(h), "rotation": 0, "opacity": 1, "props": {"fill": fill, "stroke": "", "strokeWidth": 0},
    }


def image_layer(key: str, x: float, y: float, w: float, h: float, *, fit: str = "contain", name: str = "Image",
                radius: float = 0) -> dict:
    return {
        "id": _id(), "type": "image", "name": name, "x": round(x), "y": round(y), "width": round(w),
        "height": round(h), "rotation": 0, "opacity": 1, "props": {"key": key, "fit": fit, "radius": round(radius)},
    }


def _cta(copy: Copy, style: BrandStyle, x: float, y: float, w: float, h: float, *, fill: str,
         align_center: bool = True) -> list[dict]:
    if not copy.cta:
        return []
    ink = ink_on(fill, style)
    return [
        rect_layer(x, y, w, h, fill=fill, radius=h / 2, name="Button"),
        text_layer(copy.cta, x + h * 0.4, y + h * 0.2, w - h * 0.8, h * 0.6, font=style.body_font, color=ink,
                   max_size=h * 0.42, weight=700, align="center" if align_center else "left", name="Button text"),
    ]


def _logo(style: BrandStyle, x: float, y: float, size: float) -> list[dict]:
    return [image_layer(style.logo_key, x, y, size * 2.4, size, fit="contain", name="Logo")] if style.logo_key else []


def _page(background: str, layers: list[dict]) -> dict:
    return {"background": background, "layers": layers}


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #
def bold_headline(w: int, h: int, copy: Copy, s: BrandStyle) -> list[dict]:
    m = min(w, h) * 0.08
    ink = ink_on(s.primary, s)
    tall = h >= w
    head_h = h * (0.34 if tall else 0.42)
    head_y = h * (0.28 if tall else 0.2)
    layers = [
        *_logo(s, m, m, min(w, h) * 0.07),
        text_layer(copy.headline, m, head_y, w - 2 * m, head_h, font=s.heading_font, color=ink,
                   max_size=min(w, h) * 0.13, weight=700, name="Headline"),
    ]
    if copy.subline:
        layers.append(text_layer(copy.subline, m, head_y + head_h + m * 0.4, w - 2 * m, h * 0.14,
                                 font=s.body_font, color=ink, max_size=min(w, h) * 0.045, name="Subline"))
    btn_h = min(w, h) * 0.095
    layers += _cta(copy, s, m, h - m - btn_h, min(w - 2 * m, btn_h * 5.2), btn_h, fill=s.accent)
    return [_page(s.primary, layers)]


def split_panel(w: int, h: int, copy: Copy, s: BrandStyle) -> list[dict]:
    tall = h >= w
    m = min(w, h) * 0.07
    if tall:
        panel = rect_layer(0, 0, w, h * 0.55, fill=s.primary, name="Panel")
        ink = ink_on(s.primary, s)
        head = text_layer(copy.headline, m, h * 0.55 - m - h * 0.3, w - 2 * m, h * 0.3, font=s.heading_font,
                          color=ink, max_size=min(w, h) * 0.12, weight=700, name="Headline")
        body_top, body_left, body_w = h * 0.55 + m, m, w - 2 * m
    else:
        panel = rect_layer(0, 0, w * 0.5, h, fill=s.primary, name="Panel")
        ink = ink_on(s.primary, s)
        head = text_layer(copy.headline, m, m * 1.6, w * 0.5 - 2 * m, h - 3.2 * m, font=s.heading_font,
                          color=ink, max_size=h * 0.16, weight=700, name="Headline")
        body_top, body_left, body_w = m * 1.6, w * 0.5 + m, w * 0.5 - 2 * m
    body_ink = ink_on(s.light, s)
    layers = [panel, head, *_logo(s, body_left, body_top, min(w, h) * 0.06)]
    y = body_top + min(w, h) * 0.1
    if copy.subline:
        layers.append(text_layer(copy.subline, body_left, y, body_w, min(w, h) * 0.22, font=s.body_font,
                                 color=body_ink, max_size=min(w, h) * 0.05, name="Subline"))
        y += min(w, h) * 0.26
    btn_h = min(w, h) * 0.09
    layers += _cta(copy, s, body_left, min(y, h - m - btn_h), min(body_w, btn_h * 5.2), btn_h, fill=s.accent)
    return [_page(s.light, layers)]


def minimal_frame(w: int, h: int, copy: Copy, s: BrandStyle) -> list[dict]:
    m = min(w, h) * 0.06
    ink = ink_on(s.light, s)
    layers = [
        rect_layer(m, m, w - 2 * m, h - 2 * m, fill="transparent", stroke=s.primary,
                   stroke_width=max(4, min(w, h) * 0.008), name="Frame"),
        rect_layer(w / 2 - min(w, h) * 0.06, h * 0.3, min(w, h) * 0.12, max(6, min(w, h) * 0.012),
                   fill=s.accent, name="Accent line"),
        text_layer(copy.headline, m * 2.2, h * 0.34, w - 4.4 * m, h * 0.3, font=s.heading_font, color=ink,
                   max_size=min(w, h) * 0.1, weight=700, align="center", name="Headline"),
    ]
    if copy.subline:
        layers.append(text_layer(copy.subline, m * 2.2, h * 0.66, w - 4.4 * m, h * 0.12, font=s.body_font,
                                 color=ink, max_size=min(w, h) * 0.04, align="center", name="Subline"))
    size = min(w, h) * 0.06
    if s.logo_key:
        layers += _logo(s, w / 2 - size * 1.2, h - m * 2.2 - size, size)
    elif copy.cta:
        btn_h = min(w, h) * 0.08
        bw = min(w - 4.4 * m, btn_h * 5)
        layers += _cta(copy, s, w / 2 - bw / 2, h - m * 2.2 - btn_h, bw, btn_h, fill=s.primary)
    return [_page(s.light, layers)]


def badge_offer(w: int, h: int, copy: Copy, s: BrandStyle) -> list[dict]:
    m = min(w, h) * 0.07
    bg = s.dark
    ink = ink_on(bg, s)
    d = min(w, h) * 0.3
    badge_text = copy.badge or s.name or copy.cta or "New"
    layers = [
        ellipse_layer(w - m - d, m, d, d, fill=s.accent, name="Badge"),
        text_layer(badge_text, w - m - d + d * 0.15, m + d * 0.3, d * 0.7, d * 0.4, font=s.heading_font,
                   color=ink_on(s.accent, s), max_size=d * 0.2, weight=700, align="center", name="Badge text"),
        text_layer(copy.headline, m, h * 0.42, w - 2 * m, h * 0.28, font=s.heading_font, color=ink,
                   max_size=min(w, h) * 0.11, weight=700, name="Headline"),
        *_logo(s, m, m, min(w, h) * 0.07),
    ]
    if copy.subline:
        layers.append(text_layer(copy.subline, m, h * 0.71, w - 2 * m, h * 0.1, font=s.body_font, color=ink,
                                 max_size=min(w, h) * 0.04, name="Subline"))
    btn_h = min(w, h) * 0.09
    layers += _cta(copy, s, m, h - m - btn_h, min(w - 2 * m, btn_h * 5.2), btn_h, fill=s.primary if
                   contrast(s.primary, bg) > 1.5 else s.accent)
    return [_page(bg, layers)]


def carousel_story(w: int, h: int, copy: Copy, s: BrandStyle) -> list[dict]:
    """Cover, one slide per point (up to 3), closing call to action."""
    m = min(w, h) * 0.08
    pages = bold_headline(w, h, Copy(headline=copy.headline, subline=copy.subline), s)
    ink = ink_on(s.light, s)
    for i, point in enumerate(copy.points[:3], start=1):
        pages.append(_page(s.light, [
            text_layer(f"{i:02d}", m, m, w * 0.3, h * 0.14, font=s.heading_font, color=s.accent,
                       max_size=min(w, h) * 0.12, weight=700, name="Number"),
            text_layer(point, m, h * 0.3, w - 2 * m, h * 0.45, font=s.heading_font, color=ink,
                       max_size=min(w, h) * 0.08, weight=700, name="Point"),
            *_logo(s, m, h - m - min(w, h) * 0.06, min(w, h) * 0.06),
        ]))
    btn_h = min(w, h) * 0.1
    close_ink = ink_on(s.primary, s)
    pages.append(_page(s.primary, [
        text_layer(s.name or copy.headline, m, h * 0.3, w - 2 * m, h * 0.2, font=s.heading_font, color=close_ink,
                   max_size=min(w, h) * 0.1, weight=700, align="center", name="Closing"),
        *_cta(copy, s, w / 2 - btn_h * 2.8, h * 0.58, btn_h * 5.6, btn_h, fill=s.accent),
    ]))
    return pages


def app_store_shot(w: int, h: int, copy: Copy, s: BrandStyle) -> list[dict]:
    """Store screenshot: caption on top, a device-screen slot for the app capture below."""
    m = w * 0.07
    ink = ink_on(s.primary, s)
    screen_w = w * 0.74
    screen_h = min(h * 0.66, screen_w * 2.1)
    screen_x = (w - screen_w) / 2
    screen_y = h - screen_h - m * 0.6
    return [_page(s.primary, [
        text_layer(copy.headline, m, m * 1.4, w - 2 * m, h * 0.14, font=s.heading_font, color=ink,
                   max_size=w * 0.09, weight=700, align="center", name="Caption"),
        *([text_layer(copy.subline, m, m * 1.4 + h * 0.14, w - 2 * m, h * 0.07, font=s.body_font, color=ink,
                      max_size=w * 0.045, align="center", name="Subcaption")] if copy.subline else []),
        rect_layer(screen_x - w * 0.02, screen_y - w * 0.02, screen_w + w * 0.04, screen_h + w * 0.04,
                   fill=s.dark, radius=w * 0.09, name="Device"),
        rect_layer(screen_x, screen_y, screen_w, screen_h, fill=s.light, radius=w * 0.07,
                   name="Screen (replace with your app capture)"),
    ])]


TEMPLATES: dict[str, Template] = {t.slug: t for t in (
    Template("bold-headline", "Bold headline", "Brand colour background with a large headline and a button.",
             bold_headline),
    Template("split-panel", "Split panel", "Brand colour panel for the headline, details and button beside it.",
             split_panel),
    Template("minimal-frame", "Minimal frame", "Light background, thin brand frame and a centred headline.",
             minimal_frame),
    Template("badge-offer", "Badge", "Dark background with a round accent badge for an offer or label.",
             badge_offer),
    Template("carousel-story", "Carousel", "Cover, one slide per point and a closing call to action.",
             carousel_story, presets=("carousel",)),
    Template("app-store", "App store screenshot", "Caption above a device frame for your app capture.",
             app_store_shot, presets=("app_store",)),
)}

#: Templates offered for a preset when generating options, in order.
_DEFAULT_ORDER = ("bold-headline", "split-panel", "minimal-frame", "badge-offer")


def templates_for(preset: str) -> list[Template]:
    specific = [t for t in TEMPLATES.values() if preset in t.presets]
    general = [TEMPLATES[s] for s in _DEFAULT_ORDER]
    if preset == "carousel":
        return specific + general[:3]
    if preset == "app_store":
        return specific + [TEMPLATES["bold-headline"], TEMPLATES["minimal-frame"]]
    return general


def build(template_slug: str, width: int, height: int, copy: Copy, style: BrandStyle) -> dict:
    """One ``canvas_json`` document for a template."""
    template = TEMPLATES.get(template_slug)
    if template is None:
        raise KeyError(template_slug)
    return {"version": 1, "pages": template.build(width, height, copy, style)}


__all__ = [
    "BrandStyle",
    "Copy",
    "TEMPLATES",
    "Template",
    "build",
    "contrast",
    "fit_font",
    "ink_on",
    "templates_for",
]
