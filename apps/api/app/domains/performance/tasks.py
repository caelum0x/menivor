"""Celery beat entrypoint: read every due post's numbers.

Beat-safe: never raises except a transient ``ConnectionError`` that Celery
retries. Every step is idempotent (discovery skips known posts, claimed posts
carry a lease), so an overlapping or duplicate tick is harmless.
"""

from __future__ import annotations

from loguru import logger

from app.workers.celery_app import celery_app

PERFORMANCE_TICK_SCHEDULE_S = 10 * 60.0
_EMPTY = {"discovered": 0, "read": 0, "ok": 0, "skipped": 0, "errors": 0}


@celery_app.task(
    bind=True,
    autoretry_for=(ConnectionError,),
    max_retries=3,
    retry_backoff=True,
    soft_time_limit=540,
    time_limit=570,
)
def performance_tick_task(self) -> dict[str, int]:
    """Discover new publishes and refresh due posts once. Never raises (beat-safe)."""
    try:
        from app.domains.performance.tracker import tick

        summary = tick()
        if summary.get("read") or summary.get("discovered"):
            logger.info(f"performance tick: {summary}")
        return summary
    except ConnectionError:
        raise
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash the worker
        logger.error(f"performance_tick_task failed: {exc}")
        return dict(_EMPTY)


__all__ = ["PERFORMANCE_TICK_SCHEDULE_S", "performance_tick_task"]
