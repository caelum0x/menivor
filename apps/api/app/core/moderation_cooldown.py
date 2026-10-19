"""Per-hop cooldown for the moderation provider chain.

After a hop answers 429 it is skipped for ``MENIVOR_MODERATION_COOLDOWN_S``
seconds (default 60; a larger ``Retry-After`` wins, capped at 300) so a
rate-limited provider is not hammered while the next hop serves traffic. State
is in-process (per API worker) and keyed only by hop name.
"""

from __future__ import annotations

import os
import threading
import time

DEFAULT_COOLDOWN_S = 60.0
MAX_COOLDOWN_S = 300.0

_lock = threading.Lock()
_until: dict[str, float] = {}


def _now() -> float:
    return time.monotonic()


def default_cooldown_s() -> float:
    raw = (os.getenv("MENIVOR_MODERATION_COOLDOWN_S") or "").strip()
    try:
        return min(MAX_COOLDOWN_S, max(0.0, float(raw))) if raw else DEFAULT_COOLDOWN_S
    except ValueError:
        return DEFAULT_COOLDOWN_S


def trip(hop: str, retry_after_s: float | None = None) -> float:
    """Start (or extend) the cooldown for ``hop``; returns the window in seconds."""
    window = default_cooldown_s()
    if retry_after_s is not None and retry_after_s > window:
        window = min(MAX_COOLDOWN_S, retry_after_s)
    with _lock:
        _until[hop] = max(_until.get(hop, 0.0), _now() + window)
    return window


def active(hop: str) -> bool:
    with _lock:
        until = _until.get(hop)
        if until is None:
            return False
        if _now() >= until:
            _until.pop(hop, None)
            return False
        return True


def reset() -> None:
    """Clear every cooldown (tests, operator reload)."""
    with _lock:
        _until.clear()
