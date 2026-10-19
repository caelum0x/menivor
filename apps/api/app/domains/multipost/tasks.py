"""Beat tasks for multi-account publishing (each tick is an idempotent "whatever is due" pass)."""

from __future__ import annotations

from loguru import logger

from app.workers.celery_app import celery_app

DUE_TASK = "app.domains.multipost.tasks.run_due_task"
SWEEP_TASK = "app.domains.multipost.tasks.sweep_processing_task"
STALE_TASK = "app.domains.multipost.tasks.sweep_stale_task"
REFRESH_TASK = "app.domains.multipost.tasks.refresh_tokens_task"

BEAT_SCHEDULE: dict[str, dict] = {
    "menivor-multipost-run-due": {"task": DUE_TASK, "schedule": 60.0},
    "menivor-multipost-sweep-processing": {"task": SWEEP_TASK, "schedule": 60.0},
    "menivor-multipost-sweep-stale": {"task": STALE_TASK, "schedule": 10 * 60.0},
    "menivor-multipost-refresh-tokens": {"task": REFRESH_TASK, "schedule": 15 * 60.0},
}


def _safe(name: str, fn):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - a beat tick never crashes the worker
        logger.error(f"multipost {name} failed: {exc}")
        return None


@celery_app.task(name=DUE_TASK)
def run_due_task():
    from . import runner

    return _safe("run_due", runner.run_due)


@celery_app.task(name=SWEEP_TASK)
def sweep_processing_task():
    from . import runner

    return _safe("sweep_processing", runner.sweep_processing)


@celery_app.task(name=STALE_TASK)
def sweep_stale_task():
    from . import runner

    return _safe("sweep_stale", runner.sweep_stale)


@celery_app.task(name=REFRESH_TASK)
def refresh_tokens_task():
    from . import runner

    return _safe("refresh_tokens", runner.refresh_tokens)


__all__ = ["BEAT_SCHEDULE", "refresh_tokens_task", "run_due_task", "sweep_processing_task", "sweep_stale_task"]
