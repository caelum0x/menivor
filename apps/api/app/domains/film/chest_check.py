"""Chest-text check for generated stills (Very ___ Time, gap item 6).

Image models often misspell the garment's chest embroidery ("very Turkish
time"). Every still that shows the chest is read back with OCR and compared to
the brand chest text:

1. the first attempt uses the frame's seed;
2. on a mismatch the frame is re-rolled with ``seed + 1009 * k`` up to the
   plan's cap (``max_rerolls``, clamped to 0..5; never more generate calls than
   ``max_rerolls + 1``). Re-rolls are part of the frame price the user already
   saw, so they never charge the user again;
3. after the cap, the correct text is drawn as a clean overlay on the last
   attempt (over the misspelled text's box when OCR found one).

OCR engine: RapidOCR (``rapidocr-onnxruntime``, Apache-2.0) with the bundled
PP-OCR ONNX models (Apache-2.0) on onnxruntime. When the package or its models
are missing, the check is skipped (status ``unchecked``), never a failed render.

Pure apart from the OCR engine and Pillow; no import of the template modules.
"""

from __future__ import annotations

import difflib
import io
import os
import re
import threading
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from loguru import logger

REROLLS_ENV = "VERY_TIME_CHEST_REROLLS"
MAX_REROLLS_CAP = 5
REROLL_SEED_STEP = 1009
IVORY = (0xF2, 0xEE, 0xE9)
OUTLINE = (20, 12, 12)
_PREFERRED_FONTS = ("Inter-Bold.ttf", "BeVietnamPro-Bold.ttf", "BeVietnamPro-Medium.ttf", "Montserrat-ExtraBold.ttf")
_SERIF_HINTS = ("serif", "georgia", "times", "garamond", "playfair", "lora", "merriweather")

Box = tuple[int, int, int, int]


@dataclass(frozen=True)
class OcrLine:
    text: str
    box: Box  # x0, y0, x1, y1 in pixels
    score: float


class OcrUnavailable(RuntimeError):
    """The OCR package or its models are not installed."""


@dataclass(frozen=True)
class ChestResult:
    image: bytes
    status: str  # "ok" | "rerolled" | "overlay" | "unchecked"
    attempts: int
    seed: int
    read: str


# --------------------------------------------------------------------------- #
# OCR engine (created once)
# --------------------------------------------------------------------------- #
_ENGINE: Any = None
_ENGINE_LOCK = threading.Lock()


def _engine() -> Any:
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except Exception as exc:  # noqa: BLE001 - any import failure means no OCR
                raise OcrUnavailable(f"rapidocr is not installed: {exc}") from exc
            try:
                _ENGINE = RapidOCR()
            except Exception as exc:  # noqa: BLE001 - missing models or runtime
                raise OcrUnavailable(f"rapidocr could not start: {exc}") from exc
    return _ENGINE


def ocr_available() -> bool:
    try:
        _engine()
        return True
    except OcrUnavailable:
        return False


def _box(points: Any) -> Box:
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    return int(min(xs)), int(min(ys)), int(round(max(xs))), int(round(max(ys)))


def read_text(image: bytes) -> list[OcrLine]:
    """Every text line OCR finds in ``image`` (top to bottom)."""
    engine = _engine()
    try:
        result, _elapsed = engine(image)
    except Exception as exc:  # noqa: BLE001 - an unreadable image reads as no text
        logger.warning(f"chest check: OCR failed on an image: {exc}")
        return []
    lines = [OcrLine(text=str(text), box=_box(points), score=float(score))
             for points, text, score in (result or [])]
    return sorted(lines, key=lambda line: (line.box[1], line.box[0]))


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #
_NON_WORD = re.compile(r"[^0-9a-z]+")


def normalise(text: str) -> str:
    """Turkish-aware fold: I/ı/İ/i together, accents dropped, letters and digits only."""
    lowered = str(text or "").replace("İ", "i").replace("I", "i").replace("ı", "i").casefold()
    stripped = "".join(c for c in unicodedata.normalize("NFKD", lowered) if not unicodedata.combining(c))
    return " ".join(_NON_WORD.sub(" ", stripped).split())


def _union(boxes: Sequence[Box]) -> Box:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def text_matches(expected: str, lines: Sequence[OcrLine], *, threshold: float = 0.85
                 ) -> tuple[bool, str, Box | None]:
    """Whether OCR read the expected chest text (one line, or two adjacent wrapped lines).

    Returns ``(ok, best_read_text, box)``; the box is the best candidate's (the
    union for two lines), ``None`` when nothing was read.
    """
    want = normalise(expected)
    candidates: list[tuple[str, Box]] = [(line.text, line.box) for line in lines if normalise(line.text)]
    for first, second in zip(lines, lines[1:]):
        candidates.append((f"{first.text} {second.text}", _union((first.box, second.box))))
    best: tuple[float, str, Box | None] = (0.0, "", None)
    for text, box in candidates:
        ratio = _ratio(want, normalise(text))
        if ratio > best[0]:
            best = (ratio, text, box)
    return (bool(want) and best[0] >= threshold), best[1], best[2]


# --------------------------------------------------------------------------- #
# Overlay
# --------------------------------------------------------------------------- #
def _font_files() -> list[str]:
    try:
        from app.utils import utils

        folder = utils.font_dir()
    except Exception:  # noqa: BLE001 - no repo fonts dir is fine
        return []
    try:
        names = sorted(n for n in os.listdir(folder) if n.lower().endswith((".ttf", ".otf")))
    except OSError:
        return []
    serif = [n for n in names if any(h in n.lower() for h in _SERIF_HINTS)]
    preferred = [n for n in _PREFERRED_FONTS if n in names]
    rest = [n for n in names if n not in serif and n not in preferred]
    return [os.path.join(folder, n) for n in (*serif, *preferred, *rest)]


