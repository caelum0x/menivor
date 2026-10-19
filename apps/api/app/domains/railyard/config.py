"""Railyard configuration + env gates (Python mirror of ``railyard/config.ts``).

Each Railyard service is entirely OPT-IN and env-gated. When a service's env is
unset, ``is_*_enabled`` is ``False`` and ReelForge keeps its existing direct
provider path. The Railyard hop is never a hard dependency and never a silent
failure.

Services + env (only the LLM slice ReelForge uses):

    RELAY  (LLM gateway)      RELAY_URL     (optional RELAY_API_KEY when auth on)
    ABACUS (per-key caps)     ABACUS_URL    + ABACUS_API_KEY  (+ ABACUS_AGENT_ID)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

# A read-only environment mapping (``os.environ`` by default).
RailyardEnv = Mapping[str, Optional[str]]

# Documented service default (mirrors the Abacus server's own default bind).
ABACUS_DEFAULT_URL = "http://127.0.0.1:8100"

# Default per-request timeout for Railyard HTTP calls (seconds).
RAILYARD_HTTP_TIMEOUT_S = 15.0


def _read(env: RailyardEnv, key: str) -> Optional[str]:
    """Return a trimmed non-empty env value, or ``None``."""
    raw = env.get(key)
    trimmed = raw.strip() if isinstance(raw, str) else ""
    return trimmed or None


def _normalize_base_url(url: str) -> str:
    """Strip trailing slashes so a path can be safely appended."""
    return url.rstrip("/")


def _env(env: Optional[RailyardEnv]) -> RailyardEnv:
    return env if env is not None else os.environ


# ── RELAY (LLM gateway) ──────────────────────────────────────────────────────
# gateway.auth is OFF by default, so there is no client credential today. Enabled
# on RELAY_URL alone; an optional RELAY_API_KEY is forwarded as a Bearer token if
# the owner later turns gateway auth on.
@dataclass(frozen=True)
class RelayConfig:
    configured: bool
    base_url: Optional[str]
    #: OpenAI-SDK base URL: ``${RELAY_URL}/openai/v1``.
    openai_base_url: Optional[str]
    api_key: Optional[str]
    note: str


def get_relay_config(env: Optional[RailyardEnv] = None) -> RelayConfig:
    env = _env(env)
    url = _read(env, "RELAY_URL")
    api_key = _read(env, "RELAY_API_KEY")
    if not url:
        return RelayConfig(
            configured=False,
            base_url=None,
            openai_base_url=None,
            api_key=None,
            note="Relay disabled — set RELAY_URL to route LLM calls through the Railyard gateway.",
        )
    base_url = _normalize_base_url(url)
    return RelayConfig(
        configured=True,
        base_url=base_url,
        openai_base_url=f"{base_url}/openai/v1",
        api_key=api_key,
        note="Relay configured.",
    )


def is_relay_enabled(env: Optional[RailyardEnv] = None) -> bool:
    return get_relay_config(env).configured


# ── ABACUS (per-key LLM spend caps) ──────────────────────────────────────────
@dataclass(frozen=True)
class AbacusConfig:
    configured: bool
    base_url: str
    api_key: Optional[str]
    #: Per-key agent identity, sent as ``X-Abacus-Agent: agent_<id>``.
    agent_id: Optional[str]
    note: str


def get_abacus_config(env: Optional[RailyardEnv] = None) -> AbacusConfig:
    env = _env(env)
    url = _read(env, "ABACUS_URL")
    api_key = _read(env, "ABACUS_API_KEY")
    agent_id = _read(env, "ABACUS_AGENT_ID")
    if not url or not api_key:
        return AbacusConfig(
            configured=False,
            base_url=_normalize_base_url(url or ABACUS_DEFAULT_URL),
            api_key=None,
            agent_id=agent_id,
            note="Abacus disabled — set ABACUS_URL + ABACUS_API_KEY to cap per-key LLM spend.",
        )
    return AbacusConfig(
        configured=True,
        base_url=_normalize_base_url(url),
        api_key=api_key,
        agent_id=agent_id,
        note="Abacus configured.",
    )


def is_abacus_enabled(env: Optional[RailyardEnv] = None) -> bool:
    return get_abacus_config(env).configured
