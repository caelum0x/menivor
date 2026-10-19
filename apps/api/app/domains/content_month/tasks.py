"""Celery task: build a Content Month carousel's slideshow MP4 on the render worker."""

from __future__ import annotations

from app.workers.celery_app import celery_app


@celery_app.task(name="app.domains.content_month.tasks.render_month_video_task", time_limit=900,
                 soft_time_limit=840)
def render_month_video_task(user_id: str, idea_id: str) -> str:
    from app.domains.content_month.video import build_video

    return build_video(user_id, idea_id)
