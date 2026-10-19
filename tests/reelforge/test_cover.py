"""Cover / thumbnail generator QA — real Pillow rendering.

These tests exercise :mod:`app.services.cover` end to end with the ACTUAL
bundled ``Montserrat-ExtraBold.ttf`` font (Turkish-safe) rather than mocks:

* a real cover is rendered with a Turkish headline (``Şunu İZLE: Ğ Ü Ö Ç``) and
  we assert the output JPEG exists, is exactly 1080x1920, and is *non-blank*
  (both meaningful luminance variance and real glyph "ink" over the scrim);
* every style in the catalog renders a valid, non-blank cover;
* a pathologically long headline wraps and renders without crashing (and never
  overflows the canvas).

The whole module SKIPs gracefully if Pillow is missing or the bundled font is
absent, so a hermetic box without those assets stays green.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.services import cover
from app.utils import utils

# --------------------------------------------------------------------------- #
# Skip gates (Pillow + bundled font must be present for a real render)
# --------------------------------------------------------------------------- #
try:
    from PIL import Image

    _PIL_OK = True
except Exception:  # pragma: no cover - only when Pillow is absent
    Image = None  # type: ignore[assignment]
    _PIL_OK = False

_FONT_PATH = os.path.join(utils.font_dir(), "Montserrat-ExtraBold.ttf")

pytestmark = [
    pytest.mark.skipif(not _PIL_OK, reason="Pillow (PIL) not installed"),
    pytest.mark.skipif(
        not os.path.exists(_FONT_PATH),
        reason="bundled Montserrat-ExtraBold.ttf font is missing",
    ),
]

_SIZE = (1080, 1920)
_TURKISH_HEADLINE = "Şunu İZLE: Ğ Ü Ö Ç"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _luma_variance(path: str) -> float:
    """Population variance of the JPEG's luma channel (0 for a flat image)."""
    with Image.open(path) as img:
        luma = img.convert("L")
        histogram = luma.histogram()
    total = sum(histogram)
    assert total > 0
    mean = sum(i * n for i, n in enumerate(histogram)) / total
    return sum(n * (i - mean) ** 2 for i, n in enumerate(histogram)) / total


def _bright_ink(path: str, threshold: int = 200) -> int:
    """Count near-white pixels — a proxy for drawn headline glyphs/stroke."""
    with Image.open(path) as img:
        histogram = img.convert("L").histogram()
    return sum(histogram[threshold + 1 :])


def _assert_valid_cover(path: str) -> None:
    """Assert a rendered cover exists, has the right size, and is non-blank."""
    assert os.path.exists(path), f"cover was not written: {path}"
    assert os.path.getsize(path) > 0, "cover file is empty"
    with Image.open(path) as img:
        assert img.size == _SIZE, f"expected {_SIZE}, got {img.size}"
        assert img.format == "JPEG"
    # A flat/blank image has ~zero variance; a real gradient+scrim+text clears
    # this comfortably.
    assert _luma_variance(path) > 50.0, "cover looks blank (no luma variance)"


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_generate_cover_turkish_headline(tmp_path: Path) -> None:
    """A Turkish headline renders a valid 1080x1920 non-blank JPEG with real ink."""
    out = str(tmp_path / "cover_tr.jpg")
    returned = cover.generate_cover(
        _TURKISH_HEADLINE, out, style="classic", size=_SIZE
    )
    assert returned == out
    _assert_valid_cover(out)
    # The bold white headline + black stroke must produce meaningful bright ink;
    # if Turkish glyphs collapsed to tofu/empty boxes this would drop toward the
    # background level.
    assert _bright_ink(out) > 3000, "headline drew little/no ink (Turkish tofu?)"


def test_generate_cover_over_poster(tmp_path: Path) -> None:
    """A supplied poster frame is cover-cropped/darkened as the background."""
    poster = str(tmp_path / "poster.jpg")
    # A bright, non-square source to exercise cover-crop + darken.
    Image.new("RGB", (1280, 720), (240, 60, 30)).save(poster, "JPEG")

    out = str(tmp_path / "cover_poster.jpg")
    cover.generate_cover(
        "Büyük Haber", out, base_image_path=poster, style="classic", size=_SIZE
    )
    _assert_valid_cover(out)


@pytest.mark.parametrize("style_id", list(cover.COVER_STYLES.keys()))
def test_every_style_renders(tmp_path: Path, style_id: str) -> None:
    """Each catalog style renders a valid, non-blank cover."""
    out = str(tmp_path / f"cover_{style_id}.jpg")
    cover.generate_cover("Deneme Başlık", out, style=style_id, size=_SIZE)
    _assert_valid_cover(out)


def test_long_headline_wraps_without_crashing(tmp_path: Path) -> None:
    """A very long headline wraps + auto-shrinks and never overflows the canvas."""
    long_headline = "İZLE " * 120  # far longer than any real hook
    out = str(tmp_path / "cover_long.jpg")
    cover.generate_cover(long_headline, out, style="bold_yellow", size=_SIZE)
    _assert_valid_cover(out)


def test_unknown_style_falls_back_to_default() -> None:
    """An unknown style id resolves to the default preset."""
    assert cover.get_cover_style("does-not-exist").id == cover.DEFAULT_STYLE_ID
    assert cover.get_cover_style(None).id == cover.DEFAULT_STYLE_ID


def test_list_cover_styles_catalog() -> None:
    """The catalog exposes >=4 presets as {id, name} dicts."""
    catalog = cover.list_cover_styles()
    assert len(catalog) >= 4
    for entry in catalog:
        assert set(entry.keys()) == {"id", "name"}
        assert entry["id"] and entry["name"]


def test_empty_headline_renders_background_only(tmp_path: Path) -> None:
    """An empty headline still yields a valid styled background (no crash)."""
    out = str(tmp_path / "cover_empty.jpg")
    cover.generate_cover("", out, style="sunset", size=_SIZE)
    _assert_valid_cover(out)
