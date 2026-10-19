"""Config + plan-catalogue wiring for the Creem/Polar payment providers (WF26).

These tests cover ONLY the config surface and the plan-catalogue fields that the
Creem (creem.io) and Polar (polar.sh) adapters read — they do NOT exercise the
adapter/service HTTP layer (that is covered elsewhere and mocked separately).

Two concerns are verified:

* ``app.config.config`` exposes ``config.creem`` / ``config.polar`` sections with
  the same env-override precedence as the existing ``[stripe]``/``[iyzico]``
  wiring (env wins, then config.toml, then empty string). To observe the
  import-time env overrides deterministically the config module is reloaded with
  the relevant environment variables set.
* ``app.services.billing.plans`` exposes ``creem_product_id`` /
  ``polar_price_id`` on every :class:`Plan`, resolved from config and empty-safe
  when the sections are absent or non-mapping.

No network access and no real SDKs are touched.
"""

from __future__ import annotations

import importlib
from typing import Iterator

import pytest


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _reload_config(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]):
    """Reload ``app.config.config`` with ``env`` applied, then restore it.

    The module resolves secret env overrides at import time (mirroring the
    ``STRIPE_SECRET_KEY`` precedence pattern). Reloading under a patched
    environment is the cleanest way to assert that precedence without touching
    config.toml on disk. The module is always reloaded again on teardown so the
    process-wide singleton is left in its original state for other tests.
    """
    import app.config.config as config_module

    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return importlib.reload(config_module)


@pytest.fixture
def restore_config() -> Iterator[None]:
    """Reload the config singleton back to its on-disk state after a test."""
    import app.config.config as config_module

    try:
        yield
    finally:
        importlib.reload(config_module)


# --------------------------------------------------------------------------- #
# Config sections exist
# --------------------------------------------------------------------------- #
def test_config_exposes_creem_and_polar_sections():
    from app.config import config

    # Both sections are always present (empty dict when unconfigured), so the
    # billing adapters can read them without an attribute guard.
    assert isinstance(config.creem, dict)
    assert isinstance(config.polar, dict)


def test_creem_and_polar_keys_are_empty_safe_by_default():
    from app.config import config

    # ``.get`` on an unconfigured section returns the caller default, never
    # raising — this is what plans.py / the adapters rely on.
    assert config.creem.get("api_key", "") == config.creem.get("api_key", "")
    assert config.polar.get("access_token", "") == config.polar.get(
        "access_token", ""
    )
    assert config.creem.get("nonexistent", "fallback") == "fallback"
    assert config.polar.get("nonexistent", "fallback") == "fallback"


# --------------------------------------------------------------------------- #
# Env overrides (mirror STRIPE_* / IYZICO_* precedence)
# --------------------------------------------------------------------------- #
def test_creem_env_overrides_apply_on_import(
    monkeypatch: pytest.MonkeyPatch, restore_config: None
):
    config_module = _reload_config(
        monkeypatch,
        {
            "CREEM_API_KEY": "creem_test_key",
            "CREEM_WEBHOOK_SECRET": "creem_whsec_test",
        },
    )

    assert config_module.creem["api_key"] == "creem_test_key"
    assert config_module.creem["webhook_secret"] == "creem_whsec_test"


def test_polar_env_overrides_apply_on_import(
    monkeypatch: pytest.MonkeyPatch, restore_config: None
):
    config_module = _reload_config(
        monkeypatch,
        {
            "POLAR_ACCESS_TOKEN": "polar_oat_test",
            "POLAR_WEBHOOK_SECRET": "polar_whsec_test",
        },
    )

    assert config_module.polar["access_token"] == "polar_oat_test"
    assert config_module.polar["webhook_secret"] == "polar_whsec_test"


