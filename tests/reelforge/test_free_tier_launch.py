"""Free public tier (``REELFORGE_PUBLIC_TIER=free``): launch without paid keys.

Preflight: only approval + infra + a script LLM are required; Sentry and the
premium providers become warnings. Runtime: formats whose provider key is
missing are rejected up front with ``402 format_locked``; premium voices fall
back to a free edge-tts voice.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.launch import formats
from app.core.launch.readiness import readiness_document
from app.core.launch_preflight import (
    collect_preflight_errors,
    collect_preflight_warnings,
    enforce_startup_preflight,
    missing_public_requirements,
    optional_missing_requirements,
    public_tier,
)
from app.models.exception import HttpException

SECRETISH = "sk-live-DO-NOT-LEAK-456"

FREE_ENV: dict[str, str] = {
    "REELFORGE_LAUNCH_MODE": "public",
    "REELFORGE_PUBLIC_LAUNCH_APPROVED": "true",
    "REELFORGE_PUBLIC_TIER": "free",
    "NEON_DATABASE_URL": "postgresql://user:pass@host/db",
    "REELFORGE_R2_BUCKET_NAME": "reelforge-media",
    "REDIS_HOST": "redis.internal",
    "R2_ACCOUNT_ID": "acct",
    "R2_ACCESS_KEY_ID": "key",
    "R2_SECRET_ACCESS_KEY": "secret",
    "R2_PUBLIC_BASE_URL": "https://media.example.com",
    "ANTHROPIC_API_KEY": SECRETISH,
}


class TestFreeTierPreflight:
    def test_tier_defaults_to_full(self) -> None:
        assert public_tier({}) == "full"
        assert public_tier({"REELFORGE_PUBLIC_TIER": " FREE "}) == "free"

    def test_free_tier_passes_without_premium_keys_or_sentry(self) -> None:
        assert collect_preflight_errors(production=True, env=FREE_ENV) == []
        warnings = collect_preflight_warnings(FREE_ENV)
        joined = "\n".join(warnings)
        for name in ("SENTRY_DSN", "ELEVENLABS_API_KEY", "HEYGEN_API_KEY", "B-roll"):
            assert name in joined

    def test_free_tier_startup_warns_but_does_not_raise(self) -> None:
        warnings: list[str] = []
        assert enforce_startup_preflight(warnings.append, env=FREE_ENV) == []
        assert any("SENTRY_DSN" in w for w in warnings)

    def test_full_tier_still_requires_everything(self) -> None:
        env = dict(FREE_ENV, REELFORGE_PUBLIC_TIER="full")
        with pytest.raises(RuntimeError) as excinfo:
            enforce_startup_preflight(lambda _m: None, env=env)
        assert "HEYGEN_API_KEY" in str(excinfo.value)
        assert collect_preflight_warnings(env) == []

    def test_free_tier_still_requires_infra_and_approval(self) -> None:
        env = {k: v for k, v in FREE_ENV.items() if k not in {"REDIS_HOST", "REELFORGE_PUBLIC_LAUNCH_APPROVED"}}
        errors = "\n".join(collect_preflight_errors(production=True, env=env))
        assert "REDIS_HOST" in errors and "REELFORGE_PUBLIC_LAUNCH_APPROVED" in errors

    def test_free_tier_requires_a_script_llm(self) -> None:
        env = {k: v for k, v in FREE_ENV.items() if k != "ANTHROPIC_API_KEY"}
        assert any("script LLM" in e for e in collect_preflight_errors(production=True, env=env))
        # Groq alone is not enough: the app must be pointed at a groq model.
        env["GROQ_API_KEY"] = "gsk"
        assert any("script LLM" in e for e in collect_preflight_errors(production=True, env=env))
        env["REELFORGE_LLM_MODEL"] = "groq/llama-3.3-70b-versatile"
        assert collect_preflight_errors(production=True, env=env) == []

    def test_broll_none_is_free_tier_only(self) -> None:
        free = dict(FREE_ENV, BROLL_GEN_PROVIDER="none")
        assert collect_preflight_errors(production=True, env=free) == []
        full = {"BROLL_GEN_PROVIDER": "none"}
        assert collect_preflight_errors(env=full) == ["BROLL_GEN_PROVIDER must be comfyui or pixelle"]

    def test_unknown_tier_is_rejected(self) -> None:
        errors = collect_preflight_errors(env={"REELFORGE_PUBLIC_TIER": "gold"})
        assert "REELFORGE_PUBLIC_TIER must be full or free" in errors

    def test_checkout_coherence_rules_still_apply_in_free_tier(self) -> None:
        env = dict(FREE_ENV, REELFORGE_CHECKOUT_ENABLED="true")
        assert any("payment rail" in e for e in collect_preflight_errors(production=True, env=env))

    def test_requirements_split_required_and_optional(self) -> None:
        assert missing_public_requirements(FREE_ENV) == []
        optional = optional_missing_requirements(FREE_ENV)
        for name in ("SENTRY_DSN", "ELEVENLABS_API_KEY", "HEYGEN_API_KEY", "COMFYUI_API_KEY"):
            assert name in optional


class TestLaunchStatusFormats:
    def test_free_tier_document_lists_formats_names_only(self) -> None:
        doc = readiness_document(FREE_ENV)
        assert doc["tier"] == "free"
        assert doc["public_launch_ready"] is True
        assert SECRETISH not in repr(doc)
        available = {f["id"] for f in doc["available_formats"]}
        locked = {f["id"]: f for f in doc["locked_formats"]}
        assert {"captions_only_byov", "typed_script", "generated_script"} <= available
        assert {"avatar_reel", "premium_voice", "ai_broll"} <= set(locked)
        assert locked["avatar_reel"]["code"] == "format_locked"
        assert locked["avatar_reel"]["unlock_env"] == ["HEYGEN_API_KEY"]

    def test_heygen_key_unlocks_avatar_reel(self) -> None:
        doc = readiness_document(dict(FREE_ENV, HEYGEN_API_KEY="x"))
        assert "avatar_reel" in {f["id"] for f in doc["available_formats"]}


def _params(**overrides):
    base = {
        "layout": "captions_only",
        "avatar_provider": "heygen",
        "video_script": "",
        "translate_source_script": "",
        "voiceover_key": "",
        "screen_recording_key": "uploads/rec.mp4",
        "voice_name": "",
    }
    return SimpleNamespace(**{**base, **overrides})


class TestFormatGating:
    @pytest.fixture(autouse=True)
    def _no_providers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(formats, "avatar_provider_enabled", lambda _pid="heygen": False)
        monkeypatch.setattr(formats, "script_llm_configured", lambda: False)
        monkeypatch.setattr(formats, "elevenlabs_configured", lambda: False)

    @staticmethod
    def _validate(params) -> None:
        from app.domains.reels.router import _validate_enabled_feature_secrets

        _validate_enabled_feature_secrets(params, "rid")

    def test_captions_only_byov_needs_no_keys(self) -> None:
        self._validate(_params())

    def test_faceless_with_typed_script_needs_no_keys(self) -> None:
        self._validate(_params(screen_recording_key="", voice_name="en-US-AriaNeural-Female",
                               video_script="Hello world"))

    def test_premium_voice_is_not_locked(self) -> None:
        self._validate(_params(screen_recording_key="", voice_name="elevenlabs:abc",
                               video_script="Hello world"))

    def test_avatar_layout_is_format_locked(self) -> None:
        with pytest.raises(HttpException) as excinfo:
            self._validate(_params(layout="pip", video_script="x"))
        assert excinfo.value.status_code == 402
        assert excinfo.value.data["code"] == "format_locked"
        assert excinfo.value.data["format"] == "avatar_reel"
        assert "not available yet" in excinfo.value.message

    def test_generated_script_is_locked_without_llm(self) -> None:
        with pytest.raises(HttpException) as excinfo:
            self._validate(_params(screen_recording_key="", voice_name="en-US-AriaNeural-Female"))
        assert excinfo.value.status_code == 402
        assert excinfo.value.data["format"] == "generated_script"

    def test_premium_voice_falls_back_to_free_voice(self) -> None:
        from app.services.reelforge import _effective_voice_name

        tr = SimpleNamespace(voice_name="elevenlabs:abc", language="tr")
        assert _effective_voice_name("job", tr) == "tr-TR-EmelNeural-Female"
        edge = SimpleNamespace(voice_name="en-US-GuyNeural-Male", language="en")
        assert _effective_voice_name("job", edge) == "en-US-GuyNeural-Male"

    def test_configured_elevenlabs_keeps_premium_voice_when_funded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.domains.reels import premium
        from app.services.reelforge import _effective_voice_name

        monkeypatch.setattr(formats, "elevenlabs_configured", lambda: True)
        monkeypatch.setattr(premium, "premium_voice_funded", lambda job_id, ctx=None: True)
        params = SimpleNamespace(voice_name="elevenlabs:abc", language="en")
        assert _effective_voice_name("job", params) == "elevenlabs:abc"

    def test_standard_credit_never_pays_for_elevenlabs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.domains.reels import premium
        from app.services.reelforge import _effective_voice_name

        monkeypatch.setattr(formats, "elevenlabs_configured", lambda: True)
        monkeypatch.setattr(premium, "premium_voice_funded", lambda job_id, ctx=None: False)
        params = SimpleNamespace(voice_name="elevenlabs:abc", language="en")
        assert _effective_voice_name("job", params) == formats.free_voice_for("en")


def test_broll_none_is_format_locked(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.domains.broll.router import _require_enabled_provider

    monkeypatch.setenv("BROLL_GEN_PROVIDER", "none")
    with pytest.raises(HttpException) as excinfo:
        _require_enabled_provider("rid")
    assert excinfo.value.status_code == 402
    assert excinfo.value.data["format"] == "ai_broll"
