"""MG8: degrade, don't die.

* Disk preflight: under the floor -> honest 503 (PreflightError) and one owner
  alert; enough space or an unreadable disk -> renders go on.
* LLM chain: configured provider (Relay first) -> configured free fallbacks ->
  deterministic script from the page facts. A reel script is never "Error: ...".
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from app.services import llm, llm_fallback
from app.workers import preflight

GB = 1024**3


def _statvfs(free_gb: float):
    return lambda path: SimpleNamespace(f_bavail=int(free_gb * GB / 4096), f_frsize=4096)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    preflight._reset_alert_clock()
    monkeypatch.delenv("MENIVOR_MIN_FREE_DISK_GB", raising=False)
    monkeypatch.delenv("MENIVOR_LLM_FALLBACK_CHAIN", raising=False)
    monkeypatch.delenv("MENIVOR_OWNER_ALERT_EMAIL", raising=False)
    yield
    preflight._reset_alert_clock()


# --------------------------------------------------------------------------- #
# Disk preflight
# --------------------------------------------------------------------------- #
def test_low_disk_refuses_with_503_and_alerts_once(monkeypatch, tmp_path):
    posts: list[tuple] = []
    import requests

    monkeypatch.setenv("MENIVOR_OWNER_NTFY_URL", "https://ntfy.sh/menivor-test")
    monkeypatch.setattr(requests, "post", lambda url, **kw: posts.append((url, kw)))
    result = preflight.check(str(tmp_path), statvfs=_statvfs(4.2))
    assert not result.ok and result.free_gb == pytest.approx(4.2, abs=0.01)
    assert "nothing was charged" in result.message
    with pytest.raises(preflight.PreflightError) as err:
        preflight.require_capacity(str(tmp_path), statvfs=_statvfs(4.2))
    assert err.value.status == 503 and err.value.message == preflight.BUSY_MESSAGE
    assert len(posts) == 1 and posts[0][0] == "https://ntfy.sh/menivor-test"
    assert b"4.2 GB free" in posts[0][1]["data"]


def test_enough_disk_passes_and_floor_is_configurable(monkeypatch, tmp_path):
    assert preflight.check(str(tmp_path), statvfs=_statvfs(50)).ok
    monkeypatch.setenv("MENIVOR_MIN_FREE_DISK_GB", "80")
    assert not preflight.check(str(tmp_path), statvfs=_statvfs(50)).ok
    monkeypatch.setenv("MENIVOR_MIN_FREE_DISK_GB", "junk")
    assert preflight.min_free_gb() == preflight.DEFAULT_MIN_FREE_GB


def test_unreadable_disk_does_not_block_renders(tmp_path):
    def boom(path):
        raise OSError("no statvfs")

    assert preflight.check(str(tmp_path), statvfs=boom).ok


def test_missing_render_dir_measures_the_nearest_parent(tmp_path):
    seen: list[str] = []

    def spy(path):
        seen.append(path)
        return _statvfs(99)(path)

    assert preflight.check(str(tmp_path / "not" / "yet"), statvfs=spy).ok
    assert seen == [str(tmp_path)]


def test_real_statvfs_works_here():
    assert preflight.check(os.getcwd()).free_gb >= 0


# --------------------------------------------------------------------------- #
# LLM chain
# --------------------------------------------------------------------------- #
APP = {
    "llm_provider": "litellm",
    "groq_api_key": "gsk_test",
    "ollama_base_url": "",
    "pollinations_api_key": "",
}


def test_fallback_chain_uses_only_configured_free_providers(monkeypatch):
    assert llm_fallback.fallback_chain("litellm", APP) == ["groq"]
    assert llm_fallback.fallback_chain("groq", APP) == []
    with_ollama = {**APP, "ollama_base_url": "http://127.0.0.1:11434/v1", "ollama_model_name": "llama3.2"}
    assert llm_fallback.fallback_chain("litellm", with_ollama) == ["ollama", "groq"]
    monkeypatch.setenv("MENIVOR_LLM_FALLBACK_CHAIN", "none")
    assert llm_fallback.fallback_chain("litellm", with_ollama) == []
    monkeypatch.setenv("MENIVOR_LLM_FALLBACK_CHAIN", "groq,unknown")
    assert llm_fallback.fallback_chain("litellm", with_ollama) == ["groq"]


def test_relay_down_falls_back_to_the_free_provider(monkeypatch):
    calls: list[str] = []

    def fake(prompt, app_config=None):
        provider = (app_config or {}).get("llm_provider")
        calls.append(provider)
        return "Error: relay unreachable" if provider == "litellm" else "A script from groq."

    monkeypatch.setattr(llm, "_generate_counted", fake)
    assert llm._generate_response("write", app_config=dict(APP)) == "A script from groq."
    assert calls == ["litellm", "groq"]
    assert APP["llm_provider"] == "litellm"  # the caller's config is never mutated


def test_all_llms_down_keeps_the_primary_error(monkeypatch):
    monkeypatch.setattr(llm, "_generate_counted", lambda prompt, app_config=None: "Error: down")
    assert llm._generate_response("write", app_config=dict(APP)) == "Error: down"


def test_script_never_fails_when_every_llm_is_down(monkeypatch):
    calls = {"n": 0}

    def down(prompt, app_config=None):
        calls["n"] += 1
        return "Error: relay unreachable"

    monkeypatch.setattr(llm, "_generate_response", down)
    script = llm.generate_script(
        video_subject="Acme Notes",
        language="en",
        facts=[
            "Acme Notes turns meetings into action items. It works offline",
            "Free for teams of three.",
        ],
    )
    assert calls["n"] == llm._CHAIN_FAILURES_BEFORE_DETERMINISTIC
    assert "Error" not in script
    assert script.startswith("Here is a quick look at Acme Notes.")
    assert "Acme Notes turns meetings into action items." in script
    assert "It works offline." in script and "Free for teams of three." in script


def test_script_fallback_uses_the_prompt_when_no_facts_and_speaks_turkish(monkeypatch):
    monkeypatch.setattr(llm, "_generate_response", lambda prompt, app_config=None: "Error: x")
    script = llm.generate_script(
        video_subject="Kahve Makinesi", language="tr-TR", video_script_prompt="Tek tuşla taze kahve hazırlar."
    )
    assert script.startswith("Kahve Makinesi hakkında kısa bir bakış.")
    assert "Tek tuşla taze kahve hazırlar." in script


def test_working_llm_is_used_as_before(monkeypatch):
    monkeypatch.setattr(llm, "_generate_response", lambda prompt, app_config=None: "Real script.")
    assert llm.generate_script(video_subject="Acme", facts=["ignored when the LLM works"]) == "Real script."


def test_deterministic_terms_shape():
    terms = llm_fallback.deterministic_terms("Acme Notes app", "turns meetings into action items", 5)
    assert len(terms) == 5 and terms[0] == "Acme Notes"
    assert all(1 <= len(t.split()) <= 3 for t in terms)
