"""Celery worker for approved studio renders (actor shots, lip-sync translations)."""

from __future__ import annotations

from app.workers.celery_app import celery_app

TASK_NAME = "app.domains.studio_render.tasks.run_studio_render_task"
RECONCILE_TASK = "app.domains.studio_render.tasks.studio_render_reconcile_tick"
BEAT_SCHEDULE = {"studio-render-reconcile": {"task": RECONCILE_TASK, "schedule": 600.0}}


@celery_app.task(name=TASK_NAME)
def run_studio_render_task(render_id: str) -> dict:
    from app.domains.studio_render import runners, service

    runners.register_defaults()
    return service.run(render_id)


@celery_app.task(name=RECONCILE_TASK)
def studio_render_reconcile_tick() -> dict:
    from app.domains.studio_render import service

    return service.reconcile()


__all__ = ["BEAT_SCHEDULE", "RECONCILE_TASK", "TASK_NAME", "run_studio_render_task", "studio_render_reconcile_tick"]
