"""Bundled caption-font verification for ReelForge (plan §3.4 / §5 Stage 4).

libass renders CapCut-style karaoke captions from ``resource/fonts`` (passed to
ffmpeg as ``fontsdir``). These tests guarantee the bundled fonts:

- physically exist as real TrueType files (not stray HTML error pages),
- cover the full Turkish glyph set (İ Ğ Ş Ü Ö Ç and lowercase ı ğ ş …) so
  Turkish captions never render tofu, and
- expose a family name that matches ``KaraokeStyle.font`` so libass actually
  selects the bold face instead of falling back.

``fontTools`` is required for the cmap inspection; the module is skipped (not
errored) when it is unavailable so the rest of the suite still collects.
"""

from __future__ import annotations

import os

import pytest

from app.services.captions.ass_karaoke import KaraokeStyle
from app.utils.utils import font_dir

fontTools_ttLib = pytest.importorskip("fontTools.ttLib")
TTFont = fontTools_ttLib.TTFont

# Turkish codepoints that MUST be present to avoid tofu in captions.
TURKISH_CODEPOINTS: dict[int, str] = {
    0x0130: "İ",  # LATIN CAPITAL LETTER I WITH DOT ABOVE
    0x011E: "Ğ",  # LATIN CAPITAL LETTER G WITH BREVE
    0x015E: "Ş",  # LATIN CAPITAL LETTER S WITH CEDILLA
    0x00DC: "Ü",  # LATIN CAPITAL LETTER U WITH DIAERESIS
    0x00D6: "Ö",  # LATIN CAPITAL LETTER O WITH DIAERESIS
    0x00C7: "Ç",  # LATIN CAPITAL LETTER C WITH CEDILLA
    0x0131: "ı",  # LATIN SMALL LETTER DOTLESS I
    0x011F: "ğ",  # LATIN SMALL LETTER G WITH BREVE
    0x015F: "ş",  # LATIN SMALL LETTER S WITH CEDILLA
    0x00FC: "ü",  # LATIN SMALL LETTER U WITH DIAERESIS
    0x00F6: "ö",  # LATIN SMALL LETTER O WITH DIAERESIS
    0x00E7: "ç",  # LATIN SMALL LETTER C WITH CEDILLA
}

# Bundled OFL-licensed static instances (filename -> expected NameID-1 family).
BUNDLED_FONTS: dict[str, str] = {
    "Montserrat-ExtraBold.ttf": "Montserrat ExtraBold",
    "Inter-Bold.ttf": "Inter",
}

# Minimum plausible size for a real static TTF (guards against HTML 404 pages).
_MIN_TTF_BYTES = 50 * 1024


def _font_path(filename: str) -> str:
    return os.path.join(font_dir(), filename)


@pytest.mark.parametrize("filename", sorted(BUNDLED_FONTS))
def test_bundled_font_file_exists(filename: str) -> None:
    """The bundled font is present and large enough to be a real TTF."""
    path = _font_path(filename)
    assert os.path.isfile(path), f"missing bundled font: {path}"
    size = os.path.getsize(path)
    assert size > _MIN_TTF_BYTES, f"{filename} too small ({size} bytes) — HTML error page?"


@pytest.mark.parametrize("filename", sorted(BUNDLED_FONTS))
def test_bundled_font_is_valid_truetype(filename: str) -> None:
    """The file parses as a TrueType/OpenType font and has a ``cmap``."""
    font = TTFont(_font_path(filename))
    assert font.getBestCmap(), f"{filename} has no usable cmap"


@pytest.mark.parametrize("filename,expected_family", sorted(BUNDLED_FONTS.items()))
def test_bundled_font_family_name(filename: str, expected_family: str) -> None:
    """The font reports the expected family name (NameID 1)."""
    font = TTFont(_font_path(filename))
    family = font["name"].getDebugName(1)
    assert family == expected_family, f"{filename}: family {family!r} != {expected_family!r}"


@pytest.mark.parametrize("filename", sorted(BUNDLED_FONTS))
def test_bundled_font_covers_turkish(filename: str) -> None:
    """Every Turkish codepoint is present in the font's cmap (no tofu)."""
    cmap = TTFont(_font_path(filename)).getBestCmap()
    missing = [
        f"U+{cp:04X} {ch}" for cp, ch in TURKISH_CODEPOINTS.items() if cp not in cmap
    ]
    assert not missing, f"{filename} missing Turkish glyphs: {missing}"


def test_ofl_licenses_present() -> None:
    """Each bundled family ships its OFL license text alongside the TTF."""
    for license_name in ("OFL-Montserrat.txt", "OFL-Inter.txt"):
        path = _font_path(license_name)
        assert os.path.isfile(path), f"missing license: {path}"
        assert os.path.getsize(path) > 0, f"empty license: {path}"


def test_karaoke_style_font_matches_bundled_family() -> None:
    """``KaraokeStyle.font`` default resolves to a bundled font family name.

    This is what lets libass find the bold caption face via ``fontsdir``.
    """
    bundled_families = set(BUNDLED_FONTS.values())
    assert (
        KaraokeStyle().font in bundled_families
    ), f"KaraokeStyle.font {KaraokeStyle().font!r} not in bundled families {bundled_families}"
