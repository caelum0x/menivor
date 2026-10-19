"""Redis-backed fixed-window rate limiter.

A small, dependency-light limiter that reuses the existing ``[app]`` redis
keys (``from app.config import config``) instead of introducing a new config
section. The limiter *fails closed*: if Redis is unreachable or misbehaving the
same fixed-window budget is enforced by an in-process bucket (per API process),
so a Redis outage never turns into unlimited generation and provider spend. The
API stays up; limits just become per-process until Redis is back.

Public surface:

* :func:`rate_limit` — low-level, framework-agnostic check returning a
  :class:`RateLimitResult`.
* :func:`enforce_rate_limit` — FastAPI helper that derives a per-caller key
  from the request and raises ``HttpException(status_code=429)`` when the
  bucket is exhausted.

The only module-level mutable state is a lazily-constructed Redis client
(guarded by a lock); everything else is pure.
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import NamedTuple, Optional

from loguru import logger

from app.config import config
from app.controllers.base import get_api_key, get_task_id
from app.models.exception import HttpException

# Atomic fixed-window counter. Runs INCR, sets the TTL only on the first hit of
# a window (current == 1), then reports the surviving TTL so callers can tell
# the client when the window resets. Doing this in one Lua round-trip removes
# the INCR/EXPIRE race where a crash between the two commands would leak a
# key with no expiry.
_FIXED_WINDOW_LUA: str = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""

# Short timeouts: a hung Redis must fail fast so we can fall back to the
# in-process bucket quickly rather than stalling the request thread.
_SOCKET_TIMEOUT_S: float = 0.25

_KEY_PREFIX: str = "reelforge:ratelimit"

# Lazy singleton client (the only module-level mutable state).
_client_lock: threading.Lock = threading.Lock()
_client: Optional["object"] = None
_client_failed: bool = False

# In-process fallback buckets: key -> (window_start_monotonic, count). Used only
# while Redis is unavailable; pruned when it grows past ``_LOCAL_MAX_KEYS``.
_local_lock: threading.Lock = threading.Lock()
_local_buckets: dict[str, tuple[float, int]] = {}
_LOCAL_MAX_KEYS: int = 20_000


class RateLimitResult(NamedTuple):
    """Outcome of a single rate-limit check.

    Attributes:
        allowed: Whether this request is permitted.
        remaining: Requests still available in the current window (>= 0).
        reset_s: Seconds until the current window resets.
    """

    allowed: bool
    remaining: int
    reset_s: int


def _build_client():
    """Construct a Redis client from the existing ``[app]`` redis config keys.

    Returns ``None`` if the redis package is unavailable so callers use the
    in-process bucket instead of raising at import/first-use time.
    """
    try:
        import redis  # imported lazily so this module parses without redis
    except Exception as exc:  # pragma: no cover - redis is a core dep
        logger.warning(f"rate limiter: redis package unavailable ({exc}); using in-process buckets")
        return None

    try:
        app_cfg = config.app
        password = app_cfg.get("redis_password", "") or None
        client = redis.Redis(
            host=app_cfg.get("redis_host", "localhost"),
            port=int(app_cfg.get("redis_port", 6379)),
            db=int(app_cfg.get("redis_db", 0)),
            password=password,
            socket_timeout=_SOCKET_TIMEOUT_S,
            socket_connect_timeout=_SOCKET_TIMEOUT_S,
            decode_responses=False,
        )
        return client
    except Exception as exc:
        logger.warning(f"rate limiter: failed to build redis client ({exc}); using in-process buckets")
        return None


def _get_client():
    """Return the lazily-built shared Redis client, or ``None`` if unavailable."""
    global _client, _client_failed
    if _client is not None or _client_failed:
        return _client
    with _client_lock:
        if _client is None and not _client_failed:
            client = _build_client()
            if client is None:
                _client_failed = True
            _client = client
    return _client


def _open_result(limit: int, window_s: int) -> RateLimitResult:
    """Misconfiguration result: allow the request and report the full budget."""
    return RateLimitResult(allowed=True, remaining=max(limit, 0), reset_s=max(window_s, 0))


def _prune_local(now: float) -> None:
    """Drop expired in-process windows (caller holds ``_local_lock``)."""
    if len(_local_buckets) < _LOCAL_MAX_KEYS:
        return
    for key in [k for k, (start, _count) in _local_buckets.items() if now - start >= 86_400]:
        _local_buckets.pop(key, None)
    if len(_local_buckets) >= _LOCAL_MAX_KEYS:
        # Still full of live windows: keep the newest half (bounded memory).
        newest = sorted(_local_buckets.items(), key=lambda item: item[1][0])[len(_local_buckets) // 2:]
        _local_buckets.clear()
        _local_buckets.update(newest)


def _local_rate_limit(key: str, limit: int, window_s: int) -> RateLimitResult:
    """Fixed-window counter held in this process (the Redis-down fallback)."""
    now = time.monotonic()
    with _local_lock:
        _prune_local(now)
        start, count = _local_buckets.get(key, (now, 0))
        if now - start >= window_s:
            start, count = now, 0
        count += 1
        _local_buckets[key] = (start, count)
    reset_s = max(1, int(window_s - (now - start)))
    return RateLimitResult(allowed=count <= limit, remaining=max(0, limit - count), reset_s=reset_s)


def reset_local_buckets() -> None:
    """Forget every in-process window (tests and operator resets)."""
    with _local_lock:
        _local_buckets.clear()


def rate_limit(key: str, limit: int, window_s: int) -> RateLimitResult:
    """Check and consume one unit against a fixed-window counter.

    Args:
        key: Logical bucket identifier (namespaced internally).
        limit: Maximum number of requests allowed per window.
        window_s: Window length in seconds.

    Returns:
        A :class:`RateLimitResult`. On any Redis error the same budget is
        enforced by the in-process bucket (fail closed) and a warning is logged.
    """
    if limit <= 0 or window_s <= 0:
        # A non-positive limit/window is a misconfiguration, not a reason to
        # block traffic; allow and surface it in the logs.
        logger.warning(
            f"rate limiter: non-positive limit={limit} or window_s={window_s} for "
            f"key={key!r}; not limiting"
        )
        return _open_result(limit, window_s)

    redis_key = f"{_KEY_PREFIX}:{key}"
    client = _get_client()
    if client is None:
        return _local_rate_limit(redis_key, limit, window_s)

    try:
        current, ttl = client.eval(_FIXED_WINDOW_LUA, 1, redis_key, window_s)
        current = int(current)
        ttl = int(ttl)
    except Exception as exc:
        logger.warning(f"rate limiter: redis error for key={key!r} ({exc}); using in-process bucket")
        return _local_rate_limit(redis_key, limit, window_s)

    # TTL can transiently be -1 (no expiry set) or -2 (key gone) around window
    # edges; normalize to the full window so clients get a sane reset hint.
    reset_s = ttl if ttl >= 0 else window_s
    remaining = max(0, limit - current)
    allowed = current <= limit
    return RateLimitResult(allowed=allowed, remaining=remaining, reset_s=reset_s)


def _caller_identity(request) -> str:
    """Best-effort stable identifier for the caller (api key, else client IP)."""
    api_key = get_api_key(request)
    if api_key:
        # Never key on the raw secret; a short hash is enough to bucket. Use a
        # deterministic digest (not Python's PYTHONHASHSEED-randomized hash())
        # so the same api_key maps to one bucket across all worker processes.
        return f"key:{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"
    client = getattr(request, "client", None)
    host = getattr(client, "host", None) if client else None
    return f"ip:{host or 'unknown'}"


def enforce_rate_limit(request, bucket: str, limit: int, window_s: int) -> RateLimitResult:
    """FastAPI helper: enforce a per-caller rate limit or raise HTTP 429.

    Args:
        request: The incoming FastAPI/Starlette ``Request``.
        bucket: Logical endpoint/action name (e.g. ``"webhook:stripe"``).
        limit: Maximum requests per window for this caller+bucket.
        window_s: Window length in seconds.

    Returns:
        The :class:`RateLimitResult` when allowed.

    Raises:
        HttpException: ``status_code=429`` when the bucket is exhausted.
    """
    key = f"{bucket}:{_caller_identity(request)}"
    result = rate_limit(key, limit, window_s)
    if not result.allowed:
        request_id = get_task_id(request)
        raise HttpException(
            task_id=request_id,
            status_code=429,
            message=(
                f"rate limit exceeded for '{bucket}': retry in {result.reset_s}s"
            ),
            data={
                "remaining": result.remaining,
                "reset_s": result.reset_s,
                "limit": limit,
                "window_s": window_s,
            },
        )
    return result
