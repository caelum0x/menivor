"""Unit coverage for the controlled internal-generation pilot policy."""

from __future__ import annotations

import pytest

from app.config import config
from app.models.exception import HttpException
from app.services import pilot


def test_pilot_capabilities_are_fail_closed_for_an_empty_allowlist(monkeypatch):
    monkeypatch.setitem(config.app, "pilot_enabled", True)
    monkeypatch.setitem(config.app, "pilot_allowlist", [])

    capabilities = pilot.capabilities_for_user("not-admitted")

    assert capabilities["mode"] == "internal_pilot"
    assert capabilities["generation"] == {"reels": False, "broll": False}


def test_pilot_rejects_unlisted_user_before_rate_or_credit_work(monkeypatch):
    monkeypatch.setitem(config.app, "pilot_enabled", True)
    monkeypatch.setitem(config.app, "pilot_allowlist", ["admitted"])

    with pytest.raises(HttpException) as raised:
        pilot.require_generation_access(
            request=object(),
            session=object(),
            user_id="not-admitted",
            kind="reel",
            credits=1,
            request_id="pilot-test",
        )

    assert raised.value.status_code == 403


def test_pilot_debit_reason_is_auditable(monkeypatch):
    monkeypatch.setitem(config.app, "pilot_enabled", True)
    assert pilot.pilot_debit_reason("reel", "job_debit") == "pilot_reel_debit"
    assert pilot.pilot_debit_reason("broll", "broll_gen_debit") == "pilot_broll_debit"