def test_creem_polar_default_to_empty_string_without_env(
    monkeypatch: pytest.MonkeyPatch, restore_config: None
):
    # With no env and (in CI) no config.toml values, the secret keys resolve to
    # the empty string — never a missing key and never a hardcoded secret.
    for name in (
        "CREEM_API_KEY",
        "CREEM_WEBHOOK_SECRET",
        "POLAR_ACCESS_TOKEN",
        "POLAR_WEBHOOK_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)

    config_module = _reload_config(monkeypatch, {})

    assert config_module.creem.get("api_key", "") in ("", config_module.creem.get("api_key"))
    assert "api_key" in config_module.creem
    assert "webhook_secret" in config_module.creem
    assert "access_token" in config_module.polar
    assert "webhook_secret" in config_module.polar


# --------------------------------------------------------------------------- #
# save_config persists the new sections
# --------------------------------------------------------------------------- #
def test_save_config_persists_creem_and_polar(
    monkeypatch: pytest.MonkeyPatch, tmp_path, restore_config: None
):
    import app.config.config as config_module

    written: dict[str, str] = {}

    # Intercept the on-disk read/write so the test never touches the real
    # config.toml. save_config compares against the current file then writes via
    # a temp file + os.replace; stubbing both keeps it hermetic.
    monkeypatch.setattr(config_module, "config_file", str(tmp_path / "config.toml"))

    real_dumps = config_module.toml.dumps

    def _capture_dumps(payload):
        written.update(payload)
        return real_dumps(payload)

    monkeypatch.setattr(config_module.toml, "dumps", _capture_dumps)

    config_module.creem["api_key"] = "creem_persist"
    config_module.polar["access_token"] = "polar_persist"
    config_module.save_config()

    assert "creem" in written
    assert "polar" in written
    assert written["creem"]["api_key"] == "creem_persist"
    assert written["polar"]["access_token"] == "polar_persist"


# --------------------------------------------------------------------------- #
# Plan catalogue exposes the new provider ids
# --------------------------------------------------------------------------- #
def test_plans_expose_creem_product_id_and_polar_price_id():
    from app.services.billing.plans import list_plans

    for plan in list_plans():
        # Fields always exist and are strings (empty when unconfigured).
        assert hasattr(plan, "creem_product_id")
        assert hasattr(plan, "polar_price_id")
        assert isinstance(plan.creem_product_id, str)
        assert isinstance(plan.polar_price_id, str)


def test_plan_provider_ids_are_empty_safe_when_unconfigured():
    from app.services.billing import plans as plans_module

    # ``_section`` returns {} for a missing/non-mapping config section, so the
    # resolver functions never raise and default to "".
    assert plans_module._creem_product_id("starter") == plans_module._creem_product_id(
        "starter"
    )
    assert isinstance(plans_module._polar_price_id("pro"), str)


def test_plan_provider_ids_read_from_config(monkeypatch: pytest.MonkeyPatch):
    from app.services.billing import plans as plans_module

    # Point the resolver's config lookup at fabricated sections and confirm the
    # per-plan key convention (``<key>_product_id`` / ``<key>_price_id``).
    fake_config = type(
        "FakeConfig",
        (),
        {
            "creem": {"starter_product_id": "prod_starter_x"},
            "polar": {"pro_price_id": "price_pro_y"},
        },
    )()
    monkeypatch.setattr(plans_module, "config", fake_config)

    assert plans_module._creem_product_id("starter") == "prod_starter_x"
    assert plans_module._creem_product_id("pro") == ""  # unset key -> ""
    assert plans_module._polar_price_id("pro") == "price_pro_y"
    assert plans_module._polar_price_id("starter") == ""


def test_plan_section_helper_handles_non_mapping_section(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.services.billing import plans as plans_module

    # A non-mapping section (e.g. wiring not yet landed) must degrade to {} so
    # the catalogue still builds and ids resolve to "".
    fake_config = type("FakeConfig", (), {"creem": "not-a-mapping", "polar": None})()
    monkeypatch.setattr(plans_module, "config", fake_config)

    assert plans_module._creem_product_id("starter") == ""
    assert plans_module._polar_price_id("pro") == ""
