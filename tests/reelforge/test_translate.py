"""Unit tests for app/services/translate.py (ReelForge dubbing translation).

Covers the FOCUS behaviors:
  * SUPPORTED_DUB_LANGUAGES / is_supported_language: the 7 bundled-font languages
    are accepted (including region variants) and unknown codes are rejected.
  * translate_script: returns the model's translated text (code fences stripped).
  * translate_script: retries once on empty, then returns None when still empty.
  * translate_script: unsupported language / empty script are guarded -> None.

No network is hit: _generate_response is always monkeypatched.
"""

from __future__ import annotations

import pytest

import app.services.translate as translate


# --------------------------------------------------------------------------- #
# Supported-language checks
# --------------------------------------------------------------------------- #
def test_supported_languages_cover_bundled_fonts():
    codes = {entry["code"] for entry in translate.SUPPORTED_DUB_LANGUAGES}
    assert codes == {"en", "tr", "es", "fr", "de", "pt", "it"}
    # Every entry exposes a human-readable name.
    assert all(entry["name"] for entry in translate.SUPPORTED_DUB_LANGUAGES)


@pytest.mark.parametrize("code", ["en", "tr", "es", "fr", "de", "pt", "it"])
def test_is_supported_language_accepts_each_code(code):
    assert translate.is_supported_language(code) is True


@pytest.mark.parametrize("code", ["PT-BR", "EN_US", " fr ", "De"])
def test_is_supported_language_normalizes_variants(code):
    assert translate.is_supported_language(code) is True


@pytest.mark.parametrize("code", ["ja", "zh", "ru", "", "xx", None, 123])
def test_is_supported_language_rejects_unknown(code):
    assert translate.is_supported_language(code) is False


def test_language_name_lookup():
    assert translate.language_name("tr") == "Turkish"
    assert translate.language_name("pt-BR") == "Portuguese"
    assert translate.language_name("nope") is None


# --------------------------------------------------------------------------- #
# translate_script — happy path
# --------------------------------------------------------------------------- #
def test_translate_returns_model_text(monkeypatch):
    def fake_generate(prompt, app_config=None):
        # Echo a transformed marker so we know the model output flows through.
        return "MERHABA - takip et"

    monkeypatch.setattr(translate, "_generate_response", fake_generate)

    result = translate.translate_script("Hello - follow me", "tr")
    assert result == "MERHABA - takip et"


def test_translate_strips_code_fence(monkeypatch):
    def fake_generate(prompt, app_config=None):
        return "```\nBonjour, abonne-toi\n```"

    monkeypatch.setattr(translate, "_generate_response", fake_generate)

    result = translate.translate_script("Hi, subscribe", "fr")
    assert result == "Bonjour, abonne-toi"


def test_translate_unwraps_surrounding_quotes(monkeypatch):
    def fake_generate(prompt, app_config=None):
        return '"Hola, sigueme"'

    monkeypatch.setattr(translate, "_generate_response", fake_generate)

    result = translate.translate_script("Hi, follow me", "es")
    assert result == "Hola, sigueme"


def test_translate_passes_target_language_into_prompt(monkeypatch):
    seen: dict[str, str] = {}

    def fake_generate(prompt, app_config=None):
        seen["prompt"] = prompt
        return "translated"

    monkeypatch.setattr(translate, "_generate_response", fake_generate)

    translate.translate_script("Some script", "de")
    assert "German" in seen["prompt"]
    assert "Some script" in seen["prompt"]


# --------------------------------------------------------------------------- #
# translate_script — retry + failure paths
# --------------------------------------------------------------------------- #
def test_translate_retries_once_on_empty(monkeypatch):
    calls = {"n": 0}

    def fake_generate(prompt, app_config=None):
        calls["n"] += 1
        # Empty first, then a real answer on the retry.
        return "" if calls["n"] == 1 else "Ciao, seguimi"

    monkeypatch.setattr(translate, "_generate_response", fake_generate)

    result = translate.translate_script("Bye, follow me", "it")
    assert result == "Ciao, seguimi"
    assert calls["n"] == 2


def test_translate_returns_none_when_always_empty(monkeypatch):
    calls = {"n": 0}

    def fake_generate(prompt, app_config=None):
        calls["n"] += 1
        return ""

    monkeypatch.setattr(translate, "_generate_response", fake_generate)

    result = translate.translate_script("Hello", "pt")
    assert result is None
    # One initial attempt plus exactly one retry.
    assert calls["n"] == 2


def test_translate_returns_none_on_provider_error(monkeypatch):
    def fake_generate(prompt, app_config=None):
        return "Error: provider exploded"

    monkeypatch.setattr(translate, "_generate_response", fake_generate)

    assert translate.translate_script("Hello", "en") is None


def test_translate_returns_none_on_exception(monkeypatch):
    def fake_generate(prompt, app_config=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(translate, "_generate_response", fake_generate)

    assert translate.translate_script("Hello", "en") is None


# --------------------------------------------------------------------------- #
# translate_script — input guards
# --------------------------------------------------------------------------- #
def test_translate_unsupported_language_guarded(monkeypatch):
    def fail_if_called(prompt, app_config=None):  # pragma: no cover - must not run
        raise AssertionError("LLM should not be called for unsupported language")

    monkeypatch.setattr(translate, "_generate_response", fail_if_called)

    assert translate.translate_script("Hello", "ja") is None


@pytest.mark.parametrize("script", ["", "   ", None])
def test_translate_empty_script_guarded(monkeypatch, script):
    def fail_if_called(prompt, app_config=None):  # pragma: no cover - must not run
        raise AssertionError("LLM should not be called for empty script")

    monkeypatch.setattr(translate, "_generate_response", fail_if_called)

    assert translate.translate_script(script, "en") is None
