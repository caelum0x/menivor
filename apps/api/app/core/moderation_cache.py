"""24h decision cache for prompt moderation, keyed by a hash of the text.

Only the decision and categories are stored (never the text); the key is
``menivor:moderation:<provider>:<policy version>:<sha256(text)>``. Redis is
best-effort: when it is unconfigured or unreachable every call is a miss and
moderation simply runs live. Set ``MENIVOR_MODERATION_CACHE=off`` to disable.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from loguru import logger

from app.core.moderation_types import DECISIONS, ModerationResult

TTL_SECONDS = 24 * 60 * 60
KEY_PREFIX = "menivor:moderation"

_client: Any = None
_initialized = False


def cache_enabled() -> bool:
    raw = (os.getenv("MENIVOR_MODERATION_CACHE") or "on").strip().lower()
    return raw not in {"off", "0", "false", "no", "disabled"}


def _get_client() -> Any:
    """Lazily build a Redis client from the [app] redis keys, or ``None``."""
    global _client, _initialized
    if _initialized:
        return _client
    _initialized = True
    try:
        import redis

        from app.config import config

        _client = redis.Redis(
            host=config.app.get("redis_host", "localhost"),
            port=int(config.app.get("redis_port", 6379) or 6379),
            db=int(config.app.get("redis_db", 0) or 0),
            password=config.app.get("redis_password") or None,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
    except Exception as exc:  # noqa: BLE001 - cache is best-effort
        logger.warning(f"moderation cache disabled, Redis client unavailable: {type(exc).__name__}")
        _client = None
    return _client


def set_client(client: Any) -> None:
    """Inject a client (tests) or ``None`` to force the no-cache path."""
    global _client, _initialized
    _client = client
    _initialized = True


def cache_key(provider: str, policy_version: str, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{KEY_PREFIX}:{provider}:{policy_version}:{digest}"


def get(key: str) -> ModerationResult | None:
    if not cache_enabled():
        return None
    client = _get_client()
    if client is None:
        return None
    try:
        raw = client.get(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"moderation cache read failed: {type(exc).__name__}")
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
        decision = str(data["decision"])
        categories = tuple(str(c) for c in data.get("categories") or [])
    except (ValueError, KeyError, TypeError):
        return None
    if decision not in DECISIONS:
        return None
    return ModerationResult(
        decision=decision,
        categories=categories,
        provider=str(data.get("provider") or ""),
        cached=True,
    )


def put(key: str, result: ModerationResult) -> None:
    if not cache_enabled():
        return
    client = _get_client()
    if client is None:
        return
    payload = json.dumps(
        {
            "decision": result.decision,
            "categories": list(result.categories),
            "provider": result.provider,
        }
    )
    try:
        client.set(key, payload, ex=TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"moderation cache write failed: {type(exc).__name__}")
