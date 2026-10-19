"""Turkish glyph QA — CTO plan §5 Stage 4.

Renders the Turkish stress string ``İĞÜŞÖÇ ığüşöç`` as a real karaoke ``.ass``
caption, burns it with the ACTUAL ffmpeg + libass using the BUNDLED font
directory (``resource/fonts``), then loads the resulting PNG frame and asserts
the caption drew a meaningful amount of glyph ink — i.e. the dotted/dotless I,
soft-G, cedilla and umlaut glyphs actually rendered rather than collapsing to
nothing (a missing-glyph "tofu"/empty box).

Determinism:
- Single ``color`` background of a fixed size, single output frame at ``t=0``.
- Ink is counted as the number of non-background (bright) pixels in the frame,
  compared against an ASCII control of equal character count so the assertion is
  self-calibrating rather than a magic absolute number.

The whole module auto-SKIPs when the ffmpeg build lacks the ``ass`` filter
(reusing :func:`app.services.compose.compose_ffmpeg.ffmpeg_has_filter`) so a
hermetic CI box without libass stays green; on CI with libass present it runs
for real.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services.captions.ass_karaoke import KaraokeStyle, write_ass
from app.services.captions.words import WordTiming
from app.services.compose.compose_ffmpeg import (
    _escape_ass_filter_path,
    ffmpeg_has_filter,
)
from app.utils import utils

# --------------------------------------------------------------------------- #
# Test data / tuning
# --------------------------------------------------------------------------- #
# Upper- and lower-case Turkish-specific glyphs in one string (the §5 Stage 4
# stress case): dotted-İ, soft-Ğ, Ü, Ş, Ö, Ç and their lowercase forms.
_TURKISH_WORDS: tuple[str, str] = ("İĞÜŞÖÇ", "ığüşöç")
# ASCII control with the SAME character count (6 + 6) so we can compare ink
# volume without hard-coding a brittle absolute pixel threshold.
_ASCII_WORDS: tuple[str, str] = ("ABCDEF", "abcdef")

_FRAME_W: int = 1080
_FRAME_H: int = 1920
# Pixels brighter than this (0-255 luma) count as rendered ink; the background
# is solid black (luma 0), so any glyph fill/outline clears this easily.
_INK_LUMA_THRESHOLD: int = 40
# A blank background must produce essentially no ink; allow a tiny margin for
# PNG rounding rather than demanding an exact zero.
_BLANK_INK_MAX: int = 50
# Rendered Turkish glyphs must carry at least this fraction of the ASCII
# control's ink — catches the "glyph missing → nothing drawn" failure mode.
_MIN_TURKISH_RATIO: float = 0.4

_FFMPEG: str = utils.get_ffmpeg_binary()

pytestmark = pytest.mark.skipif(
    not ffmpeg_has_filter("ass", _FFMPEG),
    reason="ffmpeg build lacks the libass 'ass' filter",
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _write_caption(path: Path, words: tuple[str, str]) -> str:
    """Write a one-line karaoke ``.ass`` for ``words`` via the prod generator.

    Uses ``upper=False`` so the exact stress string (both cases) is preserved,
    and the default :class:`KaraokeStyle` so the BUNDLED "Montserrat ExtraBold"
    font is what libass is asked to resolve from ``fontsdir``.
    """
    line = [
        WordTiming(words[0], 0.0, 0.5),
        WordTiming(words[1], 0.5, 1.0),
    ]
    return write_ass(str(path), [line], style=KaraokeStyle(), upper=False)


def _render_frame(png_path: Path, ass_path: Path | None) -> None:
    """Burn ``ass_path`` (if any) over a solid-black frame to a single PNG.

    Renders exactly one frame at ``t=0`` (the caption line starts at 0.0, so it
    is active) with ``fontsdir`` pointed at the bundled ``resource/fonts`` — the
    same libass path production uses.
    """
    cmd: list[str] = [
        _FFMPEG,
        "-y",
        "-hide_banner",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:size={_FRAME_W}x{_FRAME_H}:rate=25:duration=1",
    ]
    if ass_path is not None:
        esc_ass = _escape_ass_filter_path(str(ass_path))
        esc_fonts = _escape_ass_filter_path(utils.font_dir())
        cmd += ["-vf", f"ass={esc_ass}:fontsdir={esc_fonts}"]
    cmd += ["-frames:v", "1", str(png_path)]

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not png_path.exists():
        stderr = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"ffmpeg frame render failed: {stderr}")


def _ink_pixels(png_path: Path) -> int:
    """Count non-background (bright) pixels in the rendered PNG frame."""
    # Pillow is a hard dependency of this QA test; import locally so collection
    # yields a clear error only if it is genuinely missing at run time.
    from PIL import Image

    with Image.open(png_path) as img:
        luma = img.convert("L")
        histogram = luma.histogram()  # 256 luma buckets
    return sum(histogram[_INK_LUMA_THRESHOLD + 1 :])


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_blank_background_has_no_ink(tmp_path: Path) -> None:
    """Control: the bare background renders essentially zero ink.

    Proves the ink metric measures glyphs and not a non-black background, so the
    Turkish assertion below cannot pass on a false positive.
    """
    frame = tmp_path / "blank.png"
    _render_frame(frame, ass_path=None)
    assert _ink_pixels(frame) <= _BLANK_INK_MAX


def test_turkish_glyphs_render_non_tofu(tmp_path: Path) -> None:
    """``İĞÜŞÖÇ ığüşöç`` burns with real, non-empty glyph ink via the bundled font.

    The Turkish string and an equal-length ASCII control are each burned over an
    identical black frame. Turkish ink must be meaningful in absolute terms AND a
    substantial fraction of the ASCII control's ink — if any Turkish glyph were
    missing and libass drew nothing, the Turkish ink would collapse toward zero
    and fail the ratio check.
    """
    ascii_ass = tmp_path / "ascii.ass"
    turkish_ass = tmp_path / "turkish.ass"
    _write_caption(ascii_ass, _ASCII_WORDS)
    _write_caption(turkish_ass, _TURKISH_WORDS)

    ascii_png = tmp_path / "ascii.png"
    turkish_png = tmp_path / "turkish.png"
    _render_frame(ascii_png, ascii_ass)
    _render_frame(turkish_png, turkish_ass)

    ascii_ink = _ink_pixels(ascii_png)
    turkish_ink = _ink_pixels(turkish_png)

    # The ASCII control must itself have drawn — otherwise the render pipeline is
    # broken and the Turkish comparison is meaningless.
    assert ascii_ink > _BLANK_INK_MAX, (
        f"ASCII control drew no ink ({ascii_ink} px); render pipeline broken"
    )
    # Turkish must have drawn meaningful ink (not empty / tofu).
    assert turkish_ink > _BLANK_INK_MAX, (
        f"Turkish caption drew no glyph ink ({turkish_ink} px) — likely a "
        f"missing-glyph tofu/empty box in the bundled font"
    )
    # ...and it must be comparable to the ASCII control, proving every Turkish
    # glyph carried real outline area rather than collapsing to nothing.
    assert turkish_ink >= _MIN_TURKISH_RATIO * ascii_ink, (
        f"Turkish ink {turkish_ink} px is under {_MIN_TURKISH_RATIO:.0%} of the "
        f"ASCII control {ascii_ink} px — Turkish glyphs likely did not render"
    )
