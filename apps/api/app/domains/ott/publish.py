"""One-click publish (MV1): a creator's finished reels become a live channel in one press.

Picks the creator's newest finished, kept, unblocked renders (up to ``limit``),
creates the channel if needed, adds each as a title, runs the compliance gate
and publishes every title that passes. The elapsed time is measured and
returned, so the "5 reels to a channel in under 60 s" target is shown per run.
Titles that fail the gate stay drafts and are listed with the reason.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import service
from .models import STATUS_PUBLISHED

TARGET_SECONDS = 60.0


def finished_reels(session: Session, user_id: str, limit: int) -> list[Any]:
    from app.domains.reels import keep
    from app.models.db.models import Job

    rows = session.execute(
        select(Job).where(Job.user_id == user_id, Job.state == service.TASK_STATE_COMPLETE, Job.result_key != "",
                          Job.deleted_at.is_(None)).order_by(Job.created_at.desc()).limit(limit * 3)
    ).scalars().all()
    return [job for job in rows if not keep.is_pending(dict(job.params or {}))][:limit]


def publish_all(session: Session, user_id: str, *, limit: int = 12, clock=time.monotonic) -> dict[str, Any]:
    started = clock()
    channel = service.ensure_channel(session, user_id)
    published, held = [], []
    for job in finished_reels(session, user_id, limit):
        title = service.add_title(session, user_id, job.id)
        if title.status == STATUS_PUBLISHED:
            published.append(title.id)
            continue
        reason = service.gate(session, title)
        if reason:
            held.append({"title_id": title.id, "reason": reason})
            continue
        service.publish_title(session, user_id, title.id)
        published.append(title.id)
    session.flush()
    seconds = round(clock() - started, 3)
    return {"channel": service.channel_view(session, channel), "published": published, "held": held,
            "seconds": seconds, "target_seconds": TARGET_SECONDS, "within_target": seconds <= TARGET_SECONDS}


__all__ = ["TARGET_SECONDS", "finished_reels", "publish_all"]
