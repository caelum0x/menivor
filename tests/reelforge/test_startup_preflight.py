"""Startup enforcement of the deployment-configuration preflight.

``tools/ops/preflight.py`` has always validated launch-flag coherence and
production settings, but only when an operator or CI remembered to run it — the
FastAPI app itself would start with any configuration. The check logic now
lives in ``app.core.launch_preflight`` and runs inside the API lifespan:

* **public posture** (``REELFORGE_LAUNCH_MODE=public`` or any launch flag
  enabled) → a missing/misshaped required variable raises and aborts startup,
  listing every problem by variable *name* (never a value).
* **internal_pilot / dev** → warn-only, preserving the never-block-dev design
  of ``app/config/config.py`` and the hermetic test suites.

Stdlib-only module under test: checks take an explicit env mapping so these
tests need no monkeypatching of ``os.environ`` and cannot leak between tests.
"""

from __future__ import annotations

import sys

import pytest

from app.core.launch_preflight import (
    any_launch_flag_enabled,
    broll_provider,
    collect_preflight_errors,
    enforce_startup_preflight,
    launch_mode,
)

# A coherent, fully-credentialed public posture. Values are obvious test
# placeholders — the preflight only ever checks presence/shape, never validity.
PUBLIC_READY_ENV: dict[str, str] = {
    "REELFORGE_LAUNCH_MODE": "public",
    "REELFORGE_PUBLIC_LAUNCH_APPROVED": "true",
    "NEON_DATABASE_URL": "postgresql://user:pass@host/db",
    "REELFORGE_R2_BUCKET_NAME": "reelforge-media",
    "REDIS_HOST": "redis.internal",
    "R2_ACCOUNT_ID": "acct",
    "R2_ACCESS_KEY_ID": "key",
    "R2_SECRET_ACCESS_KEY": "secret",
    "R2_PUBLIC_BASE_URL": "https://media.example.com",
    "SENTRY_DSN": "https://key@org.ingest.sentry.io/1",
    "ANTHROPIC_API_KEY": "test",
    "ELEVENLABS_API_KEY": "test",
    "HEYGEN_API_KEY": "test",
    "COMFYUI_BASE_URL": "https://comfy.example.com",
    "COMFYUI_API_KEY": "test",
    "COMFYUI_DEPLOYMENT_ID": "dep-1",
}


class TestCollectPreflightErrors:
    def test_default_pilot_posture_is_clean(self) -> None:
        assert collect_preflight_errors(production=False, env={}) == []

    def test_unknown_launch_mode_is_rejected(self) -> None:
        errors = collect_preflight_errors(env={"REELFORGE_LAUNCH_MODE": "yolo"})
        assert any("REELFORGE_LAUNCH_MODE" in error for error in errors)

    def test_public_mode_requires_explicit_approval(self) -> None:
        errors = collect_preflight_errors(env={"REELFORGE_LAUNCH_MODE": "public"})
        assert any("REELFORGE_PUBLIC_LAUNCH_APPROVED" in error for error in errors)

    def test_checkout_outside_public_mode_is_incoherent(self) -> None:
        errors = collect_preflight_errors(env={"REELFORGE_CHECKOUT_ENABLED": "true"})
        assert any("approved public mode" in error for error in errors)

    def test_production_lists_every_missing_required_setting(self) -> None:
        errors = collect_preflight_errors(production=True, env={})
        joined = "\n".join(errors)
        for expected in (
            "database URL",
            "R2 bucket name",
            "REDIS_HOST",
            "SENTRY_DSN",
            "ANTHROPIC_API_KEY",
            "ELEVENLABS_API_KEY",
            "HEYGEN_API_KEY",
            "COMFYUI_BASE_URL",
        ):
            assert expected in joined

    def test_fully_configured_public_env_passes_production_checks(self) -> None:
        assert collect_preflight_errors(production=True, env=PUBLIC_READY_ENV) == []

    def test_checkout_requires_one_complete_payment_rail(self) -> None:
        env = dict(
            PUBLIC_READY_ENV,
            REELFORGE_CHECKOUT_ENABLED="true",
            CREEM_API_KEY="test",
        )
        errors = collect_preflight_errors(env=env)
        assert any("payment rail" in error for error in errors)

        env["CREEM_WEBHOOK_SECRET"] = "test"
        assert collect_preflight_errors(env=env) == []

    def test_unknown_broll_provider_is_rejected(self) -> None:
        errors = collect_preflight_errors(env={"BROLL_GEN_PROVIDER": "dalle"})
        assert errors == ["BROLL_GEN_PROVIDER must be comfyui or pixelle"]


