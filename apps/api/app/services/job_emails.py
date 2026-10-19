"""Transactional emails about a creator's reels (best-effort, deduplicated).

* :func:`send_reels_ready_email` - the first finished reel of a run (a batch
  shares ``Job.batch_id``); one email per run, never one per variant.
* :func:`send_reel_stopped_email` - a reel stopped making progress, the reaper
  stopped it and returned the credit (one email per job).

Every sender resolves the owner's address itself, links to the owner-scoped
results page, and never raises: a failed email must never touch a render or a
refund. Dedupe markers live in the job's ``stages`` map (underscore keys are
never pipeline stages), written under a row lock so two workers racing on the
same event send one email.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import quote

from loguru import logger

STOPPED_EMAIL_MARKER = "_stopped_email"
READY_EMAIL_MARKER = "_ready_email"
REEL_KIND = "avatar_reel"
RESULTS_PATH = "/create/results"
_MAX_RESULTS_IDS = 3


def emails_enabled() -> bool:
    """``MENIVOR_JOB_EMAILS=0`` turns every reel email off (default on)."""
    return str(os.getenv("MENIVOR_JOB_EMAILS", "1")).strip().lower() not in {"0", "false", "off", "no"}


def web_base_url() -> str:
    try:
        from app.services.billing import card_check

        return card_check.web_base_url()
    except Exception:  # noqa: BLE001 - config import failure -> public site
        return "https://menivor.com"


def results_url(job_ids: Iterable[str]) -> str:
    """The owner-scoped results page for up to three jobs."""
    ids = [str(job_id) for job_id in job_ids if job_id][:_MAX_RESULTS_IDS]
    return f"{web_base_url()}{RESULTS_PATH}?jobs={','.join(quote(i, safe='') for i in ids)}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _locked(session: Any, model: Any, ids: list[str]) -> list[Any]:
    """Rows locked FOR UPDATE in id order (deadlock-free), SQLite-tolerant."""
    from sqlalchemy import select
    from sqlalchemy.exc import NotSupportedError

    stmt = select(model).where(model.id.in_(ids)).order_by(model.id)
    try:
        return list(session.execute(stmt.with_for_update()).scalars().all())
    except NotSupportedError:
        if session.get_bind().dialect.name != "sqlite":
            raise
        return list(session.execute(stmt).scalars().all())


def claim_marker(session: Any, job_ids: list[str], marker: str, owner_id: str) -> bool:
    """Set ``marker`` on ``owner_id`` unless any of ``job_ids`` already has it.

    Locks every row of the group first, so exactly one caller wins per group.
    """
    from app.models.db.models import Job

    rows = _locked(session, Job, sorted(set(job_ids) | {owner_id}))
    if any(marker in (row.stages or {}) for row in rows):
        return False
    for row in rows:
        if row.id == owner_id:
            row.stages = {**(row.stages or {}), marker: _now_iso()}
    session.flush()
    return True


def _address(session: Any, user_id: str) -> str:
    from app.models.db.models import User

    from app.services.funnel.internal import is_internal_email

    user = session.get(User, user_id)
    email = str(getattr(user, "email", "") or "").strip()
    # Internal accounts (smoke test, Megaphone renderer) get no reel mail.
    return email if "@" in email and not is_internal_email(email) else ""


def _deliver(to: str, rendered: Any) -> bool:
    from app.services import mailer

    return mailer.send_email(to=to, subject=rendered.subject, text=rendered.text, html=rendered.html)


def _reel_title(job: Any) -> str:
    params = job.params if isinstance(job.params, dict) else {}
    for value in (job.title, params.get("video_subject"), getattr(job, "hook", "")):
        text = " ".join(str(value or "").split())
        if text:
            return text[:80]
    return "Your reel"


def send_reels_ready_email(job_id: str) -> bool:
    """Email the owner when the first reel of a run is ready (once per run)."""
    if not job_id or not emails_enabled():
        return False
    try:
        from app.models import const
        from app.models.db.base import get_session
        from app.models.db.models import Job
        from app.services.email_templates import video_ready_email

        with get_session() as session:
            job = session.get(Job, job_id)
            if job is None or job.state != const.TASK_STATE_COMPLETE:
                return False
            if str(job.kind or REEL_KIND) != REEL_KIND:
                return False
            to = _address(session, str(job.user_id))
            if not to:
                return False
            group = [job_id]
            if job.batch_id:
                group = [
                    str(row.id)
                    for row in session.query(Job)
                    .filter(Job.batch_id == job.batch_id, Job.user_id == job.user_id)
                    .order_by(Job.created_at, Job.id)
                ]
            if not claim_marker(session, group, READY_EMAIL_MARKER, job_id):
                return False
            rendered = video_ready_email(
                title=_reel_title(job), url=results_url(group), batch_size=len(group)
            )
        return _deliver(to, rendered)
    except Exception as exc:  # noqa: BLE001 - an email must never break the caller
        logger.warning(f"reels ready email for job {job_id} failed: {type(exc).__name__}: {exc}")
        return False


def send_reel_stopped_email(job_id: str) -> bool:
    """Tell the owner a stalled reel was stopped and refunded (once per job)."""
    if not job_id or not emails_enabled():
        return False
    try:
        from app.models.db.base import get_session
        from app.models.db.models import Job
        from app.services.email_templates import reel_stopped_email

        with get_session() as session:
            job = session.get(Job, job_id)
            if job is None:
                return False
            to = _address(session, str(job.user_id))
            if not to or not claim_marker(session, [job_id], STOPPED_EMAIL_MARKER, job_id):
                return False
            ids = [job_id]
            if job.batch_id:
                ids = [
                    row.id
                    for row in session.query(Job).filter(Job.batch_id == job.batch_id).order_by(Job.created_at)
                ]
            rendered = reel_stopped_email(url=results_url(ids))
        return _deliver(to, rendered)
    except Exception as exc:  # noqa: BLE001 - an email must never break the caller
        logger.warning(f"reel stopped email for job {job_id} failed: {type(exc).__name__}: {exc}")
        return False


__all__ = [
    "READY_EMAIL_MARKER",
    "STOPPED_EMAIL_MARKER",
    "claim_marker",
    "emails_enabled",
    "results_url",
    "send_reel_stopped_email",
    "send_reels_ready_email",
]
