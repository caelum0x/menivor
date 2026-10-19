"""Procedural art for the original narrators (M2.3): free generation, CPU only.

Every pose of a narrator is a short list of vector primitives computed from its
``look`` (body shape, colours, eyes, headwear) in a 1000x1000 unit space. The
reference sheet is the set of all poses (9 mouth shapes x eyes open/closed); its
SHA-256 over canonical JSON is the character's identity lock. Because the hash
is taken over the vector sheet, not pixels, it does not change with the Pillow
version, and the same sheet always rasterises to the same frames on one build.

Mouth shapes follow Rhubarb Lip Sync's alphabet: A (closed, M/B/P), B (slightly
open, teeth), C (open, EH), D (wide open, AA), E (rounded, AO/ER), F (puckered,
UW/OO), G (F/V, teeth on lip), H (L, tongue up) and X (rest, closed).
"""

from __future__ import annotations

import hashlib
import io
import json
from functools import lru_cache
from typing import Iterable

from app.domains.characters.narrators import NarratorCharacter, NarratorLook

__all__ = [
    "MOUTH_SHAPES",
    "CLOSED_SHAPES",
    "pose_primitives",
    "reference_sheet",
    "render_pose",
    "render_sheet_png",
    "sheet_hash",
]

MOUTH_SHAPES: tuple[str, ...] = ("X", "A", "B", "C", "D", "E", "F", "G", "H")
#: Shapes with the lips together (rest and M/B/P).
CLOSED_SHAPES: frozenset[str] = frozenset({"X", "A"})

_INK = "#1B1B1E"
_WHITE = "#FFFFFF"
_MOUTH = "#3A1F2B"
_TONGUE = "#E07A8B"
_MOUTH_X, _MOUTH_Y = 500, 690

# A primitive: (kind, coords, fill, outline, width). Coords are ints.
Prim = tuple


def _p(kind: str, coords: Iterable[int], fill: str | None = None,
       outline: str | None = None, width: int = 0) -> Prim:
    return (kind, tuple(int(c) for c in coords), fill, outline, int(width))


def _body(look: NarratorLook) -> list[Prim]:
    skin, accent = look.skin, look.accent
    feet = [
        _p("ellipse", (330, 880, 470, 960), accent),
        _p("ellipse", (530, 880, 670, 960), accent),
    ]
    if look.body == "round":
        shape = [_p("ellipse", (210, 300, 790, 920), skin, _INK, 10)]
    elif look.body == "tall":
        shape = [_p("rounded_rectangle", (280, 220, 720, 930, 170), skin, _INK, 10)]
    elif look.body == "pear":
        shape = [
            _p("ellipse", (250, 420, 750, 930), skin, _INK, 10),
            _p("ellipse", (310, 250, 690, 640), skin, _INK, 10),
            _p("ellipse", (320, 400, 680, 700), skin),  # hides the inner seam
        ]
    else:  # square
        shape = [_p("rounded_rectangle", (230, 300, 770, 920, 110), skin, _INK, 10)]
    belly = [_p("ellipse", (400, 790, 600, 890), accent)]
    cheeks = [
        _p("ellipse", (300, 600, 370, 650), "#F28482"),
        _p("ellipse", (630, 600, 700, 650), "#F28482"),
    ]
    return feet + shape + belly + cheeks


