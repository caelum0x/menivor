"""Unit tests for app/services/ideas.py (SPARK — AI Idea Engine).

Covers the FOCUS behaviors:
  * build_ideas_prompt: strict-JSON key contract + count + native TR rule
  * _parse_ideas: valid JSON -> normalized list of idea dicts
  * _parse_ideas: count clamp (1..10) applied to the returned list
  * _parse_ideas: invalid layout / caption_style coerced to safe defaults
  * _parse_ideas: unusable JSON raises ValueError (retry signal)
  * generate_ideas: count clamp, retry-on-invalid-JSON loop, None when exhausted

No network is hit: _generate_response is always monkeypatched.
"""

from __future__ import annotations

import json

import pytest

import app.services.ideas as ideas


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _valid_idea(
    title: str = "Morning routine reveal",
    hook: str = "Nobody told me this one trick",
    angle: str = "Curiosity gap into a quick win",
    fmt: str = "talking head",
    script_outline=None,
    suggested_layout: str = "pip",
    suggested_caption_style: str = "karaoke_yellow",
    language: str = "en",
    est_duration_s: int = 25,
) -> dict:
    if script_outline is None:
        script_outline = ["Hook the viewer.", "Show the trick.", "Deliver payoff."]
    return {
        "title": title,
        "hook": hook,
        "angle": angle,
        "format": fmt,
        "script_outline": script_outline,
        "suggested_layout": suggested_layout,
        "suggested_caption_style": suggested_caption_style,
        "language": language,
        "est_duration_s": est_duration_s,
    }


def _payload(ideas_list) -> str:
    return json.dumps({"ideas": ideas_list})


# --------------------------------------------------------------------------- #
# _parse_ideas — valid input
# --------------------------------------------------------------------------- #
def test_parse_valid_json_returns_all_fields():
    result = ideas._parse_ideas(_payload([_valid_idea()]), count=6)
    assert isinstance(result, list)
    assert len(result) == 1
    idea = result[0]
    assert set(idea.keys()) == set(ideas._REQUIRED_KEYS)
    assert idea["hook"] == "Nobody told me this one trick"
    assert idea["script_outline"] == ["Hook the viewer.", "Show the trick.", "Deliver payoff."]
    assert idea["suggested_layout"] == "pip"
    assert idea["suggested_caption_style"] == "karaoke_yellow"
    assert idea["language"] == "en"
    assert idea["est_duration_s"] == 25


def test_parse_tolerates_code_fence_wrapper():
    fenced = "```json\n" + _payload([_valid_idea()]) + "\n```"
    result = ideas._parse_ideas(fenced, count=6)
    assert result[0]["title"] == "Morning routine reveal"


def test_parse_extracts_first_json_object_from_prose():
    noisy = "Sure! Here are your ideas: " + _payload([_valid_idea()]) + " Enjoy!"
    result = ideas._parse_ideas(noisy, count=6)
    assert len(result) == 1


def test_parse_returns_multiple_ideas():
    batch = [_valid_idea(title=f"Idea {i}", hook=f"Hook number {i}") for i in range(4)]
    result = ideas._parse_ideas(_payload(batch), count=6)
    assert len(result) == 4
    assert [i["title"] for i in result] == ["Idea 0", "Idea 1", "Idea 2", "Idea 3"]


# --------------------------------------------------------------------------- #
# _parse_ideas — count clamp on the returned list
# --------------------------------------------------------------------------- #
def test_parse_truncates_to_requested_count():
    batch = [_valid_idea(title=f"Idea {i}", hook=f"Hook number {i}") for i in range(8)]
    result = ideas._parse_ideas(_payload(batch), count=3)
    assert len(result) == 3


def test_parse_count_is_clamped_to_max():
    # Requesting 999 ideas is clamped to MAX_IDEA_COUNT before truncation.
    batch = [_valid_idea(title=f"Idea {i}", hook=f"Hook number {i}") for i in range(15)]
    result = ideas._parse_ideas(_payload(batch), count=999)
    assert len(result) == ideas.MAX_IDEA_COUNT


# --------------------------------------------------------------------------- #
# _parse_ideas — invalid enum coercion
# --------------------------------------------------------------------------- #
def test_parse_coerces_invalid_layout_to_default():
    idea = _valid_idea(suggested_layout="fancy_grid")
    result = ideas._parse_ideas(_payload([idea]), count=6)
    assert result[0]["suggested_layout"] == ideas.DEFAULT_LAYOUT


