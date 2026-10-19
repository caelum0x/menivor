"""The pytest session is hermetic: no local .env, config.toml or exported keys.

Guards the conftest that keeps a developer machine's real ``.env`` (database,
R2, Mint, provider keys, pilot flags) and untracked ``config.toml`` from
changing test outcomes or triggering live calls.
"""

from __future__ import annotations

import os
from pathlib import Path

from tests.reelforge import _session_env as session_env

REPO = Path(__file__).resolve().parents[2]


def test_dotenv_loading_is_disabled_for_the_session():
    assert os.environ.get("REELFORGE_DISABLE_DOTENV") == "1"


def test_config_is_an_isolated_copy_of_the_tracked_example():
    from app.config import config

    config_file = Path(config.config_file)
    assert config_file.name == "config.toml"
    assert config_file.parent != REPO  # never the developer's local config.toml
    assert str(config_file) == os.environ["REELFORGE_CONFIG_FILE"]


def test_launch_and_storage_env_is_pinned():
    for name, value in session_env.PINNED_ENV.items():
        assert os.environ.get(name) == value, name


def test_live_endpoints_and_keys_are_not_inherited():
    # Values from a local .env / .env.reelforge must never reach the tests.
    for name in (
        "MINT_SERVER_URL",
        "MINT_API_KEY",
        "DATABASE_URL",
        "REELFORGE_DATABASE_URL",
        "REDIS_HOST",
        "REPLICATE_API_TOKEN",
        "ANTHROPIC_API_KEY",
        "SENTRY_DSN",
        "R2_BUCKET_NAME",
        "R2_S3_ENDPOINT",
    ):
        if os.environ.get(session_env.KEEP_ENV_FLAG):
            break
        assert name not in os.environ, name


def test_third_party_load_dotenv_is_a_noop(tmp_path, monkeypatch):
    import dotenv

    (tmp_path / ".env").write_text("THIRD_PARTY_LEAK=1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("THIRD_PARTY_LEAK", raising=False)
    dotenv.load_dotenv()
    dotenv.load_dotenv(tmp_path / ".env")
    assert "THIRD_PARTY_LEAK" not in os.environ


def test_scrub_selects_behaviour_changing_vars_only():
    environ = {
        "MINT_SERVER_URL": "http://mint",
        "REELFORGE_LAUNCH_MODE": "internal_pilot",
        "REELFORGE_BACKEND_ROOT": "/repo/apps/api",
        "DATABASE_URL": "postgres://x",
        "ANTHROPIC_API_KEY": "k",
        "PATH": "/usr/bin",
        "HOME": "/home/dev",
    }
    assert session_env.scrubbed_names(environ) == [
        "ANTHROPIC_API_KEY",
        "DATABASE_URL",
        "MINT_SERVER_URL",
        "REELFORGE_LAUNCH_MODE",
    ]