def _font(size: int):
    from PIL import ImageFont

    for path in _font_files():
        try:
            return ImageFont.truetype(path, max(8, int(size)))
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=max(8, int(size)))
    except TypeError:  # older Pillow without a sized default
        return ImageFont.load_default()


def _fit_font(draw: Any, text: str, width: int, height: int):
    """The largest font whose rendered text fits ``width`` x ``height``."""
    size = max(8, int(height))
    while size > 8:
        font = _font(size)
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font, stroke_width=max(1, size // 18))
        if right - left <= width and bottom - top <= height:
            return font, size
        size = int(size * 0.9)
    return _font(8), 8


def _border_median(image: Any, box: Box) -> tuple[int, int, int]:
    x0, y0, x1, y1 = box
    pixels = []
    for x in range(x0, x1 + 1, max(1, (x1 - x0) // 40 or 1)):
        pixels += [image.getpixel((x, y0)), image.getpixel((x, y1))]
    for y in range(y0, y1 + 1, max(1, (y1 - y0) // 20 or 1)):
        pixels += [image.getpixel((x0, y)), image.getpixel((x1, y))]
    channels = list(zip(*pixels))
    return tuple(sorted(c)[len(c) // 2] for c in channels)  # type: ignore[return-value]


def overlay_text(image: bytes, text: str, *, box: Box | None = None,
                 region: tuple[float, float] = (0.5, 0.55)) -> bytes:
    """Draw ``text`` cleanly on the image (PNG out, same size).

    With ``box`` (the misspelled text OCR found) the box is covered with the
    median colour of its border and the text is fitted inside it; without one
    the text is centred at ``region`` (fractions of width, height) at about 22 %
    of the image width.
    """
    from PIL import Image, ImageDraw

    with Image.open(io.BytesIO(image)) as source:
        canvas = source.convert("RGB")
    width, height = canvas.size
    draw = ImageDraw.Draw(canvas)
    if box is not None:
        pad_x = max(2, (box[2] - box[0]) // 12)
        pad_y = max(2, (box[3] - box[1]) // 5)
        x0, y0 = max(0, box[0] - pad_x), max(0, box[1] - pad_y)
        x1, y1 = min(width - 1, box[2] + pad_x), min(height - 1, box[3] + pad_y)
        draw.rectangle((x0, y0, x1, y1), fill=_border_median(canvas, (x0, y0, x1, y1)))
        target_w, target_h = max(8, x1 - x0 - pad_x), max(8, y1 - y0 - pad_y)
        centre = ((x0 + x1) / 2, (y0 + y1) / 2)
    else:
        target_w, target_h = int(width * 0.22), int(height * 0.08)
        centre = (width * float(region[0]), height * float(region[1]))
    font, size = _fit_font(draw, text, target_w, target_h)
    draw.text(centre, text, font=font, fill=IVORY, anchor="mm", stroke_width=max(1, size // 18), stroke_fill=OUTLINE)
    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


# --------------------------------------------------------------------------- #
# Verify (generate, read, re-roll, overlay)
# --------------------------------------------------------------------------- #
def _clamp(value: int) -> int:
    return max(0, min(MAX_REROLLS_CAP, int(value)))


def max_rerolls_from_env(default: int = 2) -> int:
    raw = (os.getenv(REROLLS_ENV) or "").strip()
    try:
        return _clamp(int(raw)) if raw else _clamp(default)
    except ValueError:
        return _clamp(default)


def verify_chest(generate: Callable[[int], bytes], *, expected: str, seed: int, max_rerolls: int,
                 ocr: Callable[[bytes], list[OcrLine]] | None = None,
                 region: tuple[float, float] = (0.5, 0.55)) -> ChestResult:
    """Make a still whose chest text reads ``expected``; see the module doc for the rules."""
    read = ocr or read_text
    cap = _clamp(max_rerolls)
    current_seed = int(seed)
    image = generate(current_seed)
    attempts = 1
    try:
        lines = read(image)
    except OcrUnavailable as exc:
        logger.info(f"chest check skipped: {exc}")
        return ChestResult(image=image, status="unchecked", attempts=attempts, seed=current_seed, read="")
    ok, best, box = text_matches(expected, lines)
    if ok:
        return ChestResult(image=image, status="ok", attempts=attempts, seed=current_seed, read=best)
    for k in range(1, cap + 1):
        next_seed = int(seed) + REROLL_SEED_STEP * k
        try:
            candidate = generate(next_seed)
        except Exception as exc:  # noqa: BLE001 - a failed re-roll falls back to the overlay
            logger.warning(f"chest check: re-roll {k} failed: {exc}")
            break
        attempts += 1
        try:
            candidate_lines = read(candidate)
        except OcrUnavailable:
            candidate_lines = []
        image, current_seed = candidate, next_seed
        ok, best, box = text_matches(expected, candidate_lines)
        if ok:
            return ChestResult(image=image, status="rerolled", attempts=attempts, seed=current_seed, read=best)
    fixed = overlay_text(image, expected, box=box, region=region)
    return ChestResult(image=fixed, status="overlay", attempts=attempts, seed=current_seed, read=best)


__all__ = [
    "ChestResult", "OcrLine", "OcrUnavailable", "REROLLS_ENV", "max_rerolls_from_env", "normalise",
    "ocr_available", "overlay_text", "read_text", "text_matches", "verify_chest",
]
