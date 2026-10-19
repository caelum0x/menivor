"""Validate and normalise editor ``canvas_json`` before it is stored.

The editor owns the shape, but the server never stores anything it would not
render: unknown layer types and props are dropped, numbers are clamped,
colours must be ``#rrggbb`` (or ``transparent``), fonts are plain family names,
and image layers may only reference an R2 key (never a URL), which the media
endpoint re-checks for ownership before serving it.
"""

from __future__ import annotations

import re
from typing import Any

from app.domains.design.models import MAX_PAGES

MAX_LAYERS = 60
MAX_TEXT = 600
MAX_COORD = 20_000
LAYER_TYPES = frozenset({"text", "image", "rect", "ellipse", "line"})
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_FONT_RE = re.compile(r"^[A-Za-z0-9 \-]{1,60}$")
_KEY_RE = re.compile(r"^uploads/[A-Za-z0-9/_.\-]{1,200}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")


class CanvasError(ValueError):
    """The canvas is not something the editor could have produced."""


def color(value: Any, default: str = "#000000", *, allow_transparent: bool = False) -> str:
    text = str(value or "").strip()
    if allow_transparent and text == "transparent":
        return text
    if len(text) == 4 and text.startswith("#"):
        text = "#" + "".join(ch * 2 for ch in text[1:])
    return text.lower() if _HEX_RE.match(text) else default


def font(value: Any, default: str = "Inter") -> str:
    text = " ".join(str(value or "").split())
    return text if _FONT_RE.match(text) else default


def _num(value: Any, default: float, lo: float, hi: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return max(lo, min(hi, number))


def _props(kind: str, raw: dict) -> dict:
    if kind == "text":
        return {
            "text": str(raw.get("text") or "")[:MAX_TEXT],
            "fontFamily": font(raw.get("fontFamily")),
            "fontSize": round(_num(raw.get("fontSize"), 48, 6, 800)),
            "fontWeight": 700 if int(_num(raw.get("fontWeight"), 400, 100, 900)) >= 600 else 400,
            "italic": bool(raw.get("italic")),
            "color": color(raw.get("color"), "#111111"),
            "align": raw.get("align") if raw.get("align") in ("left", "center", "right") else "left",
            "lineHeight": round(_num(raw.get("lineHeight"), 1.15, 0.8, 3), 3),
            "letterSpacing": round(_num(raw.get("letterSpacing"), 0, -20, 100), 2),
            "uppercase": bool(raw.get("uppercase")),
        }
    if kind == "image":
        key = str(raw.get("key") or "")
        if not _KEY_RE.match(key) or ".." in key:
            raise CanvasError("image layers must reference an uploaded image")
        return {
            "key": key,
            "fit": raw.get("fit") if raw.get("fit") in ("cover", "contain") else "cover",
            "radius": round(_num(raw.get("radius"), 0, 0, 2000)),
        }
    if kind == "line":
        return {"stroke": color(raw.get("stroke"), "#111111"), "strokeWidth": round(_num(raw.get("strokeWidth"), 4, 1, 200))}
    return {
        "fill": color(raw.get("fill"), "#cccccc", allow_transparent=True),
        "stroke": color(raw.get("stroke"), "", allow_transparent=True) if raw.get("stroke") else "",
        "strokeWidth": round(_num(raw.get("strokeWidth"), 0, 0, 200)),
        **({"radius": round(_num(raw.get("radius"), 0, 0, 5000))} if kind == "rect" else {}),
    }


def _layer(raw: Any, index: int) -> dict:
    if not isinstance(raw, dict):
        raise CanvasError(f"layer {index} is not an object")
    kind = raw.get("type")
    if kind not in LAYER_TYPES:
        raise CanvasError(f"layer {index} has an unknown type")
    props = raw.get("props") if isinstance(raw.get("props"), dict) else {}
    layer_id = str(raw.get("id") or "")
    return {
        "id": layer_id if _ID_RE.match(layer_id) else f"l{index}",
        "type": kind,
        "name": " ".join(str(raw.get("name") or kind.title()).split())[:60],
        "x": round(_num(raw.get("x"), 0, -MAX_COORD, MAX_COORD), 2),
        "y": round(_num(raw.get("y"), 0, -MAX_COORD, MAX_COORD), 2),
        "width": round(_num(raw.get("width"), 100, 1, MAX_COORD), 2),
        "height": round(_num(raw.get("height"), 100, 1, MAX_COORD), 2),
        "rotation": round(_num(raw.get("rotation"), 0, -360, 360), 2),
        "opacity": round(_num(raw.get("opacity"), 1, 0, 1), 3),
        "locked": bool(raw.get("locked")),
        "hidden": bool(raw.get("hidden")),
        "props": _props(kind, props),
    }


def sanitize(canvas: Any) -> dict:
    """Return a clean copy of ``canvas`` or raise :class:`CanvasError`."""
    if not isinstance(canvas, dict):
        raise CanvasError("canvas must be an object")
    pages = canvas.get("pages")
    if not isinstance(pages, list) or not pages:
        raise CanvasError("canvas needs at least one page")
    if len(pages) > MAX_PAGES:
        raise CanvasError(f"at most {MAX_PAGES} pages")
    clean_pages = []
    for p_index, page in enumerate(pages):
        if not isinstance(page, dict):
            raise CanvasError(f"page {p_index} is not an object")
        layers = page.get("layers") if isinstance(page.get("layers"), list) else []
        if len(layers) > MAX_LAYERS:
            raise CanvasError(f"at most {MAX_LAYERS} layers per page")
        clean_pages.append({
            "background": color(page.get("background"), "#ffffff"),
            "layers": [_layer(layer, i) for i, layer in enumerate(layers)],
        })
    return {"version": 1, "pages": clean_pages}


def image_keys(canvas: dict) -> set[str]:
    return {
        layer["props"]["key"]
        for page in canvas.get("pages", [])
        for layer in page.get("layers", [])
        if layer.get("type") == "image" and layer.get("props", {}).get("key")
    }


def fonts_used(canvas: dict) -> list[str]:
    seen: dict[str, None] = {}
    for page in canvas.get("pages", []):
        for layer in page.get("layers", []):
            if layer.get("type") == "text":
                seen.setdefault(layer["props"]["fontFamily"], None)
    return list(seen)


__all__ = ["CanvasError", "color", "font", "fonts_used", "image_keys", "sanitize"]
