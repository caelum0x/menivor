"""Where a queued post's video comes from, and the pre-publish content gate.

:class:`JobMedia` is the production source: it reads the owner's ``Job`` row
(BOLA-guarded), refuses takedown-blocked videos, presigns the rendered MP4 for
URL-ingest platforms and downloads it for byte uploads. Tests inject their own
source object with the same three methods.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

from loguru import logger

READY = "ready"
RENDERING = "rendering"
FAILED = "failed"
MISSING = "missing"
BLOCKED = "blocked"


class MediaSource(Protocol):
    def state(self, user_id: str, job_id: str) -> str: ...

    def video_url(self, user_id: str, job_id: str) -> str: ...

    def download(self, user_id: str, job_id: str) -> str: ...


class JobMedia:
    """Rendered videos from the job pipeline (R2)."""

    def _job(self, session: Any, user_id: str, job_id: str):
        from app.models.db.models import Job

        job = session.get(Job, job_id)
        if job is None or str(getattr(job, "user_id", "")) != str(user_id):
            return None
        return job

    def state(self, user_id: str, job_id: str) -> str:
        from app.models import const
        from app.models.db.base import get_session

        with get_session() as session:
            job = self._job(session, user_id, job_id)
            if job is None:
                return MISSING
            if job.state == const.TASK_STATE_FAILED:
                return FAILED
            if job.state != const.TASK_STATE_COMPLETE:
                return RENDERING
        try:
            from app.domains.compliance.takedown import is_blocked

            if is_blocked(str(job_id)):
                return BLOCKED
        except Exception as exc:  # noqa: BLE001 - fail closed on the takedown check
            logger.warning(f"takedown check failed for {job_id}: {exc}")
            return BLOCKED
        return READY

    def _key(self, user_id: str, job_id: str) -> str:
        from app.domains.publishing.native_service import _resolve_final_key

        key, _context, _watermark_source = _resolve_final_key(user_id, job_id)
        return key

    def video_url(self, user_id: str, job_id: str) -> str:
        from app.platform.storage.r2 import get_r2_client

        return get_r2_client().presign_get(self._key(user_id, job_id))

    def download(self, user_id: str, job_id: str) -> str:
        from app.domains.publishing.native_service import _download_temp

        return _download_temp(self._key(user_id, job_id), job_id)


def cleanup(path: str) -> None:
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:  # pragma: no cover - best-effort temp cleanup
            pass


def content_gate(provider: str, title: str, caption: str) -> tuple[bool, str]:
    """Run the shared pre-publish quality/safety gate. ``(can_publish, reason)``.

    Degrades to "publish with review" when the decision backend is unavailable
    (the gate's own contract), so an outage never silently blocks a queue.
    """
    try:
        from app.domains.publishing.content_gate import GateContext, evaluate_content_sync
    except Exception as exc:  # noqa: BLE001 - gate module missing: let the post through
        logger.warning(f"content gate unavailable: {exc}")
        return True, ""
    hook = (title or "").strip() or next((ln.strip() for ln in (caption or "").splitlines() if ln.strip()), "")
    gate = evaluate_content_sync(caption or "", hook, GateContext(platform=provider))
    if gate.can_publish:
        return True, ""
    reasons = "; ".join(f"{k}: {v}" for k, v in gate.reasons.items()) or gate.decision
    return False, f"held for review ({gate.decision}): {reasons}"
