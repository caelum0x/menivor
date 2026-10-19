"""Minimal, dependency-free ``.env`` loader for local development.

Docker Compose already injects environment via ``env_file`` / ``environment``,
so this loader exists only to make plain ``python -m …`` / ``pytest`` runs read a
repo-root ``.env`` (e.g. ``NEON_DATABASE_URL=…`` for Neon Postgres) without
requiring ``python-dotenv``.

Rules:
* Only variables **not already set** in ``os.environ`` are applied, so an
  explicit export or a Compose-provided value always wins (never overridden).
* Supports ``KEY=VALUE`` lines, ``#`` comments, blank lines, ``export KEY=…``,
  and surrounding single/double quotes. Malformed lines are skipped, not fatal.
* Loads at most once per process.
"""

from __future__ import annotations

import os
from pathlib import Path

from loguru import logger

# Files checked in priority order; the first value seen for a key wins (and an
# existing os.environ value beats all of them).
_ENV_FILENAMES = (".env", ".env.reelforge")

# Set to 1/true/yes to skip dotenv loading entirely (the pytest session does this
# so a developer's real ``.env`` never leaks keys or launch flags into tests).
DISABLE_ENV_VAR = "REELFORGE_DISABLE_DOTENV"

_loaded = False


def _parse_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].strip()
    if "=" not in stripped:
        return None
    key, _, value = stripped.partition("=")
    key = key.strip()
    if not key:
        return None
    value = value.strip()
    # Strip a single matching pair of surrounding quotes.
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return key, value


def load_local_dotenv(root_dir: str | os.PathLike[str]) -> int:
    """Load repo-root dotenv files into ``os.environ`` (missing keys only).

    Returns the number of variables applied. Never raises — a read error is
    logged and treated as "nothing to load" so config import can never crash on
    a malformed or unreadable dotenv file.
    """
    global _loaded
    if _loaded:
        return 0
    _loaded = True
    if os.environ.get(DISABLE_ENV_VAR, "").strip().lower() in {"1", "true", "yes"}:
        logger.debug(f"local dotenv loading disabled via {DISABLE_ENV_VAR}")
        return 0

    applied = 0
    for filename in _ENV_FILENAMES:
        path = Path(root_dir) / filename
        try:
            if not path.is_file():
                continue
            for raw in path.read_text(encoding="utf-8").splitlines():
                parsed = _parse_line(raw)
                if parsed is None:
                    continue
                key, value = parsed
                if key not in os.environ:
                    os.environ[key] = value
                    applied += 1
        except Exception as exc:  # noqa: BLE001 - never fatal at startup
            logger.debug(f"skipping dotenv file {path}: {exc}")
    if applied:
        logger.info(f"loaded {applied} variable(s) from local dotenv file(s)")
    return applied
