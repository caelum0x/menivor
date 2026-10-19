"""Tests for the CapCut-style caption STYLE PRESETS registry."""

from __future__ import annotations

import dataclasses

import pytest

from app.services.captions.ass_karaoke import KaraokeStyle, build_ass
from app.services.captions.presets import (
    CAPTION_STYLE_PRESETS,
    DEFAULT_CAPTION_STYLE,
    get_caption_style,
    list_caption_styles,
)
from app.services.captions.words import WordTiming

_EXPECTED_IDS = {"karaoke_yellow", "karaoke_green", "clean_white", "bold_violet"}


def test_registry_has_expected_presets() -> None:
    assert _EXPECTED_IDS.issubset(set(CAPTION_STYLE_PRESETS))
    assert len(CAPTION_STYLE_PRESETS) >= 4


def test_all_presets_are_frozen_karaoke_styles() -> None:
    for style_id, style in CAPTION_STYLE_PRESETS.items():
        assert isinstance(style, KaraokeStyle), style_id
        # Frozen dataclass: mutation must raise.
        with pytest.raises(dataclasses.FrozenInstanceError):
            style.outline = 99  # type: ignore[misc]


def test_default_style_id_is_registered() -> None:
    assert DEFAULT_CAPTION_STYLE == "karaoke_yellow"
    assert DEFAULT_CAPTION_STYLE in CAPTION_STYLE_PRESETS


def test_karaoke_yellow_matches_library_default() -> None:
    default = CAPTION_STYLE_PRESETS["karaoke_yellow"]
    assert default.primary == "&H00FFFFFF"
    assert default.secondary == "&H0000FFFF"
    # The default preset should render identically to KaraokeStyle().
    assert default == KaraokeStyle()


def test_presets_differ_in_colours() -> None:
    yellow = CAPTION_STYLE_PRESETS["karaoke_yellow"]
    green = CAPTION_STYLE_PRESETS["karaoke_green"]
    violet = CAPTION_STYLE_PRESETS["bold_violet"]
    clean = CAPTION_STYLE_PRESETS["clean_white"]

    assert green.secondary != yellow.secondary
    assert violet.secondary not in {yellow.secondary, green.secondary}
    # clean_white has no highlight colour flip.
    assert clean.primary == clean.secondary == "&H00FFFFFF"


def test_bold_violet_has_heavier_outline() -> None:
    violet = CAPTION_STYLE_PRESETS["bold_violet"]
    clean = CAPTION_STYLE_PRESETS["clean_white"]
    assert violet.outline > CAPTION_STYLE_PRESETS["karaoke_yellow"].outline
    assert clean.outline < CAPTION_STYLE_PRESETS["karaoke_yellow"].outline


def test_all_colours_are_valid_ass_format() -> None:
    for style in CAPTION_STYLE_PRESETS.values():
        for colour in (style.primary, style.secondary, style.outline_col):
            assert colour.startswith("&H")
            # &HAABBGGRR -> 8 hex digits.
            hex_part = colour[2:]
            assert len(hex_part) == 8
            int(hex_part, 16)  # raises ValueError if malformed


@pytest.mark.parametrize("style_id", sorted(_EXPECTED_IDS))
def test_get_caption_style_known_ids(style_id: str) -> None:
    assert get_caption_style(style_id) is CAPTION_STYLE_PRESETS[style_id]


@pytest.mark.parametrize("bad", [None, "", "does_not_exist", "KARAOKE_YELLOW"])
def test_get_caption_style_falls_back_to_default(bad: str | None) -> None:
    assert get_caption_style(bad) is CAPTION_STYLE_PRESETS[DEFAULT_CAPTION_STYLE]


def test_list_caption_styles_shape() -> None:
    catalog = list_caption_styles()
    assert isinstance(catalog, list)
    ids = [entry["id"] for entry in catalog]
    assert set(ids) == set(CAPTION_STYLE_PRESETS)
    # Default listed first.
    assert ids[0] == DEFAULT_CAPTION_STYLE
    for entry in catalog:
        assert set(entry) == {"id", "name", "description", "primary", "secondary"}
        assert all(isinstance(v, str) and v for v in entry.values() if v != "")
        assert entry["primary"].startswith("&H")
        assert entry["secondary"].startswith("&H")


def test_preset_renders_valid_ass() -> None:
    words = [WordTiming(text="hello", start=0.0, end=0.5)]
    for style in CAPTION_STYLE_PRESETS.values():
        doc = build_ass([words], style=style)
        assert "[V4+ Styles]" in doc
        assert style.primary in doc
        assert style.secondary in doc