class TestEnforceStartupPreflight:
    def test_clean_pilot_env_warns_nothing(self) -> None:
        warnings: list[str] = []
        assert enforce_startup_preflight(warnings.append, env={}) == []
        assert warnings == []

    def test_pilot_problems_warn_but_never_raise(self) -> None:
        warnings: list[str] = []
        errors = enforce_startup_preflight(
            warnings.append, env={"BROLL_GEN_PROVIDER": "dalle"}
        )
        assert errors  # reported...
        assert warnings and "warn-only" in warnings[0]  # ...as warnings only

    def test_public_mode_with_missing_settings_aborts_startup(self) -> None:
        env = {
            "REELFORGE_LAUNCH_MODE": "public",
            "REELFORGE_PUBLIC_LAUNCH_APPROVED": "true",
        }
        with pytest.raises(RuntimeError) as excinfo:
            enforce_startup_preflight(lambda _msg: None, env=env)
        message = str(excinfo.value)
        # Every missing variable is listed by NAME; no values can leak because
        # the preflight never reads more than presence.
        assert "SENTRY_DSN" in message
        assert "ANTHROPIC_API_KEY" in message

    def test_any_enabled_launch_flag_makes_preflight_strict(self) -> None:
        # Checkout enabled while still in pilot mode is incoherent config that
        # previously only CI would catch; startup now refuses to run with it.
        env = {"REELFORGE_CHECKOUT_ENABLED": "true"}
        assert any_launch_flag_enabled(env)
        with pytest.raises(RuntimeError):
            enforce_startup_preflight(lambda _msg: None, env=env)

    def test_fully_configured_public_env_starts_cleanly(self) -> None:
        warnings: list[str] = []
        assert enforce_startup_preflight(warnings.append, env=PUBLIC_READY_ENV) == []
        assert warnings == []


class TestCliDelegation:
    """`tools/ops/preflight.py` keeps its exact CLI contract via the shared module."""

    def test_cli_passes_on_default_pilot_env(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from apps.api.tools.ops import preflight as cli

        for flag in (
            "REELFORGE_LAUNCH_MODE",
            "REELFORGE_PUBLIC_LAUNCH_APPROVED",
            "REELFORGE_CHECKOUT_ENABLED",
            "REELFORGE_PUBLISHING_ENABLED",
            "BROLL_GEN_PROVIDER",
        ):
            monkeypatch.delenv(flag, raising=False)
        monkeypatch.setattr(sys, "argv", ["preflight.py"])
        assert cli.main() == 0
        assert "preflight passed" in capsys.readouterr().out

    def test_cli_fails_and_lists_errors_on_stderr(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from apps.api.tools.ops import preflight as cli

        monkeypatch.setenv("REELFORGE_LAUNCH_MODE", "public")
        monkeypatch.delenv("REELFORGE_PUBLIC_LAUNCH_APPROVED", raising=False)
        monkeypatch.setattr(sys, "argv", ["preflight.py"])
        assert cli.main() == 1
        captured = capsys.readouterr()
        assert "REELFORGE_PUBLIC_LAUNCH_APPROVED" in captured.err


def test_helpers_normalize_env_reads() -> None:
    assert launch_mode({"REELFORGE_LAUNCH_MODE": "  PUBLIC "}) == "public"
    assert launch_mode({}) == "internal_pilot"
    assert broll_provider({}) == "comfyui"
    assert not any_launch_flag_enabled({})
