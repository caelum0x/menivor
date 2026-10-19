"""Owner-approved daily spend caps for metered AI video generation.

Every AI-video (``broll_gen``) job spends real provider money (Replicate), so
this module enforces two hard server-side ceilings BEFORE any credit debit or
enqueue:

* a GLOBAL cap — ``AI_VIDEO_DAILY_CAP`` generations per UTC day across all
  users (default 20), and
* a PER-USER cap — ``AI_VIDEO_USER_DAILY_CAP`` generations per UTC day per
  account (default 2).

Counters are Redis ``INCR`` keys bucketed by UTC day (``aivideo:cap:*:YYYYMMDD``)
with a 2-day TTL so they self-clean. Unlike the general request rate limiter
(which fails OPEN), these caps FAIL CLOSED: if Redis cannot confirm capacity we
refuse the render (503) rather than risk uncapped provider spend — Redis is
also the Celery broker here, so a down Redis means the job could not run anyway.

An over-cap attempt decrements its own increment back out so rejected requests
never consume capacity.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from loguru import logger

from app.models.exception import HttpException

_DEFAULT_GLOBAL_DAILY_CAP: int = 20
_DEFAULT_USER_DAILY_CAP: int = 2

_KEY_PREFIX: str = "reelforge:aivideo:cap"
# Keys expire two days after first use — long enough to cover the whole UTC
# day they meter plus clock skew, short enough to self-clean.
_KEY_TTL_S: int = 2 * 86400


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int((os.getenv(name) or "").strip() or default))
    except (TypeError, ValueError):
        return default


def global_daily_cap() -> int:
    return _int_env("AI_VIDEO_DAILY_CAP", _DEFAULT_GLOBAL_DAILY_CAP)


def user_daily_cap() -> int:
    return _int_env("AI_VIDEO_USER_DAILY_CAP", _DEFAULT_USER_DAILY_CAP)


def _utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _redis_client():
    """Reuse the rate limiter's lazily-built shared Redis client."""
    from app.services.ratelimit import _get_client

    return _get_client()


def _bump(client, key: str) -> int:
    """Atomically INCR ``key`` and ensure it carries a TTL; returns the count."""
    count = int(client.incr(key))
    if count == 1:
        client.expire(key, _KEY_TTL_S)
    return count


def enforce_ai_video_daily_caps(user_id: str, request_id: str) -> None:
    """Consume one AI-video capacity slot or raise; never spends over cap.

    Raises:
        HttpException(429): the per-user or global UTC-day cap is reached —
            the client sees a clean "at capacity today" message.
        HttpException(503): Redis cannot confirm capacity (fail-closed).
    """
    per_user = user_daily_cap()
    global_cap = global_daily_cap()
    day = _utc_day()
    user_key = f"{_KEY_PREFIX}:user:{user_id}:{day}"
    global_key = f"{_KEY_PREFIX}:global:{day}"

    client = _redis_client()
    if client is None:
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=(
                f"{request_id}: AI video generation is temporarily unavailable"
            ),
        )

    try:
        user_count = _bump(client, user_key)
        if user_count > per_user:
            client.decr(user_key)
            raise HttpException(
                task_id=request_id,
                status_code=429,
                message=(
                    f"{request_id}: you have reached today's AI video limit "
                    f"({per_user}/day) — try again tomorrow"
                ),
            )
        global_count = _bump(client, global_key)
        if global_count > global_cap:
            client.decr(global_key)
            client.decr(user_key)
            raise HttpException(
                task_id=request_id,
                status_code=429,
                message=(
                    f"{request_id}: AI video generation is at capacity today — "
                    "try again tomorrow"
                ),
            )
    except HttpException:
        raise
    except Exception as exc:  # noqa: BLE001 - spend protection fails CLOSED
        logger.error(
            f"ai video caps: redis error, refusing render, "
            f"request_id={request_id}: {exc}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: AI video generation is temporarily unavailable",
        )


def release_ai_video_slot(user_id: str) -> None:
    """Return one consumed capacity slot (best-effort, never raises).

    Called when a request that already passed the cap gate fails before any
    provider spend can happen (e.g. an insufficient-credits 402), so a blocked
    user does not burn the day's capacity.
    """
    try:
        client = _redis_client()
        if client is None:
            return
        day = _utc_day()
        client.decr(f"{_KEY_PREFIX}:user:{user_id}:{day}")
        client.decr(f"{_KEY_PREFIX}:global:{day}")
    except Exception as exc:  # noqa: BLE001 - release is best-effort
        logger.warning(f"ai video caps: slot release failed: {exc}")