def _top(look: NarratorLook) -> list[Prim]:
    accent = look.accent
    head_top = {"round": 300, "tall": 220, "pear": 250, "square": 300}[look.body]
    if look.top == "tuft":
        y = head_top + 20
        return [
            _p("polygon", (440, y, 470, y - 90, 500, y), accent, _INK, 6),
            _p("polygon", (480, y, 520, y - 120, 560, y), accent, _INK, 6),
        ]
    if look.top == "cap":
        return [
            _p("chord", (330, head_top - 60, 670, head_top + 170, 180, 360), accent, _INK, 8),
            _p("rounded_rectangle", (540, head_top + 40, 740, head_top + 80, 20), accent, _INK, 8),
        ]
    if look.top == "bun":
        return [_p("ellipse", (420, head_top - 110, 580, head_top + 40), accent, _INK, 8)]
    if look.top == "beanie":
        return [
            _p("chord", (300, head_top - 50, 700, head_top + 190, 180, 360), accent, _INK, 8),
            _p("ellipse", (460, head_top - 100, 540, head_top - 20), _WHITE, _INK, 6),
        ]
    if look.top == "antenna":
        return [
            _p("line", (500, head_top + 10, 500, head_top - 110), None, _INK, 12),
            _p("ellipse", (465, head_top - 150, 535, head_top - 80), accent, _INK, 6),
        ]
    return []


def _eyes(look: NarratorLook, open_: bool) -> list[Prim]:
    prims: list[Prim] = []
    for cx in (400, 600):
        cy = 520
        if not open_:
            prims.append(_p("arc", (cx - 45, cy - 30, cx + 45, cy + 30, 20, 160), None, _INK, 12))
        elif look.eyes == "oval":
            prims.append(_p("ellipse", (cx - 40, cy - 52, cx + 40, cy + 52), _WHITE, _INK, 6))
            prims.append(_p("ellipse", (cx - 20, cy - 16, cx + 20, cy + 28), _INK))
            prims.append(_p("ellipse", (cx - 12, cy - 10, cx, cy + 2), _WHITE))
        else:  # dot and glasses
            prims.append(_p("ellipse", (cx - 34, cy - 34, cx + 34, cy + 34), _INK))
            prims.append(_p("ellipse", (cx - 20, cy - 22, cx - 2, cy - 4), _WHITE))
        if look.eyes == "glasses":
            prims.append(_p("ellipse", (cx - 72, cy - 72, cx + 72, cy + 72), None, look.accent, 14))
    if look.eyes == "glasses":
        prims.append(_p("line", (472, 520, 528, 520), None, look.accent, 14))
    return prims


def _mouth(shape: str) -> list[Prim]:
    x, y = _MOUTH_X, _MOUTH_Y
    if shape == "X":
        return [_p("arc", (x - 60, y - 40, x + 60, y + 20, 20, 160), None, _INK, 12)]
    if shape == "A":
        return [_p("line", (x - 50, y, x + 50, y), None, _INK, 16)]
    if shape == "B":
        return [
            _p("rounded_rectangle", (x - 60, y - 18, x + 60, y + 18, 14), _MOUTH, _INK, 6),
            _p("rectangle", (x - 48, y - 12, x + 48, y + 2), _WHITE),
        ]
    if shape == "C":
        return [
            _p("ellipse", (x - 62, y - 32, x + 62, y + 36), _MOUTH, _INK, 6),
            _p("ellipse", (x - 34, y + 6, x + 34, y + 32), _TONGUE),
        ]
    if shape == "D":
        return [
            _p("ellipse", (x - 72, y - 52, x + 72, y + 62), _MOUTH, _INK, 6),
            _p("rectangle", (x - 50, y - 44, x + 50, y - 26), _WHITE),
            _p("ellipse", (x - 40, y + 18, x + 40, y + 56), _TONGUE),
        ]
    if shape == "E":
        return [_p("ellipse", (x - 40, y - 46, x + 40, y + 46), _MOUTH, _INK, 6)]
    if shape == "F":
        return [_p("ellipse", (x - 26, y - 24, x + 26, y + 24), _MOUTH, _INK, 10)]
    if shape == "G":
        return [
            _p("rounded_rectangle", (x - 58, y - 16, x + 58, y + 22, 14), _MOUTH, _INK, 6),
            _p("rectangle", (x - 46, y - 12, x + 46, y + 6), _WHITE),
        ]
    if shape == "H":
        return [
            _p("ellipse", (x - 58, y - 36, x + 58, y + 40), _MOUTH, _INK, 6),
            _p("ellipse", (x - 26, y - 30, x + 26, y + 4), _TONGUE),
        ]
    raise ValueError(f"unknown mouth shape {shape!r}")


