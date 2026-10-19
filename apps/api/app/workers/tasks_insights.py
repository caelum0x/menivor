"""Celery beat entrypoint for the remake-winner loop.

:func:`winner_loop_tick_task` advances every active loop once per tick
(``app.domains.insights.winner_loop_service.tick``): it queues newly rendered
variants for spaced auto-publishing, and once a project's check window (48h by
default) has passed since its last variant went live it pulls the real platform
metrics, ranks the variants, records the winner with a plain-language
explanation and — in ``auto`` mode, within the spend cap — remakes it.

Beat-safety contract (mirrors ``tasks_series``): the task NEVER raises out of
its body except for a transient ``ConnectionError`` that Celery auto-retries;
any other failure degrades to a logged zeroed summary. Every step is idempotent
(already-queued posts are skipped, settled projects are not re-measured, a
remade project returns its existing remake), so a duplicate tick is safe.

Wiring (celery_app.py): add ``"app.workers.tasks_insights"`` to ``include`` and
a beat entry ``{"task": "app.workers.tasks_insights.winner_loop_tick_task",
"schedule": 15 * 60.0}`` routed to the ``render`` queue (DB + HTTP only).
"""

from __future__ import annotations

from loguru import logger

from app.workers.celery_app import celery_app

WINNER_LOOP_TICK_SCHEDULE_S = 15 * 60.0

_EMPTY_SUMMARY: dict[str, int] = {"loops": 0, "advanced": 0, "winners": 0, "remade": 0, "errors": 0}


def _tick_impl() -> dict[str, int]:
    from app.domains.insights.winner_loop_service import tick

    return tick()


@celery_app.task(
    bind=True,
    autoretry_for=(ConnectionError,),
    max_retries=3,
    retry_backoff=True,
    soft_time_limit=840,
    time_limit=870,
)
def winner_loop_tick_task(self) -> dict[str, int]:
    """Advance every active remake-winner loop once. Never raises (beat-safe)."""
    try:
        summary = _tick_impl()
        if summary.get("loops"):
            logger.info(f"winner loop tick: {summary}")
        return summary
    except ConnectionError:  # transient broker/DB — let Celery autoretry
        raise
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash the worker
        logger.error(f"winner_loop_tick_task failed: {exc}")
        return dict(_EMPTY_SUMMARY)


__all__ = ["WINNER_LOOP_TICK_SCHEDULE_S", "winner_loop_tick_task"]
