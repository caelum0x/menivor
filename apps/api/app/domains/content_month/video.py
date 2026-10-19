"""Slideshow MP4 for a made carousel, built on the render worker (FFmpeg is slow on a busy box).

``render_carousel`` stores the PNG slides and the PDF, sets
``outputs.video_status = "queued"`` and calls :func:`enqueue`. The Celery task
(:mod:`.tasks`, ``render`` queue) runs :func:`build_video`: download the slides
from R2, encode, upload the MP4 as an owned video asset, and set
``video_status`` to ``done`` (or ``failed`` with a reason the UI shows next to
a retry button). If the queue cannot be reached the status is ``failed`` at
once, never stuck.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from loguru import logger

QUEUED = "queued"
RENDERING = "rendering"
DONE = "done"
FAILED = "failed"
#: A video still "queued"/"rendering" after this long is shown as failed (worker restarted mid-job).
STALE_AFTER = timedelta(minutes=20)


def _default_enqueue(user_id: str, idea_id: str) -> None:
    from app.domains.content_month.tasks import render_month_video_task

    render_month_video_task.delay(user_id, idea_id)


def _set(user_id: str, idea_id: str, **fields: object) -> None:
    from app.domains.content_month import service

    with service.get_session() as session:  # type: ignore[misc]
        idea = service._idea(session, user_id, idea_id)
        idea.outputs = {**(idea.outputs or {}), **fields}
        session.flush()


def enqueue(user_id: str, idea_id: str, *, run: Callable[[str, str], None] | None = None) -> None:
    try:
        (run or _default_enqueue)(user_id, idea_id)
    except Exception as exc:  # noqa: BLE001 - broker down: say so instead of spinning forever
        logger.error(f"content month: could not queue the video for {idea_id}: {exc}")
        _set(user_id, idea_id, video_status=FAILED, video_error="the video queue is busy; try again")


def build_video(user_id: str, idea_id: str, *, to_mp4: Callable[..., bytes] | None = None,
                download: Callable[[str], bytes] | None = None) -> str:
    """Encode and store the MP4 for one carousel. Returns the final ``video_status``."""
    from app.domains.content_month import raster, service, slides
    from app.domains.design import service as design_service

    with service.get_session() as session:  # type: ignore[misc]
        idea = service._idea(session, user_id, idea_id)
        outputs = dict(idea.outputs or {})
    keys = list(outputs.get("png_keys") or [])
    if not keys:
        _set(user_id, idea_id, video_status=FAILED, video_error="make the slides first")
        return FAILED
    _set(user_id, idea_id, video_status=RENDERING, video_started_at=datetime.now(timezone.utc).isoformat())
    _, width, height = slides.SIZES.get(outputs.get("size") or slides.DEFAULT_SIZE, slides.SIZES[slides.DEFAULT_SIZE])
    stem = outputs.get("stem") or f"uploads/month-{idea_id}"
    try:
        pngs = [(download or design_service._download)(k) for k in keys]
        mp4 = (to_mp4 or raster.to_mp4)(pngs, width, height)
        with service.get_session() as session:  # type: ignore[misc]
            service._store(session, user_id, f"{stem}.mp4", mp4, "video/mp4",
                           {"source": "content_month", "idea_id": idea_id, "filename": "carousel.mp4",
                            "design_id": outputs.get("design_id", "")})
    except Exception as exc:  # noqa: BLE001 - the slides and PDF stay usable
        logger.error(f"content month: video failed for {idea_id}: {exc}")
        _set(user_id, idea_id, video_status=FAILED, video_error="the video could not be made; try again")
        return FAILED
    _set(user_id, idea_id, video_status=DONE, mp4_key=f"{stem}.mp4", video_error="")
    logger.info(f"content month: video ready for {idea_id} ({len(mp4)} bytes)")
    return DONE


def effective_status(outputs: dict, now: datetime | None = None) -> str:
    """``video_status`` with stale queued/rendering jobs shown as failed."""
    status = str(outputs.get("video_status") or "")
    if status not in (QUEUED, RENDERING):
        return status
    started = outputs.get("video_started_at")
    if status == RENDERING and started:
        try:
            when = datetime.fromisoformat(str(started))
        except ValueError:
            return status
        if (now or datetime.now(timezone.utc)) - when > STALE_AFTER:
            return FAILED
    return status


__all__ = ["DONE", "FAILED", "QUEUED", "RENDERING", "build_video", "effective_status", "enqueue"]
