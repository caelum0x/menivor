"""Unit tests for the shared money helpers and the local dotenv loader.

These pure helpers underpin every catalog/wallet amount, so their rounding,
validation, and precedence rules are asserted directly (the API tests exercise
the happy paths; these cover the edges).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.env import _parse_line, load_local_dotenv
from app.core.money import (
    MICRODOLLARS_PER_USD,
    micros_to_usd_decimal,
    micros_to_usd_str,
    usd_to_micros,
)


# =========================================================================== #
# money
# =========================================================================== #
@pytest.mark.parametrize(
    "value,expected",
    [
        ("20.00", 20_000_000),
        ("0", 0),
        (None, 0),
        ("", 0),
        ("2.5", 2_500_000),
        (Decimal("1.234567"), 1_234_567),
        # HALF_UP rounding at the microdollar boundary.
        ("0.0000005", 1),
        (5, 5_000_000),
    ],
)
def test_usd_to_micros(value, expected):
    assert usd_to_micros(value) == expected


@pytest.mark.parametrize("bad", ["abc", "-1", "nan", "inf", "1e400"])
def test_usd_to_micros_rejects_bad(bad):
    with pytest.raises(ValueError):
        usd_to_micros(bad)


def test_usd_to_micros_rejects_over_max():
    with pytest.raises(ValueError):
        usd_to_micros("2000000")  # above the $1,000,000 ceiling


def test_micros_display_roundtrip():
    assert micros_to_usd_str(21_000_000) == "21.00"
    assert micros_to_usd_str(0) == "0.00"
    assert micros_to_usd_str(None) == "0.00"
    assert micros_to_usd_decimal(2_500_000) == Decimal("2.5")
    assert MICRODOLLARS_PER_USD == 1_000_000


# =========================================================================== #
# dotenv loader
# =========================================================================== #
def test_parse_line_variants():
    assert _parse_line("KEY=value") == ("KEY", "value")
    assert _parse_line("export KEY=value") == ("KEY", "value")
    assert _parse_line('KEY="quoted value"') == ("KEY", "quoted value")
    assert _parse_line("KEY='single'") == ("KEY", "single")
    assert _parse_line("# comment") is None
    assert _parse_line("") is None
    assert _parse_line("no_equals_here") is None


def test_load_local_dotenv_missing_keys_only(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "NEON_DATABASE_URL=postgresql://from-dotenv\nFOO_ONLY=bar\n", encoding="utf-8"
    )
    # An already-set var must NOT be overridden by the dotenv file.
    monkeypatch.setenv("NEON_DATABASE_URL", "postgresql://explicit")
    monkeypatch.delenv("FOO_ONLY", raising=False)

    # Reset the module-level load-once guard so this test controls loading.
    import app.core.env as env_mod

    monkeypatch.setattr(env_mod, "_loaded", False)
    # The test session disables dotenv loading (conftest); re-enable it here.
    monkeypatch.delenv(env_mod.DISABLE_ENV_VAR, raising=False)

    applied = load_local_dotenv(tmp_path)
    assert applied == 1  # only FOO_ONLY applied; NEON left untouched
    import os

    assert os.environ["NEON_DATABASE_URL"] == "postgresql://explicit"
    assert os.environ["FOO_ONLY"] == "bar"


def test_load_local_dotenv_load_once(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("ONE_TIME=1\n", encoding="utf-8")
    import app.core.env as env_mod

    monkeypatch.setattr(env_mod, "_loaded", False)
    monkeypatch.delenv(env_mod.DISABLE_ENV_VAR, raising=False)
    monkeypatch.delenv("ONE_TIME", raising=False)
    assert load_local_dotenv(tmp_path) == 1
    # Second call is a no-op regardless of file contents.
    assert load_local_dotenv(tmp_path) == 0


def test_load_local_dotenv_disabled_by_switch(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("DISABLED_ONLY=1\n", encoding="utf-8")
    import os

    import app.core.env as env_mod

    monkeypatch.setattr(env_mod, "_loaded", False)
    monkeypatch.setenv(env_mod.DISABLE_ENV_VAR, "1")
    monkeypatch.delenv("DISABLED_ONLY", raising=False)
    assert load_local_dotenv(tmp_path) == 0
    assert "DISABLED_ONLY" not in os.environ
