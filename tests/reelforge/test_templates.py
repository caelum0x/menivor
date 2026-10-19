"""Tests for the ReelForge job-template + hook catalog service."""

from __future__ import annotations

import dataclasses

import pytest

from app.services.templates import (
    TEMPLATES,
    JobTemplate,
    get_template,
    list_hooks,
    list_templates,
    load_hooks,
)

# The five formats the product spec requires, keyed by machine id.
_EXPECTED_IDS = {
    "app_demo",
    "pov",
    "three_apps_that",
    "before_after",
    "founder_story",
}
_REQUIRED_CONFIG_FIELDS = {
    "video_subject",
    "prompt_scaffold",
    "layout",
    "caption_style",
    "language",
    "target_duration_s",
}


# --------------------------------------------------------------------------- #
# Template catalog
# --------------------------------------------------------------------------- #
def test_catalog_has_at_least_five_named_templates() -> None:
    assert len(TEMPLATES) >= 5
    assert _EXPECTED_IDS.issubset(set(TEMPLATES))


def test_templates_are_frozen_dataclasses() -> None:
    for tpl in TEMPLATES.values():
        assert isinstance(tpl, JobTemplate)
        with pytest.raises(dataclasses.FrozenInstanceError):
            tpl.name = "mutated"  # type: ignore[misc]


def test_list_templates_returns_serializable_dicts_in_order() -> None:
    templates = list_templates()
    assert isinstance(templates, list)
    assert [t["id"] for t in templates] == list(TEMPLATES.keys())
    for entry in templates:
        assert isinstance(entry, dict)
        # Prefill fields exist both top-level and in the nested config block.
        for key in _REQUIRED_CONFIG_FIELDS:
            assert key in entry, key
            assert key in entry["config"], key
        assert isinstance(entry["tags"], list)
        assert isinstance(entry["target_duration_s"], int)
        assert entry["target_duration_s"] > 0


def test_display_names_cover_the_expected_formats() -> None:
    names = {t["name"] for t in list_templates()}
    assert {"App demo", "POV", "3 apps that…", "Before/After", "Founder story"} <= names


def test_prompt_scaffold_uses_subject_placeholder() -> None:
    for tpl in TEMPLATES.values():
        assert "{subject}" in tpl.prompt_scaffold, tpl.id


def test_template_values_are_valid_against_registries() -> None:
    from app.services.templates import (
        _ALLOWED_CAPTION_STYLE_IDS,
        _ALLOWED_LAYOUT_IDS,
        _SUPPORTED_LANGUAGES,
    )

    for tpl in TEMPLATES.values():
        assert tpl.layout in _ALLOWED_LAYOUT_IDS, tpl.id
        assert tpl.caption_style in _ALLOWED_CAPTION_STYLE_IDS, tpl.id
        assert tpl.language in _SUPPORTED_LANGUAGES, tpl.id


def test_get_template_hit_miss_and_normalization() -> None:
    assert get_template("app_demo")["name"] == "App demo"
    # Case-insensitive + whitespace-tolerant lookup.
    assert get_template("  APP_DEMO  ")["id"] == "app_demo"
    # Unknown / empty ids return None (not a crash).
    assert get_template("does_not_exist") is None
    assert get_template("") is None
    assert get_template("   ") is None


def test_invalid_template_definition_raises() -> None:
    with pytest.raises(ValueError):
        JobTemplate(
            id="bad",
            name="Bad",
            description="",
            video_subject="x",
            prompt_scaffold="{subject}",
            layout="not_a_real_layout",
            caption_style="karaoke_yellow",
            language="en",
            target_duration_s=30,
        )
    with pytest.raises(ValueError):
        JobTemplate(
            id="bad2",
            name="Bad2",
            description="",
            video_subject="x",
            prompt_scaffold="{subject}",
            layout="pip",
            caption_style="karaoke_yellow",
            language="en",
            target_duration_s=0,
        )


# --------------------------------------------------------------------------- #
# Hook catalog
# --------------------------------------------------------------------------- #
def test_load_hooks_returns_native_lines_per_language() -> None:
    en = load_hooks("en")
    tr = load_hooks("tr")
    assert isinstance(en, list) and len(en) >= 5
    assert isinstance(tr, list) and len(tr) >= 5
    assert all(isinstance(h, str) and h for h in en + tr)


def test_load_hooks_accepts_language_variants() -> None:
    assert load_hooks("en-US") == load_hooks("english") == load_hooks("en")
    assert load_hooks("tr-TR") == load_hooks("turkish") == load_hooks("tr")


def test_load_hooks_unknown_language_is_empty() -> None:
    assert load_hooks("fr") == []
    assert load_hooks("") == []


def test_load_hooks_returns_fresh_mutable_copy() -> None:
    first = load_hooks("en")
    first.append("mutated")
    assert "mutated" not in load_hooks("en")


def test_turkish_hooks_preserve_native_glyphs() -> None:
    joined = " ".join(load_hooks("tr"))
    assert any(ch in joined for ch in "şğıçöü")


def test_list_hooks_shape_is_stable() -> None:
    catalog = list_hooks()
    assert set(catalog) == {"tr", "en"}
    for lang, hooks in catalog.items():
        assert isinstance(hooks, list)
        assert len(hooks) >= 5, lang
