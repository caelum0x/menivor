"""Unit tests for ``app/telemetry/sentry.py`` (CTO locked decision, DoD #5).

Verifies the two contractual behaviours:

  * NO-OP path: with an empty ``[sentry].dsn`` (the ship default), ``init_sentry``
    returns ``False`` and never imports/initialises ``sentry_sdk`` — no key is
    required to run.
  * Enabled path: with a DSN set, ``init_sentry`` calls ``sentry_sdk.init`` with
    the configured dsn/environment/traces_sample_rate, tagged with ``component``.

``sentry_sdk`` is replaced by a fake module so the tests never touch the real
SDK or network. Config is monkeypatched in-place so nothing is persisted.

Run:
    NEON_DATABASE_URL='sqlite:///:memory:' R2_ACCOUNT_ID=x R2_ACCESS_KEY_ID=x \\
    R2_SECRET_ACCESS_KEY=x R2_BUCKET=x \\
    .venv/bin/python -m pytest tests/reelforge/test_sentry.py -q
"""

from __future__ import annotations

import sys
import types

import pytest

from app.config import config
from app.telemetry import sentry


class _FakeSentrySdk(types.ModuleType):
    """Minimal stand-in for ``sentry_sdk`` recording init/tag calls."""

    def __init__(self) -> None:
        super().__init__("sentry_sdk")
        self.init_calls: list[dict] = []
        self.tags: dict[str, str] = {}

    def init(self, **kwargs) -> None:
        self.init_calls.append(kwargs)

    def set_tag(self, key: str, value: str) -> None:
        self.tags[key] = value


@pytest.fixture(autouse=True)
def _reset_init_state(monkeypatch):
    """Isolate each test: fresh sentry config + no leaked init bookkeeping."""
    monkeypatch.setattr(
        sentry, "_initialised_components", set(), raising=True
    )
    # Neutralise integration discovery so tests never import optional extras.
    monkeypatch.setattr(sentry, "_build_integrations", lambda: [], raising=True)
    # Replace the whole [sentry] section with a plain dict copy so writes here
    # cannot mutate the shared process config.
    monkeypatch.setattr(
        config,
        "sentry",
        {"dsn": "", "environment": "", "traces_sample_rate": 0.0},
        raising=True,
    )
    yield


def _install_fake_sdk(monkeypatch) -> _FakeSentrySdk:
    fake = _FakeSentrySdk()
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    return fake


def test_init_sentry_noop_when_dsn_empty(monkeypatch):
    """Empty dsn -> returns False and never imports sentry_sdk."""
    fake = _install_fake_sdk(monkeypatch)
    config.sentry["dsn"] = ""

    result = sentry.init_sentry("api")

    assert result is False
    assert fake.init_calls == []
    assert "api" not in sentry._initialised_components


def test_init_sentry_noop_when_dsn_whitespace(monkeypatch):
    """Whitespace-only dsn is treated as unset (NO-OP)."""
    fake = _install_fake_sdk(monkeypatch)
    config.sentry["dsn"] = "   "

    assert sentry.init_sentry("worker") is False
    assert fake.init_calls == []


def test_init_sentry_calls_init_when_dsn_set(monkeypatch):
    """Non-empty dsn -> sentry_sdk.init called with configured values."""
    fake = _install_fake_sdk(monkeypatch)
    config.sentry["dsn"] = "https://key@o1.ingest.sentry.io/2"
    config.sentry["environment"] = "production"
    config.sentry["traces_sample_rate"] = 0.25

    result = sentry.init_sentry("api")

    assert result is True
    assert len(fake.init_calls) == 1
    call = fake.init_calls[0]
    assert call["dsn"] == "https://key@o1.ingest.sentry.io/2"
    assert call["environment"] == "production"
    assert call["traces_sample_rate"] == 0.25
    assert fake.tags.get("component") == "api"
    assert "api" in sentry._initialised_components


def test_init_sentry_is_idempotent_per_component(monkeypatch):
    """A second call for the same component does not re-init."""
    fake = _install_fake_sdk(monkeypatch)
    config.sentry["dsn"] = "https://key@o1.ingest.sentry.io/2"

    assert sentry.init_sentry("worker") is True
    assert sentry.init_sentry("worker") is False
    assert len(fake.init_calls) == 1


def test_init_sentry_noop_when_sdk_missing(monkeypatch):
    """Missing sentry_sdk import -> returns False, does not raise."""
    monkeypatch.setitem(sys.modules, "sentry_sdk", None)
    config.sentry["dsn"] = "https://key@o1.ingest.sentry.io/2"

    # ``import sentry_sdk`` with a None entry raises ImportError, which
    # init_sentry must swallow and report as disabled.
    assert sentry.init_sentry("api") is False


def test_init_sentry_clamps_invalid_sample_rate(monkeypatch):
    """A bad traces_sample_rate falls back to 0.0 rather than raising."""
    fake = _install_fake_sdk(monkeypatch)
    config.sentry["dsn"] = "https://key@o1.ingest.sentry.io/2"
    config.sentry["traces_sample_rate"] = "not-a-number"

    assert sentry.init_sentry("api") is True
    assert fake.init_calls[0]["traces_sample_rate"] == 0.0


def test_init_sentry_environment_none_when_blank(monkeypatch):
    """Blank environment is passed as None (Sentry treats it as unset)."""
    fake = _install_fake_sdk(monkeypatch)
    config.sentry["dsn"] = "https://key@o1.ingest.sentry.io/2"
    config.sentry["environment"] = ""

    assert sentry.init_sentry("api") is True
    assert fake.init_calls[0]["environment"] is None