def test_parse_coerces_invalid_caption_style_to_default():
    idea = _valid_idea(suggested_caption_style="rainbow_sparkle")
    result = ideas._parse_ideas(_payload([idea]), count=6)
    assert result[0]["suggested_caption_style"] == ideas.DEFAULT_CAPTION_STYLE


def test_parse_keeps_each_valid_layout_and_caption_style():
    for layout in ideas.VALID_LAYOUTS:
        idea = _valid_idea(suggested_layout=layout)
        result = ideas._parse_ideas(_payload([idea]), count=6)
        assert result[0]["suggested_layout"] == layout
    for style in ideas.VALID_CAPTION_STYLES:
        idea = _valid_idea(suggested_caption_style=style)
        result = ideas._parse_ideas(_payload([idea]), count=6)
        assert result[0]["suggested_caption_style"] == style


def test_parse_coerces_invalid_language_to_default():
    idea = _valid_idea(language="klingon")
    result = ideas._parse_ideas(_payload([idea]), count=6)
    assert result[0]["language"] == ideas.DEFAULT_IDEA_LANGUAGE


def test_parse_normalizes_language_variants():
    idea = _valid_idea(language="tr-TR")
    result = ideas._parse_ideas(_payload([idea]), count=6)
    assert result[0]["language"] == "tr"


def test_parse_coerces_and_clamps_duration():
    idea = _valid_idea(est_duration_s=99999)
    result = ideas._parse_ideas(_payload([idea]), count=6)
    assert result[0]["est_duration_s"] == ideas._MAX_DURATION_S

    idea = _valid_idea(est_duration_s="not-a-number")
    result = ideas._parse_ideas(_payload([idea]), count=6)
    assert isinstance(result[0]["est_duration_s"], int)
    assert result[0]["est_duration_s"] == ideas._DEFAULT_DURATION_S


def test_parse_truncates_overlong_outline_to_max_beats():
    idea = _valid_idea(script_outline=[f"beat {i}" for i in range(10)])
    result = ideas._parse_ideas(_payload([idea]), count=6)
    assert len(result[0]["script_outline"]) == ideas._MAX_BEATS


# --------------------------------------------------------------------------- #
# _parse_ideas — unusable JSON raises ValueError (retry signal)
# --------------------------------------------------------------------------- #
def test_parse_non_json_raises_value_error():
    with pytest.raises(ValueError):
        ideas._parse_ideas("this is not json at all", count=6)


def test_parse_missing_ideas_key_raises_value_error():
    with pytest.raises(ValueError):
        ideas._parse_ideas(json.dumps({"stuff": []}), count=6)


def test_parse_empty_ideas_array_raises_value_error():
    with pytest.raises(ValueError):
        ideas._parse_ideas(_payload([]), count=6)


def test_parse_top_level_array_raises_value_error():
    with pytest.raises(ValueError):
        ideas._parse_ideas(json.dumps([_valid_idea()]), count=6)


def test_parse_all_ideas_malformed_raises_value_error():
    # Every idea is missing its hook -> nothing usable survives -> retry signal.
    bad = _valid_idea()
    del bad["hook"]
    with pytest.raises(ValueError):
        ideas._parse_ideas(_payload([bad, bad]), count=6)


def test_parse_skips_malformed_but_keeps_valid():
    bad = _valid_idea(title="broken")
    del bad["script_outline"]
    good = _valid_idea(title="good one")
    result = ideas._parse_ideas(_payload([bad, good]), count=6)
    assert len(result) == 1
    assert result[0]["title"] == "good one"


def test_parse_missing_hook_idea_is_dropped():
    bad = _valid_idea(hook="   ")
    good = _valid_idea(title="survivor")
    result = ideas._parse_ideas(_payload([bad, good]), count=6)
    assert len(result) == 1
    assert result[0]["title"] == "survivor"


def test_parse_short_outline_idea_is_dropped():
    bad = _valid_idea(script_outline=["only one beat"])
    good = _valid_idea(title="survivor")
    result = ideas._parse_ideas(_payload([bad, good]), count=6)
    assert len(result) == 1
    assert result[0]["title"] == "survivor"


