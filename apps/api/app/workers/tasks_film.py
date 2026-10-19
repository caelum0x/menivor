"""Celery task for the film final export (stitch shots -> one MP4).

Routed to the ``render`` queue (FFmpeg work, alongside the reel compose stage) in
``celery_app.py``. The body delegates to
:func:`app.domains.film.export.run_film_export`, which never raises: every failure
is recorded on the project (``export_state='failed'`` + reason) so the web/mobile
film page can surface it and offer a retry.
"""

from __future__ import annotations

from loguru import logger

from app.workers.celery_app import celery_app


@celery_app.task(bind=True, soft_time_limit=1500, time_limit=1560)
def export_film_task(self, project_id: str) -> dict:
    """Stitch every rendered shot of ``project_id`` into its final export."""
    try:
        from app.domains.film.export import run_film_export

        return run_film_export(str(project_id or ""))
    except Exception as exc:  # noqa: BLE001 - the export records its own failure
        logger.error(f"export_film_task crashed for {project_id}: {exc}")
        return {"ok": False, "error": "export crashed"}
