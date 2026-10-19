"""Unit tests for the launch-flag stage machinery (``mint_stage``).

Drives the ``local -> canary -> on`` rollout decisions off a stubbed config so no
network or live mint-server is involved. Verifies the fail-safe defaults (unknown
stage -> local; partial config -> local), the deterministic per-owner canary
bucketing, and that a fully-configured rail defaults to ``on``.
"""

from __future__ import annotations

import pytest

from app.domains.wallet import mint_stage
from app.domains.wallet.mint_stage import MintStage, should_use_mint


@pytest.fixture()
def mint_config(monkeypatch):
    """Install a mutable fake ``config.mint`` dict and return it."""
    cfg = {
        "server_url": "http://mint.test",
        "api_key": "k",
        "treasury_account": "acct_treasury",
        "stage": "",
        "rollout_percent": 0,
    }

    class _Cfg:
        mint = cfg

    import app.config as app_config

    monkeypatch.setattr(app_config, "config", _Cfg, raising=False)
    return cfg


# --------------------------------------------------------------------------- #
# Stage parsing (fail-safe)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("local", MintStage.LOCAL),
        ("canary", MintStage.CANARY),
        ("on", MintStage.ON),
        ("ON", MintStage.ON),
        ("  Canary ", MintStage.CANARY),
        ("bogus", MintStage.LOCAL),  # unknown -> local (fail safe)
        ("", MintStage.LOCAL),
        (None, MintStage.LOCAL),
    ],
)
def test_stage_parse_is_fail_safe(raw, expected):
    assert MintStage.parse(raw) is expected


# --------------------------------------------------------------------------- #
# Configuration gate
# --------------------------------------------------------------------------- #
def test_unconfigured_never_uses_mint(mint_config):
    mint_config["server_url"] = ""
    assert mint_stage.mint_configured() is False
    assert should_use_mint("owner-1") is False


def test_partial_config_is_treated_as_unconfigured(mint_config):
    mint_config["api_key"] = ""  # URL + treasury but no key
    assert mint_stage.mint_configured() is False
    assert should_use_mint("owner-1") is False


def test_fully_configured_defaults_to_on(mint_config):
    # Empty stage + fully wired rail => ON (setting the URL flips the wallet).
    assert mint_stage.current_stage() is MintStage.ON
    assert should_use_mint("anybody") is True


# --------------------------------------------------------------------------- #
# Stage routing
# --------------------------------------------------------------------------- #
def test_local_stage_is_kill_switch(mint_config):
    mint_config["stage"] = "local"
    assert mint_stage.current_stage() is MintStage.LOCAL
    # Even fully configured, local routes everyone to the local ledger.
    assert should_use_mint("owner-1") is False


def test_on_stage_routes_everyone(mint_config):
    mint_config["stage"] = "on"
    assert all(should_use_mint(f"owner-{i}") for i in range(20))


def test_canary_zero_percent_routes_nobody(mint_config):
    mint_config["stage"] = "canary"
    mint_config["rollout_percent"] = 0
    assert not any(should_use_mint(f"owner-{i}") for i in range(50))


def test_canary_hundred_percent_routes_everyone(mint_config):
    mint_config["stage"] = "canary"
    mint_config["rollout_percent"] = 100
    assert all(should_use_mint(f"owner-{i}") for i in range(50))


def test_canary_bucketing_is_deterministic_and_partial(mint_config):
    mint_config["stage"] = "canary"
    mint_config["rollout_percent"] = 50
    owners = [f"owner-{i}" for i in range(200)]
    first = {o: should_use_mint(o) for o in owners}
    # Stable across repeated calls (crypto digest, not salted hash()).
    second = {o: should_use_mint(o) for o in owners}
    assert first == second
    # A 50% slice actually splits the population (not all-or-nothing).
    routed = sum(first.values())
    assert 0 < routed < len(owners)


def test_rollout_percent_is_clamped(mint_config):
    mint_config["stage"] = "canary"
    mint_config["rollout_percent"] = 999
    assert mint_stage.rollout_percent() == 100
    mint_config["rollout_percent"] = -5
    assert mint_stage.rollout_percent() == 0
    mint_config["rollout_percent"] = "not-an-int"
    assert mint_stage.rollout_percent() == 0


def test_explicit_stage_override_beats_default(mint_config):
    # An explicit stage always wins over the configured-default ON.
    mint_config["stage"] = "canary"
    mint_config["rollout_percent"] = 0
    assert should_use_mint("owner-x") is False