# --------------------------------------------------------------------------- #
# build_ideas_prompt — contract embedding
# --------------------------------------------------------------------------- #
def test_prompt_includes_all_required_keys():
    prompt = ideas.build_ideas_prompt("a budgeting app", "gen-z", 5, "en")
    for key in ideas._REQUIRED_KEYS:
        assert f'"{key}"' in prompt


def test_prompt_includes_context_and_audience():
    prompt = ideas.build_ideas_prompt("a budgeting app", "college students", 5, "en")
    assert "a budgeting app" in prompt
    assert "college students" in prompt


def test_prompt_requests_exact_count():
    prompt = ideas.build_ideas_prompt("an app", "", 7, "en")
    assert "EXACTLY 7" in prompt


def test_prompt_clamps_count_in_text():
    prompt = ideas.build_ideas_prompt("an app", "", 999, "en")
    assert f"EXACTLY {ideas.MAX_IDEA_COUNT}" in prompt


def test_prompt_lists_valid_layouts_and_caption_styles():
    prompt = ideas.build_ideas_prompt("an app", "", 5, "en")
    for layout in ideas.VALID_LAYOUTS:
        assert layout in prompt
    for style in ideas.VALID_CAPTION_STYLES:
        assert style in prompt


def test_prompt_tr_requests_native_turkish():
    prompt = ideas.build_ideas_prompt("bir bütçe uygulaması", "gençler", 5, "tr")
    # Native Turkish instruction with real glyphs survives in the prompt.
    assert "Türkçe" in prompt


# --------------------------------------------------------------------------- #
# generate_ideas — retry loop with monkeypatched _generate_response
# --------------------------------------------------------------------------- #
def test_generate_success_first_try(monkeypatch):
    batch = [_valid_idea(title=f"Idea {i}", hook=f"Hook number {i}") for i in range(6)]

    def fake_generate(prompt, app_config=None):
        return _payload(batch)

    monkeypatch.setattr(ideas, "_generate_response", fake_generate)

    result = ideas.generate_ideas("a cool app", count=6)
    assert result is not None
    assert len(result) == 6
    assert result[0]["hook"] == "Hook number 0"


def test_generate_clamps_count(monkeypatch):
    seen = {}
    batch = [_valid_idea(title=f"Idea {i}", hook=f"Hook number {i}") for i in range(20)]

    def fake_generate(prompt, app_config=None):
        seen["prompt"] = prompt
        return _payload(batch)

    monkeypatch.setattr(ideas, "_generate_response", fake_generate)

    # count 99 -> clamped to MAX_IDEA_COUNT in both the prompt and the result.
    result = ideas.generate_ideas("a cool app", count=99)
    assert result is not None
    assert len(result) == ideas.MAX_IDEA_COUNT
    assert f"EXACTLY {ideas.MAX_IDEA_COUNT}" in seen["prompt"]


def test_generate_clamps_count_minimum(monkeypatch):
    batch = [_valid_idea()]

    def fake_generate(prompt, app_config=None):
        return _payload(batch)

    monkeypatch.setattr(ideas, "_generate_response", fake_generate)

    result = ideas.generate_ideas("a cool app", count=0)
    assert result is not None
    assert len(result) == ideas.MIN_IDEA_COUNT


def test_generate_retries_then_succeeds(monkeypatch):
    batch = [_valid_idea()]
    calls = {"n": 0}

    def fake_generate(prompt, app_config=None):
        calls["n"] += 1
        if calls["n"] < 3:
            return "totally not json"  # triggers ValueError -> retry
        return _payload(batch)

    monkeypatch.setattr(ideas, "_generate_response", fake_generate)
    monkeypatch.setattr(ideas, "_max_retries", 5)

    result = ideas.generate_ideas("a cool app", count=1)
    assert result is not None
    assert calls["n"] == 3


def test_generate_returns_none_when_retries_exhausted(monkeypatch):
    calls = {"n": 0}

    def fake_generate(prompt, app_config=None):
        calls["n"] += 1
        return "never valid json"

    monkeypatch.setattr(ideas, "_generate_response", fake_generate)
    monkeypatch.setattr(ideas, "_max_retries", 4)

    result = ideas.generate_ideas("a cool app")
    assert result is None
    assert calls["n"] == 4  # every attempt consumed


