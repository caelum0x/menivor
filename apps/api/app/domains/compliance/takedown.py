"""Content reports and takedown (MN5).

Anyone can report a Menivor video from ``/legal/report`` (no account needed).
A report:

1. creates a ticket (a ``takedown_reports`` row) and returns its id,
2. alerts the owner on ntfy right away (``MENIVOR_OWNER_NTFY_URL``; email too
   when ``MENIVOR_OWNER_ALERT_EMAIL`` is set),
3. can soft-block the reported video's media: staff block it with one call,
   and a report still open after :data:`AUTO_BLOCK_HOURS` hours is blocked
   automatically by the beat sweep, so no report waits longer than 24 h.

A soft block hides the media (no result/preview URLs, public share page gone)
without deleting anything; staff can restore it. The reported video is found
from what the reporter pastes: a job id, a link containing one, or a public
share link (``/r/<token>``).
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import DateTime, Index, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.db.base import Base

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
STATUS_OPEN = "open"
STATUS_BLOCKED = "blocked"
STATUS_DISMISSED = "dismissed"
STATUS_RESTORED = "restored"

#: Reasons a reporter can pick (the web form mirrors these).
REASONS: tuple[str, ...] = (
    "impersonation",
    "copyright",
    "privacy",
    "harmful",
    "sexual",
    "other",
)
#: An open report older than this is soft-blocked by the sweep.
AUTO_BLOCK_HOURS = 24
MAX_DETAILS = 4000
MAX_CONTENT_REF = 1000
AUTO_BLOCK_ACTOR = "auto:24h"
BLOCKED_MESSAGE = "This video is paused while we review a report about it."

_JOB_ID = re.compile(r"\b([0-9a-f]{32})\b")
_SHARE = re.compile(r"/r/([A-Za-z0-9_\-]{8,})")
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")


class TakedownError(ValueError):
    """A report could not be accepted (bad input)."""


class TakedownReport(Base):
    """One content report (a ticket). Never deleted; status records the outcome."""

    __tablename__ = "takedown_reports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    job_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    content_ref: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reporter_email: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_OPEN)
    resolved_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_takedown_reports_status_created", "status", "created_at"),)


# --------------------------------------------------------------------------- #
# Resolving what was reported
# --------------------------------------------------------------------------- #
def resolve_job_id(session: Session, content_ref: str) -> str | None:
    """The job a pasted id or link points at, or ``None`` when unknown."""
    from app.models.db.models import Job, ShareLink

    text = (content_ref or "").strip()
    share = _SHARE.search(text)
    if share:
        link = session.execute(
            select(ShareLink).where(ShareLink.token == share.group(1)).limit(1)
        ).scalars().first()
        if link is not None:
            return str(link.job_id)
    for candidate in _JOB_ID.findall(text.lower()):
        if session.get(Job, candidate) is not None:
            return candidate
    # Wave P PM2 verify: an uploaded OTT title has no job; its title id is the media id.
    for candidate in _JOB_ID.findall(text.lower()):
        if _is_ott_title(session, candidate):
            return candidate
    return None


def _is_ott_title(session: Session, candidate: str) -> bool:
    try:
        from app.domains.ott.models import OttTitle

        return session.get(OttTitle, candidate) is not None
    except Exception as exc:  # noqa: BLE001 - an OTT lookup never breaks a report
        logger.warning(f"takedown: OTT title lookup failed: {type(exc).__name__}")
        return False


# --------------------------------------------------------------------------- #
# Alerts
# --------------------------------------------------------------------------- #
def _alert_owner(report: TakedownReport, *, headline: str) -> bool:
    """ntfy (and email when configured). Best effort; returns True if ntfy sent."""
    text = (
        f"{headline}\nticket {report.id}\nreason {report.reason}\n"
        f"job {report.job_id or 'not found'}\nreported {report.content_ref[:200]}"
    )
    sent = False
    topic = (os.environ.get("MENIVOR_OWNER_NTFY_URL") or "").strip()
    if topic:
        try:
            import requests

            resp = requests.post(
                topic, data=text.encode("utf-8"), timeout=5,
                headers={"Title": "Menivor content report", "Priority": "high", "Tags": "warning"},
            )
            sent = 200 <= int(getattr(resp, "status_code", 0) or 0) < 300
        except Exception as exc:  # noqa: BLE001 - alerting is best effort
            logger.warning(f"takedown ntfy alert failed: {type(exc).__name__}")
    else:
        logger.warning("takedown alert: MENIVOR_OWNER_NTFY_URL is not set")
    to = (os.environ.get("MENIVOR_OWNER_ALERT_EMAIL") or "").strip()
    if to:
        try:
            from app.services import mailer

            mailer.send_email(to=to, subject="Menivor content report", text=text)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"takedown email alert failed: {type(exc).__name__}")
    logger.warning(f"content report {report.id}: {headline}")
    return sent


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
def _clean(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def create_report(
    session: Session, *, content_ref: str, reason: str, details: str, reporter_email: str
) -> TakedownReport:
    """Validate and store a report, then alert the owner. Returns the ticket."""
    ref = _clean(content_ref, MAX_CONTENT_REF)
    why = _clean(reason, 40).lower()
    email = _clean(reporter_email, 320)
    if not ref:
        raise TakedownError("Paste the link or id of the video you are reporting.")
    if why not in REASONS:
        raise TakedownError("Pick a reason for the report.")
    if not _EMAIL.match(email):
        raise TakedownError("Enter an email address so we can reply.")
    report = TakedownReport(
        job_id=resolve_job_id(session, ref),
        content_ref=ref,
        reason=why,
        details=_clean(details, MAX_DETAILS),
        reporter_email=email,
        status=STATUS_OPEN,
    )
    session.add(report)
    session.flush()
    session.commit()
    _alert_owner(report, headline="New content report")
    return report


def _set_status(session: Session, report_id: str, status: str, actor: str) -> TakedownReport | None:
    report = session.get(TakedownReport, report_id)
    if report is None:
        return None
    now = datetime.now(timezone.utc)
    report.status = status
    report.resolved_by = _clean(actor, 64)
    report.resolved_at = now
    if status == STATUS_BLOCKED:
        report.blocked_at = now
    session.flush()
    return report


def block(session: Session, report_id: str, actor: str) -> TakedownReport | None:
    """Soft-block the reported video's media (reversible)."""
    report = _set_status(session, report_id, STATUS_BLOCKED, actor)
    if report is not None:
        logger.warning(f"takedown {report.id}: media of job {report.job_id} blocked by {actor}")
        from app.domains.gallery.service import on_media_blocked  # Wave P PM1.3: hide the gallery item now

        on_media_blocked(session, report.job_id)
        from app.domains.ott.service import on_media_blocked as hide_ott_titles  # Wave P PM2.3: hide OTT titles now

        hide_ott_titles(session, report.job_id)
    return report


