"""Unit tests for app/services/script/ugc.py (ReelForge UGC script generator).

Covers the FOCUS behaviors:
  * _parse_ugc_script: valid JSON -> normalized dict with all fields
  * _parse_ugc_script: invalid / missing-field JSON raises ValueError
  * full_text reconstruction from hook + segments + cta
  * build_ugc_script_prompt embeds both the TR and EN personas
  * generate_ugc_script retry-on-invalid-JSON loop and None on exhausted retries

No network is hit: _generate_response is always monkeypatched.
"""

from __future__ import annotations

import json

import pytest

import app.services.script.ugc as ugc


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _valid_payload(
    hook: str = "You won't believe this trick",
    segments=None,
    cta: str = "Follow for more",
    est_duration_s: int = 25,
) -> dict:
    if segments is None:
        segments = ["First I tried this.", "Then this happened.", "Now it's easy."]
    return {
        "hook": hook,
        "segments": segments,
        "cta": cta,
        "est_duration_s": est_duration_s,
    }


# --------------------------------------------------------------------------- #
# _parse_ugc_script — valid input
# --------------------------------------------------------------------------- #
def test_parse_valid_json_returns_all_fields():
    payload = _valid_payload()
    result = ugc._parse_ugc_script(json.dumps(payload))

    assert set(result.keys()) == {
        "hook",
        "segments",
        "cta",
        "full_text",
        "est_duration_s",
    }
    assert result["hook"] == payload["hook"]
    assert result["segments"] == payload["segments"]
    assert result["cta"] == payload["cta"]
    assert result["est_duration_s"] == payload["est_duration_s"]


def test_parse_full_text_reconstructed_from_parts():
    payload = _valid_payload(
        hook="HOOK LINE",
        segments=["seg one", "seg two"],
        cta="CTA LINE",
    )
    result = ugc._parse_ugc_script(json.dumps(payload))

    # full_text is rebuilt locally (upstream strips newlines), joined with blank lines.
    assert result["full_text"] == "HOOK LINE\n\nseg one\n\nseg two\n\nCTA LINE"
    # Order: hook first, cta last, segments in between.
    assert result["full_text"].startswith("HOOK LINE")
    assert result["full_text"].endswith("CTA LINE")


def test_parse_tolerates_code_fence_wrapper():
    payload = _valid_payload()
    fenced = "```json\n" + json.dumps(payload) + "\n```"
    result = ugc._parse_ugc_script(fenced)
    assert result["hook"] == payload["hook"]


def test_parse_extracts_first_json_object_from_prose():
    payload = _valid_payload()
    noisy = "Sure! Here you go: " + json.dumps(payload) + " Hope that helps."
    result = ugc._parse_ugc_script(noisy)
    assert result["segments"] == payload["segments"]


def test_parse_drops_empty_segments_and_keeps_valid():
    payload = _valid_payload(segments=["real one", "", "   ", "real two"])
    result = ugc._parse_ugc_script(json.dumps(payload))
    assert result["segments"] == ["real one", "real two"]


def test_parse_estimates_duration_when_missing():
    payload = _valid_payload(est_duration_s=0)
    result = ugc._parse_ugc_script(json.dumps(payload))
    # Falls back to a word-count estimate, clamped to the supported minimum.
    assert result["est_duration_s"] >= ugc._MIN_TARGET_DURATION_S


def test_parse_estimates_duration_when_non_integer():
    payload = _valid_payload()
    payload["est_duration_s"] = "not-a-number"
    result = ugc._parse_ugc_script(json.dumps(payload))
    assert isinstance(result["est_duration_s"], int)
    assert result["est_duration_s"] >= ugc._MIN_TARGET_DURATION_S


def test_parse_clamps_overlong_duration():
    payload = _valid_payload(est_duration_s=99999)
    result = ugc._parse_ugc_script(json.dumps(payload))
    assert result["est_duration_s"] == ugc._MAX_TARGET_DURATION_S


# --------------------------------------------------------------------------- #
# _parse_ugc_script — invalid input raises ValueError
# --------------------------------------------------------------------------- #
def test_parse_non_json_raises_value_error():
    with pytest.raises(ValueError):
        ugc._parse_ugc_script("this is not json at all")


def test_parse_json_array_raises_value_error():
    with pytest.raises(ValueError):
        ugc._parse_ugc_script(json.dumps(["a", "b"]))


def test_parse_missing_hook_raises_value_error():
    payload = _valid_payload()
    del payload["hook"]
    with pytest.raises(ValueError):
        ugc._parse_ugc_script(json.dumps(payload))