def pose_primitives(character: NarratorCharacter, mouth: str, eyes_open: bool) -> tuple[Prim, ...]:
    """Every primitive of one pose, in paint order."""
    look = character.look
    return tuple(_body(look) + _top(look) + _eyes(look, eyes_open) + _mouth(mouth))


def reference_sheet(character: NarratorCharacter) -> dict:
    """The full vector reference sheet: look plus every pose."""
    poses = {
        f"{mouth}-{'open' if eyes else 'blink'}": [list(p) for p in pose_primitives(character, mouth, eyes)]
        for mouth in MOUTH_SHAPES
        for eyes in (True, False)
    }
    return {"id": character.id, "backdrop": character.look.backdrop, "poses": poses}


def sheet_hash(character: NarratorCharacter) -> str:
    """SHA-256 of the canonical reference sheet (the identity lock)."""
    canonical = json.dumps(reference_sheet(character), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _draw(draw, prim: Prim, scale: float) -> None:
    kind, coords, fill, outline, width = prim
    w = max(1, int(round(width * scale))) if width else 0
    if kind == "rounded_rectangle":
        box = [round(c * scale) for c in coords[:4]]
        draw.rounded_rectangle(box, radius=round(coords[4] * scale), fill=fill, outline=outline, width=w)
    elif kind in ("chord", "arc"):
        box = [round(c * scale) for c in coords[:4]]
        start, end = coords[4], coords[5]
        if kind == "chord":
            draw.chord(box, start, end, fill=fill, outline=outline, width=w)
        else:
            draw.arc(box, start, end, fill=outline, width=w)
    else:
        pts = [round(c * scale) for c in coords]
        if kind == "ellipse":
            draw.ellipse(pts, fill=fill, outline=outline, width=w)
        elif kind == "rectangle":
            draw.rectangle(pts, fill=fill, outline=outline, width=w)
        elif kind == "polygon":
            draw.polygon(pts, fill=fill, outline=outline, width=w)
        elif kind == "line":
            draw.line(pts, fill=outline, width=w, joint="curve")
        else:  # pragma: no cover - primitives are produced above
            raise ValueError(f"unknown primitive {kind!r}")


@lru_cache(maxsize=512)
def _render_cached(character: NarratorCharacter, mouth: str, eyes_open: bool, size: int) -> bytes:
    from PIL import Image, ImageDraw

    big = size * 2  # draw at 2x, downsample for anti-aliasing
    image = Image.new("RGB", (big, big), character.look.backdrop)
    draw = ImageDraw.Draw(image)
    scale = big / 1000.0
    for prim in pose_primitives(character, mouth, eyes_open):
        _draw(draw, prim, scale)
    return image.resize((size, size), Image.LANCZOS).tobytes()


def render_pose(character: NarratorCharacter, mouth: str, eyes_open: bool = True, size: int = 440):
    """One pose as an RGB ``PIL.Image`` of ``size`` x ``size``."""
    from PIL import Image

    return Image.frombytes("RGB", (size, size), _render_cached(character, mouth, eyes_open, size))


def render_sheet_png(character: NarratorCharacter, cell: int = 220) -> bytes:
    """A PNG contact sheet of every pose (for the owner's art review, O9)."""
    from PIL import Image

    cols = len(MOUTH_SHAPES)
    sheet = Image.new("RGB", (cols * cell, 2 * cell), character.look.backdrop)
    for col, mouth in enumerate(MOUTH_SHAPES):
        for row, eyes in enumerate((True, False)):
            sheet.paste(render_pose(character, mouth, eyes, cell), (col * cell, row * cell))
    buf = io.BytesIO()
    sheet.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
