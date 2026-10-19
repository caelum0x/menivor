"""Burn/preview parity for the shared caption engine.

The web caption preview renders ASS from the shared ``reelforge_caption_engine``
registry (``@reelforge/caption-engine``). The API burn-in service must produce
the SAME bytes for those presets, otherwise the previewed caption and the burned
subtitle drift. These tests pin the service's shared-engine renderer
(``ass_karaoke.build_ass_engine``) to the golden ``.ass`` fixtures that the
TypeScript port is also held to, so any divergence between the two burn/preview
implementations fails CI.

They also cover the two burn-specific concerns the wiring adds: bundled-font
substitution (so libass resolves a real face) and Turkish-safe uppercasing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.captions._engine import caption_engine
from app.services.captions.ass_karaoke import (
    BURN_FONT_SUBSTITUTIONS,
    build_ass_engine,
    engine_preset_ids,
)

# Golden fixtures live with the shared package (the byte-exact cross-language
# contract). tests/reelforge/ -> parents[2] is the repo root.
_GOLDEN = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "caption-engine"
    / "test"
    / "fixtures"
    / "golden"
)

pytestmark = pytest.mark.skipif(
    caption_engine() is None,
    reason="shared reelforge_caption_engine package is not importable",
)


def _golden_words() -> list[dict]:
    return json.loads((_GOLDEN / "words.json").read_text())


@pytest.mark.parametrize(
    "preset", ["hormozi", "karaoke-classic", "minimal-top-label", "brainrot-popin"]
)
def test_burn_matches_golden_preview(preset: str) -> None:
    """The service burn reproduces the golden preview ASS byte-for-byte."""
    got = build_ass_engine(_golden_words(), preset)
    expected = (_GOLDEN / f"{preset}.ass").read_text()
    assert got == expected, f"burn drifted from the {preset} preview golden"


def test_engine_preset_ids_cover_the_golden_registry() -> None:
    """The service exposes exactly the shared registry the preview renders."""
    on_disk = sorted(p.stem for p in _GOLDEN.glob("*.ass"))
    assert sorted(engine_preset_ids()) == on_disk


def test_default_words_are_uppercased_ascii_identically() -> None:
    """Hormozi uppercases ASCII exactly like the golden (no Turkish regression)."""
    ass = build_ass_engine(_golden_words(), "hormozi")
    assert "MAKE" in ass and "YOUR" in ass and "TODAY" in ass


def test_engine_uppercase_is_naive_matching_the_golden_contract() -> None:
    """The shared engine uppercases naively (locale-safe casing is the caller's job).

    Turkish-locale uppercasing (``i -> İ``) cannot live in the shared engine
    without corrupting ASCII English ("first" -> "FİRST") and breaking the golden
    byte-contract. The burn caller (clipping ``_write_captions``) therefore
    pre-applies ``turkish_upper`` and disables the engine's naive upper for
    Turkish clips; the engine itself stays byte-identical to the preview.
    """
    words = [{"text": "first", "start": 0.0, "end": 0.4}]
    ass = build_ass_engine(words, "hormozi")  # hormozi preset uppercases
    assert "FIRST" in ass  # naive upper, exactly like the golden/preview


def test_font_substitution_targets_a_bundled_face_only_when_requested() -> None:
    """``fonts=`` swaps the display weight for a bundled family; default keeps it."""
    preview = build_ass_engine(_golden_words(), "hormozi")
    burned = build_ass_engine(
        _golden_words(), "hormozi", fonts=BURN_FONT_SUBSTITUTIONS
    )
    # Preview keeps the preset's web font; the burn maps it to the bundled face.
    assert "Montserrat Black" in preview
    assert "Montserrat ExtraBold" in burned
    assert "Montserrat Black" not in burned


def test_upper_override_forces_case() -> None:
    """``upper=False`` overrides an uppercasing preset (and vice versa)."""
    words = [{"text": "keep", "start": 0.0, "end": 0.3}]
    lowered = build_ass_engine(words, "hormozi", upper=False)
    assert "keep" in lowered and "KEEP" not in lowered


def test_hormozi_cue_style_single_sources_from_shared_preset() -> None:
    """``hormozi.hormozi_style`` mirrors the shared ``hormozi`` preset."""
    from app.services.captions.hormozi import hormozi_style

    engine = caption_engine()
    preset = engine.get_preset("hormozi")
    style = hormozi_style()
    assert style.font == preset.font  # "Montserrat Black", not the old ExtraBold
    assert style.highlight_hex == preset.highlight_hex
    assert style.base_hex == preset.primary_hex
    assert style.max_per_group == preset.words_per_group
    # Accent override still honoured.
    assert hormozi_style("#00FF00").highlight_hex == "#00FF00"