def test_generate_treats_error_sentinel_as_failure(monkeypatch):
    calls = {"n": 0}

    def fake_generate(prompt, app_config=None):
        calls["n"] += 1
        return "Error: provider exploded"

    monkeypatch.setattr(ideas, "_generate_response", fake_generate)
    monkeypatch.setattr(ideas, "_max_retries", 3)

    result = ideas.generate_ideas("a cool app")
    assert result is None
    assert calls["n"] == 3  # never tried to parse the error text


def test_generate_never_returns_raw_model_text(monkeypatch):
    # Even a plausible-looking-but-invalid payload must never leak as raw text.
    def fake_generate(prompt, app_config=None):
        return "Here is some prose with no JSON object whatsoever."

    monkeypatch.setattr(ideas, "_generate_response", fake_generate)
    monkeypatch.setattr(ideas, "_max_retries", 2)

    result = ideas.generate_ideas("a cool app")
    assert result is None


def test_generate_empty_context_returns_none_without_calling_llm(monkeypatch):
    called = {"n": 0}

    def fake_generate(prompt, app_config=None):
        called["n"] += 1
        return _payload([_valid_idea()])

    monkeypatch.setattr(ideas, "_generate_response", fake_generate)

    assert ideas.generate_ideas("   ") is None
    assert called["n"] == 0


def test_generate_passes_app_config_through(monkeypatch):
    seen = {}

    def fake_generate(prompt, app_config=None):
        seen["app_config"] = app_config
        return _payload([_valid_idea()])

    monkeypatch.setattr(ideas, "_generate_response", fake_generate)

    sentinel = {"provider": "litellm"}
    result = ideas.generate_ideas("subject", app_config=sentinel)
    assert result is not None
    assert seen["app_config"] is sentinel


def test_generate_recovers_from_provider_exception(monkeypatch):
    batch = [_valid_idea()]
    calls = {"n": 0}

    def fake_generate(prompt, app_config=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient boom")
        return _payload(batch)

    monkeypatch.setattr(ideas, "_generate_response", fake_generate)
    monkeypatch.setattr(ideas, "_max_retries", 5)

    result = ideas.generate_ideas("subject")
    assert result is not None
    assert calls["n"] == 2


# --------------------------------------------------------------------------- #
# temperature — variety by default (threaded only when supported)
# --------------------------------------------------------------------------- #
def test_generate_threads_temperature_when_supported(monkeypatch):
    seen = {}

    def fake_generate(prompt, app_config=None, temperature=None):
        seen["temperature"] = temperature
        return _payload([_valid_idea()])

    monkeypatch.setattr(ideas, "_generate_response", fake_generate)

    result = ideas.generate_ideas("subject", temperature=0.7)
    assert result is not None
    assert seen["temperature"] == pytest.approx(0.7)


def test_generate_does_not_pass_temperature_when_unsupported(monkeypatch):
    # The stock MPT _generate_response(prompt, app_config=None) has no temperature
    # kwarg; generate_ideas must NOT try to pass it (would raise TypeError).
    seen = {"kwargs": None}

    def fake_generate(prompt, app_config=None):
        seen["kwargs"] = {"app_config": app_config}
        return _payload([_valid_idea()])

    monkeypatch.setattr(ideas, "_generate_response", fake_generate)

    result = ideas.generate_ideas("subject", temperature=0.9)
    assert result is not None
    assert seen["kwargs"] == {"app_config": None}


def test_generate_clamps_out_of_range_temperature(monkeypatch):
    seen = {}

    def fake_generate(prompt, app_config=None, temperature=None):
        seen["temperature"] = temperature
        return _payload([_valid_idea()])

    monkeypatch.setattr(ideas, "_generate_response", fake_generate)

    ideas.generate_ideas("subject", temperature=99.0)
    assert seen["temperature"] == ideas._MAX_TEMPERATURE

    ideas.generate_ideas("subject", temperature=-5.0)
    assert seen["temperature"] == ideas._MIN_TEMPERATURE


def test_generate_default_temperature_is_high(monkeypatch):
    seen = {}

    def fake_generate(prompt, app_config=None, temperature=None):
        seen["temperature"] = temperature
        return _payload([_valid_idea()])

    monkeypatch.setattr(ideas, "_generate_response", fake_generate)

    ideas.generate_ideas("subject")
    assert seen["temperature"] == pytest.approx(ideas.DEFAULT_IDEA_TEMPERATURE)
    assert ideas.DEFAULT_IDEA_TEMPERATURE == 0.9
