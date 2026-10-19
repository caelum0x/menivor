"""Hermetic environment for the ReelForge/Menivor API test session.

``tests/reelforge/conftest.py`` calls :func:`apply_hermetic_env` before pytest
imports any test module (and so before ``app.config`` is first imported). It
stops a developer machine's local state from changing test outcomes:

* ``REELFORGE_DISABLE_DOTENV=1``: the repo-root ``.env`` / ``.env.reelforge``
  (real database, R2, Mint and provider keys, pilot launch flags) are never
  loaded into ``os.environ``. Third-party ``load_dotenv()`` calls (litellm
  runs one on import) are turned into no-ops too.
* ``REELFORGE_CONFIG_FILE``: config is read from a throwaway copy of the tracked
  ``config.example.toml``, never the developer's untracked ``config.toml``,
  which may carry pilot gates, real keys and local provider URLs. The copy also
  absorbs any ``save_config()`` writes a test triggers.
* Exported shell variables that change runtime behaviour (launch mode, Mint,
  Redis, database, R2, billing and provider keys) are removed, and then the
  same pinned values ``make -f Makefile.reelforge test`` and CI use are applied.
  This also keeps the suite from making real paid provider calls.

Live integration runs (for example against a local mint-server through
``MINT_SERVER_URL``) can opt out of the scrub with
``REELFORGE_TEST_KEEP_ENV=1``. Dotenv loading and the config isolation stay on
in that mode, so a variable reaches the tests only if it was exported on purpose.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLE_CONFIG = _REPO_ROOT / "config.example.toml"

KEEP_ENV_FLAG = "REELFORGE_TEST_KEEP_ENV"

# Variables the suite always controls. The first nine match CI and
# Makefile.reelforge's PYTHON_TEST. Signup is opened too, so the default test
# posture is a fully open public launch. Tests that exercise a closed gate
# monkeypatch the flag back off.
PINNED_ENV: dict[str, str] = {
    "NEON_DATABASE_URL": "sqlite:///:memory:",
    "R2_ACCOUNT_ID": "x",
    "R2_ACCESS_KEY_ID": "x",
    "R2_SECRET_ACCESS_KEY": "x",
    "R2_BUCKET": "x",
    "REELFORGE_LAUNCH_MODE": "public",
    "REELFORGE_PUBLIC_LAUNCH_APPROVED": "true",
    "REELFORGE_CHECKOUT_ENABLED": "true",
    "REELFORGE_PUBLISHING_ENABLED": "true",
    "REELFORGE_SIGNUP_ENABLED": "true",
    # M3.3: production (public launch) defaults to the client-allowlisted API
    # surface and frozen P2P transfers. The suite exercises every route, so it
    # pins the full surface; test_m3_3_api_surface.py covers the allowlist.
    "MENIVOR_API_SURFACE": "full",
    "MENIVOR_WALLET_P2P_TRANSFERS": "on",
    # litellm calls python-dotenv's load_dotenv() on import unless it runs in
    # PRODUCTION mode, which would pull the repo-root .env back in.
    "LITELLM_MODE": "PRODUCTION",
}

# Exported variables with any of these prefixes are removed before the pins are
# applied (unless KEEP_ENV_FLAG is set).
SCRUB_PREFIXES: tuple[str, ...] = (
    "REELFORGE_",
    "MINT_",
    "R2_",
    "REDIS_",
    "SENTRY_",
    "IDENTITY_LOCK_",
    "CLERK_",
    "STRIPE_",
    "IYZICO_",
    "CREEM_",
    "POLAR_",
    "REVENUECAT_",
    "RAGO_",
    "RELAY_",
    "ABACUS_",
    "RAILYARD_",
    "RUNPOD_",
    "COMFYUI_",
    "PILOT_",
)

# Individual exported variables to remove (database URLs and provider keys).
SCRUB_NAMES: frozenset[str] = frozenset(
    {
        "DATABASE_URL",
        "NEON_DATABASE_URL",
        "CORS_ALLOWED_ORIGINS",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "ELEVENLABS_API_KEY",
        "HEYGEN_API_KEY",
        "REPLICATE_API_TOKEN",
        "FAL_KEY",
        "UPLOAD_POST_API_KEY",
    }
)

# Test harness variables that must survive the scrub.
PRESERVED_NAMES: frozenset[str] = frozenset(
    {
        "REELFORGE_BACKEND_ROOT",
        "REELFORGE_DISABLE_DOTENV",
        "REELFORGE_CONFIG_FILE",
        KEEP_ENV_FLAG,
    }
)


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes"}


def scrubbed_names(environ: dict[str, str] | os._Environ[str]) -> list[str]:
    """Return the names in ``environ`` the hermetic session removes."""
    return sorted(
        name
        for name in environ
        if name not in PRESERVED_NAMES
        and (name in SCRUB_NAMES or name.startswith(SCRUB_PREFIXES))
    )


def _isolated_config_file() -> str:
    """Copy the tracked example config into a private temp dir."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="reelforge-test-config-"))
    atexit.register(shutil.rmtree, tmp_dir, ignore_errors=True)
    target = tmp_dir / "config.toml"
    if _EXAMPLE_CONFIG.is_file():
        shutil.copyfile(_EXAMPLE_CONFIG, target)
    else:  # pragma: no cover - the example config is tracked in git
        target.write_text("[app]\n", encoding="utf-8")
    return str(target)


def _disable_third_party_dotenv() -> None:
    """Make python-dotenv's ``load_dotenv`` a no-op for this process.

    Libraries imported by the app (litellm, for one) call ``load_dotenv()`` at
    import time, which reads the developer's ``.env`` from the working
    directory: real database URLs and provider keys.
    """
    try:
        import dotenv
        import dotenv.main
    except ImportError:  # pragma: no cover - python-dotenv is optional
        return

    def _no_dotenv(*_args, **_kwargs) -> bool:
        return False

    dotenv.load_dotenv = _no_dotenv
    dotenv.main.load_dotenv = _no_dotenv


_applied = False


def apply_hermetic_env() -> None:
    """Disable dotenv, isolate config, scrub and pin env. Runs once per process."""
    global _applied
    if _applied:
        return
    _applied = True
    os.environ["REELFORGE_DISABLE_DOTENV"] = "1"
    os.environ["REELFORGE_CONFIG_FILE"] = _isolated_config_file()
    if not _is_truthy(os.environ.get(KEEP_ENV_FLAG)):
        for name in scrubbed_names(os.environ):
            os.environ.pop(name, None)
    os.environ.update(PINNED_ENV)
    # M7.1: the self-issued C2PA signer is written to a throwaway dir, never
    # to the developer's runtime storage.
    os.environ["REELFORGE_C2PA_KEY_DIR"] = str(Path(os.environ["REELFORGE_CONFIG_FILE"]).parent / "c2pa")
    _disable_third_party_dotenv()
