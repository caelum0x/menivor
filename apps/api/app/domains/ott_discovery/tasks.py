"""Discovery index (MV19, Wave P PM3.5): every 15 minutes embed titles whose text changed (CPU tier 3)."""

from __future__ import annotations

from loguru import logger

from app.workers.celery_app import celery_app

INDEX_TASK = "app.domains.ott_discovery.tasks.reindex_task"
BEAT_SCHEDULE: dict[str, dict] = {"menivor-ott-discovery-index": {"task": INDEX_TASK, "schedule": 15 * 60.0}}


def run() -> int:
    from app.domains.ott import flags
    from app.models.db.base import get_session

    from . import search

    if not flags.enabled("discovery"):
        return 0
    with get_session() as session:
        return search.reindex(session)


@celery_app.task(name=INDEX_TASK)
def reindex_task() -> int:
    try:
        return run()
    except Exception as exc:  # noqa: BLE001 - a beat tick never crashes the worker
        logger.error(f"ott discovery index failed: {exc}")
        return 0


__all__ = ["BEAT_SCHEDULE", "INDEX_TASK", "reindex_task", "run"]