def dismiss(session: Session, report_id: str, actor: str) -> TakedownReport | None:
    """Close a report with no action."""
    return _set_status(session, report_id, STATUS_DISMISSED, actor)


def restore(session: Session, report_id: str, actor: str) -> TakedownReport | None:
    """Lift a soft block after review."""
    return _set_status(session, report_id, STATUS_RESTORED, actor)


def list_reports(session: Session, *, status: str = "", limit: int = 100) -> list[TakedownReport]:
    stmt = select(TakedownReport).order_by(TakedownReport.created_at.desc()).limit(max(1, min(limit, 500)))
    if status:
        stmt = stmt.where(TakedownReport.status == status)
    return list(session.execute(stmt).scalars().all())


def auto_block_overdue(session: Session, *, now: datetime | None = None) -> int:
    """Soft-block every report still open after 24 h that names a video."""
    at = now or datetime.now(timezone.utc)
    cutoff = at - timedelta(hours=AUTO_BLOCK_HOURS)
    if session.get_bind().dialect.name == "sqlite":
        cutoff = cutoff.replace(tzinfo=None)
    overdue = session.execute(
        select(TakedownReport).where(
            TakedownReport.status == STATUS_OPEN,
            TakedownReport.job_id.is_not(None),
            TakedownReport.created_at <= cutoff,
        )
    ).scalars().all()
    for report in overdue:
        block(session, report.id, AUTO_BLOCK_ACTOR)
        _alert_owner(report, headline="Report open for 24 h: media soft-blocked, please review")
    return len(overdue)


# --------------------------------------------------------------------------- #
# The check every media path makes
# --------------------------------------------------------------------------- #
def is_blocked_in_session(session: Session, job_id: str) -> bool:
    if not job_id:
        return False
    found = session.execute(
        select(TakedownReport.id)
        .where(TakedownReport.job_id == str(job_id), TakedownReport.status == STATUS_BLOCKED)
        .limit(1)
    ).scalar()
    return found is not None


def is_blocked(job_id: str) -> bool:
    """True when the job's media is soft-blocked. A lookup error never blocks."""
    if not job_id:
        return False
    try:
        from app.models.db.base import get_session

        with get_session() as session:
            return is_blocked_in_session(session, job_id)
    except Exception as exc:  # noqa: BLE001 - serving stays up if the check fails
        logger.warning(f"takedown check failed for job {job_id}: {type(exc).__name__}")
        return False


def report_view(report: TakedownReport) -> dict[str, Any]:
    """Staff view of a ticket."""
    def iso(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    return {
        "id": report.id,
        "job_id": report.job_id,
        "content_ref": report.content_ref,
        "reason": report.reason,
        "details": report.details,
        "reporter_email": report.reporter_email,
        "status": report.status,
        "resolved_by": report.resolved_by,
        "created_at": iso(report.created_at),
        "blocked_at": iso(report.blocked_at),
        "resolved_at": iso(report.resolved_at),
    }


__all__ = [
    "AUTO_BLOCK_HOURS",
    "BLOCKED_MESSAGE",
    "REASONS",
    "TakedownError",
    "TakedownReport",
    "auto_block_overdue",
    "block",
    "create_report",
    "dismiss",
    "is_blocked",
    "is_blocked_in_session",
    "list_reports",
    "report_view",
    "resolve_job_id",
    "restore",
]
