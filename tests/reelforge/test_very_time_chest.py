"""Chest-text check (Very ___ Time gap item 6): OCR, re-roll cap, clean overlay.

Real-OCR tests run RapidOCR on PIL-made fixtures (skipped when the package is
not installed); the re-roll and overlay rules run on a fake OCR.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.domains.film import chest_check as cc
from app.domains.film.chest_check import OcrLine, OcrUnavailable

FONTS = Path(__file__).resolve().parents[2] / "apps" / "api" / "assets" / "resource" / "fonts"
EXPECTED = "very Turkish time"
OXBLOOD = (74, 14, 14)

needs_ocr = pytest.mark.skipif(not cc.ocr_available(), reason="rapidocr-onnxruntime not installed")


def _shirt(text: str | None, size=(720, 1280)) -> bytes:
    """A grey backdrop with a dark oxblood shirt block and (optionally) ivory chest text."""
    image = Image.new("RGB", size, (128, 128, 128))
    draw = ImageDraw.Draw(image)
    w, h = size
    draw.rectangle((int(w * 0.12), int(h * 0.35), int(w * 0.88), int(h * 0.95)), fill=OXBLOOD)
    if text:
        font = ImageFont.truetype(str(FONTS / "Inter-Bold.ttf"), 54)
        draw.text((w / 2, h * 0.55), text, font=font, fill=cc.IVORY, anchor="mm")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


@pytest.fixture(scope="module")
def right() -> bytes:
    return _shirt(EXPECTED)


@pytest.fixture(scope="module")
def misspelled() -> bytes:
    return _shirt("vrey Turksh tmie")


@pytest.fixture(scope="module")
def blank() -> bytes:
    return _shirt(None)


def _size(image: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(image)) as im:
        return im.size


# --------------------------------------------------------------------------- #
# Real OCR
# --------------------------------------------------------------------------- #
@needs_ocr
def test_read_text_finds_the_chest_text(right):
    lines = cc.read_text(right)
    assert any(cc.normalise(line.text) == "very turkish time" for line in lines)
    line = next(line for line in lines if "turkish" in cc.normalise(line.text))
    x0, y0, x1, y1 = line.box
    assert 0 <= x0 < x1 <= 720 and 0 <= y0 < y1 <= 1280
    assert 0 < line.score <= 1


@needs_ocr
def test_text_matches_accepts_right_and_rejects_misspelled(right, misspelled, blank):
    ok, read, box = cc.text_matches(EXPECTED, cc.read_text(right))
    assert ok and box is not None and "Turkish" in read
    ok, read, box = cc.text_matches(EXPECTED, cc.read_text(misspelled))
    assert not ok and box is not None
    ok, read, box = cc.text_matches(EXPECTED, cc.read_text(blank))
    assert not ok and read == "" and box is None


@needs_ocr
def test_overlay_over_a_misspelled_box_reads_correctly(misspelled):
    _, _, box = cc.text_matches(EXPECTED, cc.read_text(misspelled))
    fixed = cc.overlay_text(misspelled, EXPECTED, box=box)
    assert _size(fixed) == (720, 1280)
    ok, _, _ = cc.text_matches(EXPECTED, cc.read_text(fixed))
    assert ok


@needs_ocr
def test_overlay_without_a_box_reads_correctly(blank):
    fixed = cc.overlay_text(blank, EXPECTED, region=(0.5, 0.6))
    ok, _, box = cc.text_matches(EXPECTED, cc.read_text(fixed))
    assert ok and box is not None
    assert abs((box[1] + box[3]) / 2 - 1280 * 0.6) < 80


@needs_ocr
def test_verify_chest_end_to_end_with_real_ocr(right, misspelled):
    images = {11: misspelled, 11 + 1009: right}
    result = cc.verify_chest(lambda seed: images[seed], expected=EXPECTED, seed=11, max_rerolls=2)
    assert (result.status, result.attempts, result.seed) == ("rerolled", 2, 1020)


# --------------------------------------------------------------------------- #
# Matching rules (no OCR)
# --------------------------------------------------------------------------- #
def _line(text: str, box=(100, 600, 600, 660)) -> OcrLine:
    return OcrLine(text=text, box=box, score=0.99)


def test_normalise_is_turkish_aware():
    assert cc.normalise("Very TÜRKİSH tıme!") == "very turkish time"
    assert cc.normalise("ÇAY  saati") == "cay saati"
    assert cc.normalise("İSTANBUL") == cc.normalise("istanbul") == cc.normalise("ıstanbul")


def test_text_matches_turkish_casing_and_small_ocr_noise():
    assert cc.text_matches("çok Türk zamanı", [_line("COK TURK ZAMANI")])[0]
    assert cc.text_matches(EXPECTED, [_line("very Turklsh time")])[0]
    assert not cc.text_matches(EXPECTED, [_line("very German time")])[0]
    assert not cc.text_matches("", [_line("anything")])[0]


def test_text_matches_joins_two_wrapped_lines_and_returns_the_union_box():
    lines = [_line("very Turkish", (100, 600, 500, 650)), _line("time", (250, 660, 360, 710))]
    ok, read, box = cc.text_matches(EXPECTED, lines)
    assert ok and read == "very Turkish time" and box == (100, 600, 500, 710)


# --------------------------------------------------------------------------- #
# verify_chest with a fake OCR
# --------------------------------------------------------------------------- #
class FakeGen:
    def __init__(self, image: bytes, fail_on: set[int] | None = None):
        self.image = image
        self.seeds: list[int] = []
        self.fail_on = fail_on or set()

    def __call__(self, seed: int) -> bytes:
        if seed in self.fail_on:
            raise RuntimeError("provider down")
        self.seeds.append(seed)
        return self.image


def _ocr(reads: list[str]):
    """Fake OCR returning the scripted reads in order (one per call)."""
    calls = iter(reads)

    def read(_image: bytes) -> list[OcrLine]:
        text = next(calls)
        return [_line(text)] if text else []

    return read


def test_ok_on_first_try_calls_generate_once(blank):
    gen = FakeGen(blank)
    result = cc.verify_chest(gen, expected=EXPECTED, seed=7, max_rerolls=3, ocr=_ocr([EXPECTED]))
    assert (result.status, result.attempts, result.seed, result.read) == ("ok", 1, 7, EXPECTED)
    assert gen.seeds == [7] and result.image == blank


def test_reroll_then_ok(blank):
    gen = FakeGen(blank)
    result = cc.verify_chest(gen, expected=EXPECTED, seed=7, max_rerolls=3,
                             ocr=_ocr(["vrey Turksh tmie", "very Turkish time"]))
    assert (result.status, result.attempts, result.seed) == ("rerolled", 2, 7 + 1009)
    assert gen.seeds == [7, 1016]


@pytest.mark.parametrize("cap", [0, 1, 2, 5])
def test_cap_reached_overlays_with_exactly_cap_plus_one_generations(blank, cap):
    gen = FakeGen(blank)
    result = cc.verify_chest(gen, expected=EXPECTED, seed=3, max_rerolls=cap, ocr=_ocr(["wrong"] * (cap + 1)))
    assert result.status == "overlay"
    assert len(gen.seeds) == result.attempts == cap + 1
    assert gen.seeds == [3 + 1009 * k for k in range(cap + 1)]
    assert result.image != blank and _size(result.image) == _size(blank)


def test_cap_is_clamped_to_five(blank):
    gen = FakeGen(blank)
    result = cc.verify_chest(gen, expected=EXPECTED, seed=1, max_rerolls=99, ocr=_ocr(["x"] * 10))
    assert result.status == "overlay" and len(gen.seeds) == 6
    gen = FakeGen(blank)
    cc.verify_chest(gen, expected=EXPECTED, seed=1, max_rerolls=-3, ocr=_ocr(["x"]))
    assert len(gen.seeds) == 1


def test_unchecked_when_ocr_is_unavailable(blank):
    gen = FakeGen(blank)

    def no_ocr(_image: bytes):
        raise OcrUnavailable("not installed")

    result = cc.verify_chest(gen, expected=EXPECTED, seed=5, max_rerolls=3, ocr=no_ocr)
    assert (result.status, result.attempts, result.image) == ("unchecked", 1, blank)
    assert gen.seeds == [5]


def test_generate_failure_on_reroll_overlays_the_last_good_image(blank):
    gen = FakeGen(blank, fail_on={5 + 1009 * 2})
    result = cc.verify_chest(gen, expected=EXPECTED, seed=5, max_rerolls=4, ocr=_ocr(["bad", "bad"]))
    assert result.status == "overlay" and result.attempts == 2 and result.seed == 5 + 1009
    assert gen.seeds == [5, 1014]
    assert _size(result.image) == _size(blank)


def test_overlay_keeps_size_for_any_image(misspelled):
    small = Image.new("RGB", (300, 400), (10, 10, 10))
    buf = io.BytesIO()
    small.save(buf, format="JPEG")
    assert _size(cc.overlay_text(buf.getvalue(), EXPECTED)) == (300, 400)
    out = cc.overlay_text(misspelled, EXPECTED, box=(150, 640, 570, 700))
    assert _size(out) == (720, 1280)
    with Image.open(io.BytesIO(out)) as im:
        assert im.format == "PNG"


def test_max_rerolls_from_env(monkeypatch):
    monkeypatch.delenv(cc.REROLLS_ENV, raising=False)
    assert cc.max_rerolls_from_env() == 2
    assert cc.max_rerolls_from_env(default=9) == 5
    for raw, want in (("0", 0), ("3", 3), ("12", 5), ("-1", 0), ("abc", 2), ("", 2)):
        monkeypatch.setenv(cc.REROLLS_ENV, raw)
        assert cc.max_rerolls_from_env() == want
