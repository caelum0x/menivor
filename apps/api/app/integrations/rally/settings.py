"""Env settings for Menivor -> Rally lifecycle events (dogfooding Rally journeys).

OFF unless ``RALLY_EVENTS_KEY`` is set. Reading settings never opens a socket.

    RALLY_EVENTS_KEY              workspace event key (``rly_evt_...``), created on
                                  Rally's Journeys page. Server-side only.
    RALLY_EVENTS_URL              Rally base URL (default ``https://vcpeer.com``);
                                  events go to ``${RALLY_EVENTS_URL}/api/autogtm/events``
    RALLY_EVENTS_TIMEOUT_SECONDS  per-request timeout (default 3)
    RALLY_EVENTS_SOURCE           ``source`` tag on every event (default ``menivor``)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

Env = Mapping[str, Optional[str]]

DEFAULT_URL = "https://vcpeer.com"
DEFAULT_TIMEOUT_S = 3.0
DEFAULT_SOURCE = "menivor"
EVENTS_PATH = "/api/autogtm/events"
KEY_PREFIX = "rly_evt_"


def _read(env: Env, key: str) -> Optional[str]:
    raw = env.get(key)
    value = raw.strip() if isinstance(raw, str) else ""
    return value or None


@dataclass(frozen=True)
class RallySettings:
    key: Optional[str]
    base_url: str
    timeout_s: float
    source: str

    @property
    def enabled(self) -> bool:
        return bool(self.key and self.key.startswith(KEY_PREFIX))

    @property
    def events_url(self) -> str:
        return f"{self.base_url}{EVENTS_PATH}"


def load_settings(env: Optional[Env] = None) -> RallySettings:
    env = env if env is not None else os.environ
    timeout_raw = _read(env, "RALLY_EVENTS_TIMEOUT_SECONDS")
    try:
        timeout = float(timeout_raw) if timeout_raw else DEFAULT_TIMEOUT_S
    except ValueError:
        timeout = DEFAULT_TIMEOUT_S
    if timeout <= 0:
        timeout = DEFAULT_TIMEOUT_S
    base = _read(env, "RALLY_EVENTS_URL") or DEFAULT_URL
    return RallySettings(
        key=_read(env, "RALLY_EVENTS_KEY"),
        base_url=base.rstrip("/"),
        timeout_s=timeout,
        source=_read(env, "RALLY_EVENTS_SOURCE") or DEFAULT_SOURCE,
    )