def test_parse_empty_hook_raises_value_error():
    payload = _valid_payload(hook="   ")
    with pytest.raises(ValueError):
        ugc._parse_ugc_script(json.dumps(payload))


def test_parse_missing_cta_raises_value_error():
    payload = _valid_payload()
    del payload["cta"]
    with pytest.raises(ValueError):
        ugc._parse_ugc_script(json.dumps(payload))


def test_parse_segments_not_a_list_raises_value_error():
    payload = _valid_payload()
    payload["segments"] = "one big string"
    with pytest.raises(ValueError):
        ugc._parse_ugc_script(json.dumps(payload))


def test_parse_zero_segments_raises_value_error():
    payload = _valid_payload(segments=[])
    with pytest.raises(ValueError):
        ugc._parse_ugc_script(json.dumps(payload))


def test_parse_too_many_segments_raises_value_error():
    payload = _valid_payload(segments=[f"seg {i}" for i in range(ugc.UGC_SEGMENT_MAX + 1)])
    with pytest.raises(ValueError):
        ugc._parse_ugc_script(json.dumps(payload))


# --------------------------------------------------------------------------- #
# build_ugc_script_prompt — persona embedding
# --------------------------------------------------------------------------- #
def test_prompt_auto_contains_both_tr_and_en_personas():
    prompt = ugc.build_ugc_script_prompt("morning routine", language="auto")
    assert ugc._TR_PERSONA in prompt
    assert ugc._EN_PERSONA in prompt


def test_prompt_tr_contains_tr_persona():
    prompt = ugc.build_ugc_script_prompt("sabah rutini", language="tr")
    assert ugc._TR_PERSONA in prompt
    # Native Turkish glyphs survive in the persona block.
    assert "üreticisisin" in prompt


def test_prompt_en_contains_en_persona():
    prompt = ugc.build_ugc_script_prompt("morning routine", language="en")
    assert ugc._EN_PERSONA in prompt


def test_prompt_includes_subject_and_json_key_contract():
    prompt = ugc.build_ugc_script_prompt("green tea benefits", language="en")
    assert "green tea benefits" in prompt
    for key in ("hook", "segments", "cta", "est_duration_s"):
        assert f'"{key}"' in prompt


# --------------------------------------------------------------------------- #
# generate_ugc_script — retry loop with monkeypatched _generate_response
# --------------------------------------------------------------------------- #
def test_generate_success_first_try(monkeypatch):
    payload = _valid_payload()

    def fake_generate(prompt, app_config=None):
        return json.dumps(payload)

    monkeypatch.setattr(ugc, "_generate_response", fake_generate)

    result = ugc.generate_ugc_script("cool subject", language="en")
    assert result is not None
    assert result["hook"] == payload["hook"]
    assert result["full_text"].startswith(payload["hook"])


def test_generate_retries_then_succeeds(monkeypatch):
    payload = _valid_payload()
    calls = {"n": 0}

    def fake_generate(prompt, app_config=None):
        calls["n"] += 1
        if calls["n"] < 3:
            return "totally not json"  # triggers ValueError -> retry
        return json.dumps(payload)

    monkeypatch.setattr(ugc, "_generate_response", fake_generate)
    monkeypatch.setattr(ugc, "_max_retries", 5)

    result = ugc.generate_ugc_script("cool subject", language="auto")
    assert result is not None
    assert calls["n"] == 3
    assert result["cta"] == payload["cta"]


def test_generate_returns_none_when_retries_exhausted(monkeypatch):
    calls = {"n": 0}

    def fake_generate(prompt, app_config=None):
        calls["n"] += 1
        return "never valid json"

    monkeypatch.setattr(ugc, "_generate_response", fake_generate)
    monkeypatch.setattr(ugc, "_max_retries", 4)

    result = ugc.generate_ugc_script("cool subject")
    assert result is None
    # Every attempt was consumed.
    assert calls["n"] == 4


def test_generate_treats_error_sentinel_as_failure(monkeypatch):
    calls = {"n": 0}

    def fake_generate(prompt, app_config=None):
        calls["n"] += 1
        return "Error: provider exploded"

    monkeypatch.setattr(ugc, "_generate_response", fake_generate)
    monkeypatch.setattr(ugc, "_max_retries", 3)

    result = ugc.generate_ugc_script("cool subject")
    assert result is None
    # The "Error: " guard must not attempt to parse; all attempts still run.
    assert calls["n"] == 3


def test_generate_empty_subject_returns_none_without_calling_llm(monkeypatch):
    called = {"n": 0}

    def fake_generate(prompt, app_config=None):
        called["n"] += 1
        return json.dumps(_valid_payload())

    monkeypatch.setattr(ugc, "_generate_response", fake_generate)

    assert ugc.generate_ugc_script("   ") is None
    assert called["n"] == 0


