"""Concurrent streams per viewer (MV5): a third stream on a two-stream plan is refused.

Each playback session is a Redis key with a short TTL that the stream renews
on every manifest, key or segment request. Starting playback counts the
viewer's other live sessions. If Redis is unreachable the check lets the
stream start and logs it (playback stays up).
"""

from __future__ import annotations

import os
import time
from typing import Any, Protocol

from loguru import logger

SESSION_TTL_S = 90
DEFAULT_MAX_STREAMS = 2


class Store(Protocol):
    def active(self, viewer: str, now: float) -> list[str]: ...
    def touch(self, viewer: str, session_id: str, now: float) -> None: ...
    def drop(self, viewer: str, session_id: str) -> None: ...


class RedisStore:
    """``ott:streams:<viewer>`` is a sorted set of session id -> last seen."""

    def __init__(self, client: Any = None) -> None:
        self._client = client

    def _redis(self) -> Any:
        if self._client is None:
            from app.services.billing.service import _get_redis

            self._client = _get_redis()
        return self._client

    def active(self, viewer: str, now: float) -> list[str]:
        client = self._redis()
        key = f"ott:streams:{viewer}"
        client.zremrangebyscore(key, 0, now - SESSION_TTL_S)
        return [m.decode() if isinstance(m, bytes) else str(m) for m in client.zrange(key, 0, -1)]

    def touch(self, viewer: str, session_id: str, now: float) -> None:
        client = self._redis()
        key = f"ott:streams:{viewer}"
        client.zadd(key, {session_id: now})
        client.expire(key, SESSION_TTL_S * 2)

    def drop(self, viewer: str, session_id: str) -> None:
        self._redis().zrem(f"ott:streams:{viewer}", session_id)


class MemoryStore:
    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, float]] = {}

    def active(self, viewer: str, now: float) -> list[str]:
        live = {s: t for s, t in self.sessions.get(viewer, {}).items() if t > now - SESSION_TTL_S}
        self.sessions[viewer] = live
        return list(live)

    def touch(self, viewer: str, session_id: str, now: float) -> None:
        self.sessions.setdefault(viewer, {})[session_id] = now

    def drop(self, viewer: str, session_id: str) -> None:
        self.sessions.get(viewer, {}).pop(session_id, None)


_STORE: Store | None = None


def store() -> Store:
    global _STORE
    if _STORE is None:
        _STORE = RedisStore()
    return _STORE


def max_streams() -> int:
    try:
        return max(1, int(os.getenv("OTT_MAX_STREAMS") or DEFAULT_MAX_STREAMS))
    except ValueError:
        return DEFAULT_MAX_STREAMS


def admit(viewer: str, session_id: str, *, limit: int | None = None, now: float | None = None,
          backend: Store | None = None) -> bool:
    """Register a new stream; ``False`` when the viewer already has ``limit`` other live streams."""
    moment = now or time.time()
    cap = limit or max_streams()
    try:
        chosen = backend or store()
        others = [s for s in chosen.active(viewer, moment) if s != session_id]
        if len(others) >= cap:
            return False
        chosen.touch(viewer, session_id, moment)
        return True
    except Exception as exc:  # noqa: BLE001 - a limiter outage never stops playback
        logger.warning(f"ott stream limit unavailable: {type(exc).__name__}")
        return True


def renew(viewer: str, session_id: str, *, now: float | None = None, backend: Store | None = None) -> None:
    try:
        (backend or store()).touch(viewer, session_id, now or time.time())
    except Exception:  # noqa: BLE001 - renewal is best-effort
        pass


__all__ = ["DEFAULT_MAX_STREAMS", "MemoryStore", "RedisStore", "SESSION_TTL_S", "admit", "max_streams", "renew",
           "store"]
