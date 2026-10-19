"""AI panel jobs (MV16, Wave P PM3.5) on the bulk lane (CPU tier 3, never ahead of paid renders). Never raises."""

from __future__ import annotations

import shutil
from typing import Any

from loguru import logger

from app.workers.celery_app import celery_app

AI_TASK = "app.domains.ott_ai.tasks.run_ai_task"


def run(title_id: str, source_language: str, deps: Any = None) -> dict[str, Any]:
    from app.domains.film.story8_render import ffmpeg_bin
    from app.domains.ott.feeds import api_base
    from app.domains.ott.models import OttTitle
    from app.models.db.base import get_session

    from . import pipeline

    with get_session() as session:
        title = session.get(OttTitle, title_id)
        if title is None:
            return {"skipped": True}
        chosen = deps or pipeline.Deps(store=pipeline.Store(), ffmpeg=ffmpeg_bin(),
                                       ffprobe=shutil.which("ffprobe") or "ffprobe", api_base=api_base())
        return pipeline.run(session, title, source_language, chosen)


@celery_app.task(name=AI_TASK, soft_time_limit=3 * 3600, time_limit=3 * 3600 + 60)
def run_ai_task(title_id: str, source_language: str) -> dict[str, Any]:
    try:
        return run(title_id, source_language)
    except Exception as exc:  # noqa: BLE001 - the rows keep their own failures
        logger.error(f"ott ai job {title_id} failed: {exc}")
        return {"failed": True}


__all__ = ["AI_TASK", "run", "run_ai_task"]
