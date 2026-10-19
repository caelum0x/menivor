"""Pillow cover / thumbnail renderer for ReelForge (Creator Studio).

Given a reel's HOOK line and (optionally) the job's poster frame, this module
renders a 1080x1920 JPEG "cover" — the eye-catching still a creator can attach
to a reel before publishing. The headline is drawn as a bold, centered,
word-wrapped, stroked title in a chosen visual *style*.

Design notes
------------
* **Pure Pillow.** No FFmpeg, no external services. The only external asset is
  the bundled ``resource/fonts/Montserrat-ExtraBold.ttf`` (full Turkish glyph
  coverage — ``İĞÜŞÖÇ``), resolved via :func:`app.utils.utils.font_dir`.
* **Import-guarded.** ``from PIL import ...`` is wrapped so this file still
  ``py_compile``\\s on a box without Pillow installed; every public entry point
  that actually needs Pillow raises a clear :class:`RuntimeError` if it is
  missing. (Pillow *is* installed in the project venv.)
* **Legibility first.** Whether the background is a poster frame (cover-cropped
  and darkened) or a style gradient, a bottom-to-top scrim is composited under
  the text, and the headline itself is drawn with a contrasting stroke so it
  stays readable over any background.
* **Never overflows.** The headline is word-wrapped to the text column and the
  font size auto-shrinks until the wrapped block fits the available box; the raw
  headline is also length-capped defensively before any layout happens.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.utils import utils

# --------------------------------------------------------------------------- #
# Optional Pillow import (guarded so this module still py_compiles without it)
# --------------------------------------------------------------------------- #
try:  # pragma: no cover - exercised implicitly wherever Pillow is present
    from PIL import Image, ImageDraw, ImageFont

    _PIL_AVAILABLE = True
    _PIL_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - only hit when Pillow is absent
    Image = ImageDraw = ImageFont = None  # type: ignore[assignment]
    _PIL_AVAILABLE = False
    _PIL_IMPORT_ERROR = exc

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PIL import ImageFont as _ImageFontModule


# --------------------------------------------------------------------------- #
# Types
# --------------------------------------------------------------------------- #
RGB = tuple[int, int, int]
RGBA = tuple[int, int, int, int]


@dataclass(frozen=True)
class CoverStyle:
    """A cover preset controlling background treatment and text rendering.

    Colors are RGB(A) tuples so rendering stays dependency-free. ``gradient_top``
    /``gradient_bottom`` are only used when no poster is supplied (the style's own
    background). ``poster_darken`` (0..1) is how much a supplied poster frame is
    dimmed so the headline reads over it. ``scrim_alpha`` is the peak opacity of
    the bottom-to-top legibility scrim.
    """

    id: str
    name: str
    text_color: RGB
    stroke_color: RGB
    gradient_top: RGB
    gradient_bottom: RGB
    poster_darken: float = 0.45
    scrim_alpha: int = 200
    uppercase: bool = True


# --------------------------------------------------------------------------- #
# Style catalog
# --------------------------------------------------------------------------- #
_CLASSIC = CoverStyle(
    id="classic",
    name="Classic",
    text_color=(255, 255, 255),
    stroke_color=(0, 0, 0),
    gradient_top=(38, 42, 54),
    gradient_bottom=(12, 14, 20),
    poster_darken=0.45,
    scrim_alpha=205,
    uppercase=True,
)
_SUNSET = CoverStyle(
    id="sunset",
    name="Sunset",
    text_color=(255, 255, 255),
    stroke_color=(74, 20, 8),
    gradient_top=(255, 148, 41),
    gradient_bottom=(196, 33, 84),
    poster_darken=0.35,
    scrim_alpha=170,
    uppercase=True,
)
_BOLD_YELLOW = CoverStyle(
    id="bold_yellow",
    name="Bold Yellow",
    text_color=(255, 214, 10),
    stroke_color=(0, 0, 0),
    gradient_top=(28, 28, 30),
    gradient_bottom=(0, 0, 0),
    poster_darken=0.5,
    scrim_alpha=210,
    uppercase=True,
)
_MINIMAL = CoverStyle(
    id="minimal",
    name="Minimal",
    text_color=(245, 245, 247),
    stroke_color=(20, 20, 24),
    gradient_top=(30, 30, 34),
    gradient_bottom=(18, 18, 20),
    poster_darken=0.55,
    scrim_alpha=225,
    uppercase=False,
)

# Registry keyed by id; insertion order is the catalog order.
COVER_STYLES: dict[str, CoverStyle] = {
    _CLASSIC.id: _CLASSIC,
    _SUNSET.id: _SUNSET,
    _BOLD_YELLOW.id: _BOLD_YELLOW,
    _MINIMAL.id: _MINIMAL,
}

DEFAULT_STYLE_ID = "classic"

# --------------------------------------------------------------------------- #
# Tuning constants
# --------------------------------------------------------------------------- #
_FONT_FILENAME = "Montserrat-ExtraBold.ttf"

# Defensive cap on the raw headline before any layout — a runaway string can
# never blow up wrapping / metrics work.
_MAX_HEADLINE_CHARS = 180

# Fraction of the canvas width used as the text column (rest is side margin).
_TEXT_WIDTH_FRACTION = 0.86
# Fraction of the canvas height the wrapped headline block is allowed to occupy.
_TEXT_HEIGHT_FRACTION = 0.42
# Headline baseline sits this fraction of the height from the top (lower third).
_TEXT_CENTER_FRACTION = 0.72

# Auto-fit font-size search bounds (px) and step.
_FONT_SIZE_MAX = 150
_FONT_SIZE_MIN = 40
_FONT_SIZE_STEP = 4

# Stroke width as a fraction of font size (clamped to at least 2px).
_STROKE_FRACTION = 0.06
_STROKE_MIN = 2

# Line spacing as a fraction of the font size.
_LINE_SPACING_FRACTION = 0.22

_JPEG_QUALITY = 90


# --------------------------------------------------------------------------- #
# Public: style catalog helpers
# --------------------------------------------------------------------------- #
def get_cover_style(style_id: str | None) -> CoverStyle:
    """Return the preset for ``style_id``, falling back to the default.

    Unknown / ``None`` ids resolve to :data:`DEFAULT_STYLE_ID` so callers never
    have to special-case a bad value.
    """
    if not style_id:
        return COVER_STYLES[DEFAULT_STYLE_ID]
    return COVER_STYLES.get(style_id, COVER_STYLES[DEFAULT_STYLE_ID])


def list_cover_styles() -> list[dict[str, str]]:
    """Return the style catalog as ``[{"id", "name"}, ...]`` for the UI."""
    return [{"id": s.id, "name": s.name} for s in COVER_STYLES.values()]


@dataclass(frozen=True)
class RankedCover:
    """One catalog style scored for a headline — the shape surfaced to the UI.

    ``composite`` is the ranker's tunable ``stop + 0.5*legibility - 0.75*generic``
    score; the raw ``stop_power`` / ``legibility`` / ``is_generic`` signals are
    carried through so a picker can explain *why* a style ranks where it does.
    ``scored`` is ``False`` for a pass-through (degraded) entry with null signals.
    """

    id: str
    name: str
    composite: float
    stop_power: float
    legibility: float
    is_generic: float
    primary_mood: str
    scored: bool


@dataclass(frozen=True)
class CoverRecommendation:
    """The full auto-pick result: the chosen style plus the ranked candidates.

    ``recommended_style`` is always a valid key of :data:`COVER_STYLES` (it falls
    back to :data:`DEFAULT_STYLE_ID` on any degradation). ``degraded`` is ``True``
    when no ``TYPESAFE_API_KEY`` was configured (or the ranker failed), in which
    case ``ranked`` preserves catalog order with unscored (null-signal) entries.
    """

    recommended_style: str
    degraded: bool
    note: str
    ranked: list[RankedCover] = field(default_factory=list)


def _rank_candidates(
    headline: str,
    *,
    has_poster: bool,
    topic: str,
    platform: str,
    audience: str,
):
    """Build one candidate per catalog style and rank them via the cover ranker.

    Returns the raw :class:`app.domains.growth.cover_ranker.CoverRanking` (or
    ``None`` when the catalog is empty). Shared by :func:`recommend_cover` and the
    thin :func:`recommend_cover_style` so the candidate set is built in exactly
    one place.
    """
    from app.domains.growth import cover_ranker

    background = "poster" if has_poster else "gradient"
    candidates = [
        cover_ranker.CoverCandidate(
            id=style.id,
            headline=headline,
            style_name=style.name,
            background=background,
            text_treatment=(
                f"{'uppercase' if style.uppercase else 'mixed-case'} bold headline"
                " with a contrasting stroke over a legibility scrim"
            ),
        )
        for style in COVER_STYLES.values()
    ]
    if not candidates:
        return None
    return cover_ranker.rank_covers_sync(
        candidates,
        cover_ranker.CoverContext(topic=topic, platform=platform, audience=audience),
    )


def recommend_cover(
    headline: str,
    *,
    has_poster: bool = False,
    topic: str = "",
    platform: str = "",
    audience: str = "",
) -> CoverRecommendation:
    """Rank every catalog style for ``headline`` and return the full recommendation.

    Generates one candidate cover per style (the same headline drawn in each style
    over the poster frame or the style gradient) and ranks them with the
    Jev-scored :func:`app.domains.growth.cover_ranker.rank_covers_sync` composite,
    auto-picking the highest-scoring style. The whole ranked list is returned so
    the API / UI can surface *why* one won, not just which one.

    Graceful degradation: with no ``TYPESAFE_API_KEY`` (or on any ranker failure)
    the ranker degrades to a pass-through, ``degraded`` is ``True`` and
    ``recommended_style`` is :data:`DEFAULT_STYLE_ID` — the deterministic default —
    so cover selection never depends on a key being present. The headline is
    treated purely as data by the ranker.
    """
    ranking = _rank_candidates(
        headline,
        has_poster=has_poster,
        topic=topic,
        platform=platform,
        audience=audience,
    )
    if ranking is None:
        return CoverRecommendation(
            recommended_style=DEFAULT_STYLE_ID,
            degraded=True,
            note="No cover styles are configured.",
            ranked=[],
        )

    ranked = [
        RankedCover(
            id=signal.id,
            name=get_cover_style(signal.id).name,
            composite=signal.composite,
            stop_power=signal.stop_power,
            legibility=signal.legibility,
            is_generic=signal.is_generic,
            primary_mood=signal.primary_mood,
            scored=signal.scored,
        )
        for signal in ranking.ranked
    ]
    if ranking.degraded:
        recommended = DEFAULT_STYLE_ID
    else:
        recommended = ranking.recommended_style
        if recommended not in COVER_STYLES:
            recommended = DEFAULT_STYLE_ID
    return CoverRecommendation(
        recommended_style=recommended,
        degraded=ranking.degraded,
        note=ranking.note,
        ranked=ranked,
    )


def recommend_cover_style(
    headline: str,
    *,
    has_poster: bool = False,
    topic: str = "",
    platform: str = "",
    audience: str = "",
) -> str:
    """Recommend the scroll-stopping cover style id for ``headline``.

    Thin convenience wrapper over :func:`recommend_cover` returning just the
    winning style id — always a valid key of :data:`COVER_STYLES`, and
    :data:`DEFAULT_STYLE_ID` whenever the ranker degrades (no ``TYPESAFE_API_KEY``
    or a scoring failure).
    """
    return recommend_cover(
        headline,
        has_poster=has_poster,
        topic=topic,
        platform=platform,
        audience=audience,
    ).recommended_style


# --------------------------------------------------------------------------- #
# Internal: guards & small helpers
# --------------------------------------------------------------------------- #
def _require_pillow() -> None:
    """Raise a clear error if Pillow could not be imported."""
    if not _PIL_AVAILABLE:  # pragma: no cover - only when Pillow is absent
        raise RuntimeError(
            "Pillow (PIL) is required to render covers but is not installed"
        ) from _PIL_IMPORT_ERROR


def _font_path() -> str:
    """Absolute path to the bundled Turkish-safe headline font."""
    return os.path.join(utils.font_dir(), _FONT_FILENAME)


def _clean_headline(headline: str, *, uppercase: bool) -> str:
    """Normalize, length-cap and optionally uppercase the raw headline.

    Collapses internal whitespace, trims, hard-caps the length defensively, then
    applies the style's casing. Turkish casing is handled with an explicit
    ``i`` -> ``İ`` mapping so ``str.upper`` does not fold the dotted/dotless I
    incorrectly (Python's default upper() maps ``i`` -> ``I``).
    """
    text = " ".join((headline or "").split())
    if len(text) > _MAX_HEADLINE_CHARS:
        text = text[:_MAX_HEADLINE_CHARS].rstrip()
    if uppercase and text:
        text = _turkish_upper(text)
    return text


def _turkish_upper(text: str) -> str:
    """Uppercase ``text`` with correct Turkish dotted-I handling."""
    # Map the two Turkish-sensitive lowercase letters first, then upper() the
    # rest. 'i' -> 'İ' (dotted capital I), 'ı' -> 'I' (dotless capital I).
    mapped = text.replace("i", "İ").replace("ı", "I")
    return mapped.upper()


# --------------------------------------------------------------------------- #
# Internal: background rendering
# --------------------------------------------------------------------------- #
def _render_gradient(size: tuple[int, int], top: RGB, bottom: RGB):
    """Return an RGB vertical gradient image from ``top`` to ``bottom``."""
    width, height = size
    base = Image.new("RGB", size, top)
    draw = ImageDraw.Draw(base)
    span = max(height - 1, 1)
    for y in range(height):
        t = y / span
        color = (
            round(top[0] + (bottom[0] - top[0]) * t),
            round(top[1] + (bottom[1] - top[1]) * t),
            round(top[2] + (bottom[2] - top[2]) * t),
        )
        draw.line([(0, y), (width, y)], fill=color)
    return base


def _cover_crop(img, size: tuple[int, int]):
    """Resize ``img`` to fully cover ``size`` (crop overflow), preserving aspect."""
    target_w, target_h = size
    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0:
        return Image.new("RGB", size, (0, 0, 0))

    scale = max(target_w / src_w, target_h / src_h)
    new_w = max(round(src_w * scale), target_w)
    new_h = max(round(src_h * scale), target_h)
    resized = img.resize((new_w, new_h), Image.LANCZOS)

    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def _darken(img, amount: float):
    """Return ``img`` darkened by ``amount`` (0 = unchanged, 1 = black)."""
    amount = min(max(amount, 0.0), 1.0)
    if amount <= 0.0:
        return img
    overlay = Image.new("RGB", img.size, (0, 0, 0))
    return Image.blend(img, overlay, amount)


def _build_background(
    size: tuple[int, int], base_image_path: str | None, style: CoverStyle
):
    """Build the RGB background: cover-cropped darkened poster, else gradient."""
    if base_image_path:
        try:
            with Image.open(base_image_path) as raw:
                poster = raw.convert("RGB")
                cropped = _cover_crop(poster, size)
            return _darken(cropped, style.poster_darken)
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"cover base image not found: {base_image_path}"
            ) from exc
        except OSError as exc:
            raise ValueError(
                f"could not read cover base image {base_image_path!r}: {exc}"
            ) from exc
    return _render_gradient(size, style.gradient_top, style.gradient_bottom)


def _apply_scrim(background, style: CoverStyle):
    """Composite a bottom-to-top black scrim under the headline for legibility.

    The scrim is fully transparent at the top and reaches ``style.scrim_alpha``
    at the bottom, so text in the lower third stays readable over bright poster
    frames or gradients.
    """
    width, height = background.size
    scrim = Image.new("L", (1, height), 0)
    peak = min(max(style.scrim_alpha, 0), 255)
    span = max(height - 1, 1)
    for y in range(height):
        scrim.putpixel((0, y), round(peak * (y / span)))
    alpha = scrim.resize((width, height))

    overlay = Image.new("RGB", background.size, (0, 0, 0))
    return Image.composite(overlay, background, alpha)


# --------------------------------------------------------------------------- #
# Internal: text layout
# --------------------------------------------------------------------------- #
def _line_width(draw, text: str, font) -> int:
    """Pixel width of a single rendered line."""
    left, _, right, _ = draw.textbbox((0, 0), text, font=font)
    return right - left


def _wrap_text(draw, text: str, font, max_width: int) -> list[str]:
    """Greedy word-wrap ``text`` to ``max_width`` px using ``font`` metrics.

    A single word longer than ``max_width`` is placed on its own line rather than
    being dropped — the auto-fit loop is responsible for shrinking the font until
    even long words fit; this function never loses text.
    """
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if _line_width(draw, candidate, font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _block_size(
    draw, lines: list[str], font, line_spacing: int
) -> tuple[int, int]:
    """Return the (width, height) of the wrapped text block."""
    if not lines:
        return (0, 0)
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    width = max(_line_width(draw, line, font) for line in lines)
    height = line_h * len(lines) + line_spacing * (len(lines) - 1)
    return (width, height)


def _fit_lines(
    draw, text: str, font_path: str, max_width: int, max_height: int
) -> tuple[list[str], "_ImageFontModule.FreeTypeFont", int]:
    """Find the largest font size whose wrapped block fits ``max_width``x``max_height``.

    Returns ``(lines, font, line_spacing)``. Falls back to the minimum size (with
    whatever wrapping fits best) if nothing fits cleanly, so rendering always
    proceeds rather than raising on pathological input.
    """
    best: tuple[list[str], object, int] | None = None
    for font_size in range(_FONT_SIZE_MAX, _FONT_SIZE_MIN - 1, -_FONT_SIZE_STEP):
        font = ImageFont.truetype(font_path, font_size)
        line_spacing = round(font_size * _LINE_SPACING_FRACTION)
        lines = _wrap_text(draw, text, font, max_width)
        block_w, block_h = _block_size(draw, lines, font, line_spacing)
        if block_w <= max_width and block_h <= max_height:
            return (lines, font, line_spacing)
        best = (lines, font, line_spacing)  # remember smallest tried so far

    # Nothing fit within bounds; use the smallest size we tried.
    assert best is not None
    lines, font, line_spacing = best
    return (lines, font, line_spacing)  # type: ignore[return-value]


def _draw_headline(
    image, lines: list[str], font, line_spacing: int, style: CoverStyle
) -> None:
    """Draw the wrapped, centered, stroked headline onto ``image`` in place."""
    if not lines:
        return
    draw = ImageDraw.Draw(image)
    width, height = image.size
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    block_h = line_h * len(lines) + line_spacing * (len(lines) - 1)

    center_y = height * _TEXT_CENTER_FRACTION
    top_y = round(center_y - block_h / 2)

    stroke_w = max(round(font.size * _STROKE_FRACTION), _STROKE_MIN)

    y = top_y
    for line in lines:
        draw.text(
            (width / 2, y),
            line,
            font=font,
            fill=style.text_color,
            anchor="ma",  # middle-ascender: horizontally centered, top-aligned
            stroke_width=stroke_w,
            stroke_fill=style.stroke_color,
        )
        y += line_h + line_spacing


# --------------------------------------------------------------------------- #
# Public: render entry point
# --------------------------------------------------------------------------- #
def generate_cover(
    headline: str,
    out_path: str,
    *,
    base_image_path: str | None = None,
    style: str = DEFAULT_STYLE_ID,
    size: tuple[int, int] = (1080, 1920),
) -> str:
    """Render a cover/thumbnail JPEG and return ``out_path``.

    Parameters
    ----------
    headline:
        The hook headline to overlay. Normalized, length-capped and (per style)
        uppercased before layout; an empty headline renders just the styled
        background + scrim.
    out_path:
        Destination JPEG path. Parent directories are created if needed.
    base_image_path:
        Optional poster frame used as the background (cover-cropped + darkened).
        When ``None`` the style's own gradient is rendered instead.
    style:
        Style id (see :data:`COVER_STYLES`); unknown ids fall back to the default.
    size:
        Output canvas size, default ``(1080, 1920)`` (vertical 9:16).

    Raises
    ------
    RuntimeError
        If Pillow is not installed.
    FileNotFoundError / ValueError
        If ``base_image_path`` is given but cannot be opened / decoded.
    """
    _require_pillow()

    if not isinstance(size, (tuple, list)) or len(size) != 2:
        raise ValueError(f"size must be a (width, height) tuple, got {size!r}")
    width, height = int(size[0]), int(size[1])
    if width <= 0 or height <= 0:
        raise ValueError(f"size must be positive, got {(width, height)!r}")
    canvas_size = (width, height)

    preset = get_cover_style(style)
    text = _clean_headline(headline, uppercase=preset.uppercase)

    # 1) Background (poster or gradient) then legibility scrim.
    background = _build_background(canvas_size, base_image_path, preset)
    composed = _apply_scrim(background, preset)

    # 2) Auto-fit + wrap the headline, then draw it stroked and centered.
    if text:
        draw = ImageDraw.Draw(composed)
        max_text_w = round(width * _TEXT_WIDTH_FRACTION)
        max_text_h = round(height * _TEXT_HEIGHT_FRACTION)
        lines, font, line_spacing = _fit_lines(
            draw, text, _font_path(), max_text_w, max_text_h
        )
        _draw_headline(composed, lines, font, line_spacing, preset)

    # 3) Persist as JPEG.
    parent = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(parent, exist_ok=True)
    composed.save(out_path, format="JPEG", quality=_JPEG_QUALITY)
    return out_path


__all__ = [
    "CoverStyle",
    "COVER_STYLES",
    "DEFAULT_STYLE_ID",
    "RankedCover",
    "CoverRecommendation",
    "get_cover_style",
    "list_cover_styles",
    "recommend_cover",
    "recommend_cover_style",
    "generate_cover",
]
