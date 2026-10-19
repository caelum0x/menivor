"""Optional Celery task for captures (``render`` queue).

Used only when ``[app] capture_executor = "celery"``; the worker lists
``app.domains.capture.tasks`` in its ``include``. The body delegates to
:func:`app.domains.capture.worker.run_capture`, which records every failure on
the capture job itself. Website/game captures need Playwright + Chromium on the
worker host (see ``browser.py``).
"""

from __future__ import annotations

from loguru import logger

from app.workers.celery_app import celery_app


@celery_app.task(name="app.domains.capture.tasks.run_capture_task", soft_time_limit=1200, time_limit=1260)
def run_capture_task(capture_id: str) -> dict:
    try:
        from app.domains.capture.worker import run_capture

        return run_capture(str(capture_id or ""))
    except Exception as exc:  # noqa: BLE001 - the capture records its own failure
        logger.error(f"run_capture_task crashed for {capture_id}: {exc}")
        return {"ok": False, "error": "capture crashed"}
