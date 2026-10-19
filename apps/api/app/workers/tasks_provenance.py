"""Compose stage that marks the final MP4 as AI-generated before delivery (MN5).

This is the chord callback :mod:`app.workers.pipeline` uses in place of
``app.workers.tasks.stage_compose_task``. It runs the same compose
(:func:`app.services.reelforge.stage_compose`) through the same stage runner and
failure/refund machinery (``StageTask``), then writes the provenance tag into
the final MP4 (:func:`app.services.provenance.tag_final`) and replaces the
stored copy. Because tagging happens inside the stage, the job is marked
complete (and handed to autopublish) only once the file carries the tag; a
tagging failure fails the stage and follows the normal refund path.

The task keeps the leaf name ``stage_compose_task`` so the stage name derived by
``StageTask`` stays ``compose``. The original task stays registered and
routable (nothing is removed).
"""

from __future__ import annotations

from typing import Any

from app.workers.celery_app import celery_app
from app.workers.context import merge_partials
from app.workers.tasks import StageTask, _run_stage

COMPOSE_TASK_NAME = "app.workers.tasks_provenance.stage_compose_task"


def compose_with_provenance(job_id: str, params: Any, ctx: dict) -> dict:
    """Compose the reel, then tag and re-store the final MP4."""
    from app.services import provenance
    from app.services.reelforge import stage_compose

    result = stage_compose(job_id, params, ctx)
    return provenance.tag_final(job_id, dict(result or {}))


@celery_app.task(
    name=COMPOSE_TASK_NAME,
    base=StageTask,
    bind=True,
    soft_time_limit=600,
    time_limit=660,
)
def stage_compose_task(self, results: list[dict]) -> dict:
    """Chord callback: merge avatar + captions partials, compose, then tag."""
    return _run_stage(merge_partials(results), "compose", compose_with_provenance)


__all__ = ["COMPOSE_TASK_NAME", "compose_with_provenance", "stage_compose_task"]
