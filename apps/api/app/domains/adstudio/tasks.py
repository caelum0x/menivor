"""Optional Celery task for Ad Studio renders (``render`` queue).

Used only when ``[app] adstudio_render_executor = "celery"``; the worker must
list ``app.domains.adstudio.tasks`` in its ``include``. The body delegates to
:func:`app.domains.adstudio.worker.run_variant_render`, which records every
failure on the variant itself.
"""

from __future__ import annotations

from loguru import logger

from app.workers.celery_app import celery_app


@celery_app.task(name="app.domains.adstudio.tasks.render_ad_variant_task", soft_time_limit=1500, time_limit=1560)
def render_ad_variant_task(variant_id: str) -> dict:
    try:
        from app.domains.adstudio.worker import run_variant_render

        return run_variant_render(str(variant_id or ""))
    except Exception as exc:  # noqa: BLE001 - the render records its own failure
        logger.error(f"render_ad_variant_task crashed for {variant_id}: {exc}")
        return {"ok": False, "error": "render crashed"}