def test_generate_passes_app_config_through(monkeypatch):
    payload = _valid_payload()
    seen = {}

    def fake_generate(prompt, app_config=None):
        seen["app_config"] = app_config
        return json.dumps(payload)

    monkeypatch.setattr(ugc, "_generate_response", fake_generate)

    sentinel = {"provider": "litellm"}
    result = ugc.generate_ugc_script("subject", app_config=sentinel)
    assert result is not None
    assert seen["app_config"] is sentinel


def test_generate_recovers_from_provider_exception(monkeypatch):
    payload = _valid_payload()
    calls = {"n": 0}

    def fake_generate(prompt, app_config=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient boom")
        return json.dumps(payload)

    monkeypatch.setattr(ugc, "_generate_response", fake_generate)
    monkeypatch.setattr(ugc, "_max_retries", 5)

    result = ugc.generate_ugc_script("subject")
    assert result is not None
    assert calls["n"] == 2


# --------------------------------------------------------------------------- #
# temperature — batch-variant diversity (§5a)
# --------------------------------------------------------------------------- #
def test_generate_two_calls_can_differ_at_high_temperature(monkeypatch):
    # §5a: with temperature>0, repeated calls on the SAME input must be able to
    # produce DISTINCT scripts (batch variant diversity). We model provider
    # non-determinism by echoing a per-call counter into the hook.
    calls = {"n": 0}

    def fake_generate(prompt, app_config=None, temperature=None):
        calls["n"] += 1
        payload = _valid_payload(hook=f"variant hook #{calls['n']}")
        return json.dumps(payload)

    monkeypatch.setattr(ugc, "_generate_response", fake_generate)

    first = ugc.generate_ugc_script("cool subject", temperature=0.9)
    second = ugc.generate_ugc_script("cool subject", temperature=0.9)

    assert first is not None and second is not None
    # Same input, high temperature -> the two variants differ.
    assert first["hook"] != second["hook"]
    assert first["full_text"] != second["full_text"]


def test_generate_threads_temperature_when_supported(monkeypatch):
    # When the bound _generate_response accepts a temperature kwarg, the caller's
    # value is threaded through verbatim.
    seen = {}

    def fake_generate(prompt, app_config=None, temperature=None):
        seen["temperature"] = temperature
        return json.dumps(_valid_payload())

    monkeypatch.setattr(ugc, "_generate_response", fake_generate)

    result = ugc.generate_ugc_script("subject", temperature=0.7)
    assert result is not None
    assert seen["temperature"] == pytest.approx(0.7)


def test_generate_does_not_pass_temperature_when_unsupported(monkeypatch):
    # The stock MPT _generate_response(prompt, app_config=None) has no temperature
    # kwarg; generate_ugc_script must NOT try to pass it (would raise TypeError).
    seen = {"kwargs": None}

    def fake_generate(prompt, app_config=None):
        seen["kwargs"] = {"app_config": app_config}
        return json.dumps(_valid_payload())

    monkeypatch.setattr(ugc, "_generate_response", fake_generate)

    result = ugc.generate_ugc_script("subject", temperature=0.9)
    assert result is not None
    # Reached the provider without a TypeError -> temperature was not forced in.
    assert seen["kwargs"] == {"app_config": None}


def test_generate_clamps_out_of_range_temperature(monkeypatch):
    seen = {}

    def fake_generate(prompt, app_config=None, temperature=None):
        seen["temperature"] = temperature
        return json.dumps(_valid_payload())

    monkeypatch.setattr(ugc, "_generate_response", fake_generate)

    ugc.generate_ugc_script("subject", temperature=99.0)
    assert seen["temperature"] == ugc._MAX_TEMPERATURE

    ugc.generate_ugc_script("subject", temperature=-5.0)
    assert seen["temperature"] == ugc._MIN_TEMPERATURE


def test_generate_default_temperature_is_high(monkeypatch):
    # Diversity-by-default: the public entry point defaults to 0.9.
    seen = {}

    def fake_generate(prompt, app_config=None, temperature=None):
        seen["temperature"] = temperature
        return json.dumps(_valid_payload())

    monkeypatch.setattr(ugc, "_generate_response", fake_generate)

    ugc.generate_ugc_script("subject")
    assert seen["temperature"] == pytest.approx(ugc.DEFAULT_UGC_TEMPERATURE)
    assert ugc.DEFAULT_UGC_TEMPERATURE == 0.9
