"""Scheduled Publishing service for ReelForge.

A creator schedules an *already-rendered, complete* job to auto-publish to
social platforms (tiktok | instagram | youtube_shorts, via the creator's native
OAuth connections) at a future UTC time. A
background due-runner (Celery beat, wired every minute) calls
:func:`process_due_publishes`, which claims due ``pending`` schedules, publishes
each, and marks them ``published`` / ``failed``. Owners can list and cancel
their still-``pending`` schedules.

Design notes
------------
* **Real time vs. determinism.** Production uses ``datetime.now(timezone.utc)``;
  callers (and tests) may pass an explicit ``now`` for deterministic behaviour.
* **Import-safe.** The persistence layer is pulled in through a guarded block so
  merely importing this module never crashes app startup; the session-dependent
  entrypoints raise / no-op cleanly when the DB layer is absent.
* **Best-effort, idempotent runner.** :func:`process_due_publishes` NEVER raises
  out of its per-item loop — a publish failure is isolated to that one schedule
  (marked ``failed`` with ``attempts+1``) and the runner keeps going. The
  guarded claim makes re-runs safe (a claimed row is not re-claimed).
* **No secrets.** All platform credentials live in ``upload_post`` /
  ``publish``; this module only orchestrates scheduling.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, ContextManager

from loguru import logger

from app.models import const

# --------------------------------------------------------------------------- #
# Guarded persistence-layer import (keeps this module import-safe even when the
# DB layer / driver is not yet configured).
# --------------------------------------------------------------------------- #
try:
    from app.models.db import base as db_base
    from app.models.db.repositories import (
        JobRepository,
        ScheduledPublishRepository,
    )

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before DB layer exists
    db_base = None  # type: ignore[assignment]
    JobRepository = None  # type: ignore[assignment]
    ScheduledPublishRepository = None  # type: ignore[assignment]
    _DB_IMPORT_ERROR = exc


#: Platforms this scheduler knows how to publish to (mirrors the on-demand
#: publish targets). A schedule must request at least one of these.
ALLOWED_PLATFORMS: tuple[str, ...] = ("tiktok", "instagram", "youtube_shorts")
_DEFAULT_YOUTUBE_PRIVACY: str = "private"

#: Upper bound on the persisted (and client-visible) error string. Platform SDK
#: exceptions can be huge (full HTTP response bodies); cap them defensively.
_MAX_ERROR_LEN: int = 500

#: Substrings that commonly wrap secrets in platform-SDK exception text. Any
#: match is replaced with ``[redacted]`` before the error is stored on the row
#: (and, via the public serialiser, returned to the owner). The full, unredacted
#: string is still logged server-side for diagnostics.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # `Authorization: Bearer <token>` fragments.
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"),
    # `token=...`, `secret: ...`, `api_key=...`, etc.
    re.compile(
        r"(?i)\b(?:token|secret|password|passwd|api[_-]?key|authorization|"
        r"access[_-]?token|refresh[_-]?token|client[_-]?secret)\b\s*[=:]\s*\S+"
    ),
    # Long high-entropy blobs (opaque tokens, signatures, account ids).
    re.compile(r"[A-Za-z0-9_\-]{32,}"),
)


class ScheduleError(ValueError):
    """Raised when a schedule cannot be created (bad job / ownership / input)."""


def _now(now: datetime | None) -> datetime:
    """Return ``now`` if provided (deterministic tests), else real UTC time."""
    return now if now is not None else datetime.now(timezone.utc)


def _sanitize_error(exc: BaseException) -> str:
    """Redact secret-looking substrings from ``exc`` and cap its length.

    The returned string is persisted on the schedule row (``row.error``) and
    served back to the owner via ``GET /me/scheduled``. Platform SDK exceptions
    can embed the raw HTTP response body — OAuth token fragments, account ids,
    signed URLs — which the SDK does not always scrub. We strip obvious secrets
    and truncate before the value can reach the DB. The caller still logs the
    full, unredacted exception server-side for diagnostics.
    """
    text = str(exc)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    text = text.strip()
    if len(text) > _MAX_ERROR_LEN:
        text = text[:_MAX_ERROR_LEN].rstrip() + "…"
    return text or "publish failed"


def _normalize_platforms(platforms: list[str] | None) -> list[str]:
    """Strip/deduplicate platform names, preserving order.

    Untrusted input: coerces each entry to ``str``, drops blanks, and removes
    duplicates so a request cannot double-post to the same platform.
    """
    seen: set[str] = set()
    normalized: list[str] = []
    for raw in platforms or []:
        name = str(raw).strip()
        if name and name not in seen:
            seen.add(name)
            normalized.append(name)
    return normalized


def _default_session_factory() -> Callable[[], ContextManager[Any]]:
    """Return ``base.get_session`` (resolved at call time so tests can patch it).

    Raises ``RuntimeError`` when the persistence layer is unavailable so a
    misconfigured deployment fails with a clear, actionable message rather than
    an opaque ``AttributeError``.
    """
    if _DB_IMPORT_ERROR is not None or db_base is None:
        raise RuntimeError(
            f"persistence layer is not available: {_DB_IMPORT_ERROR}"
        )
    return db_base.get_session


def schedule_publish(
    session,
    user_id: str,
    job_id: str,
    platforms: list[str],
    scheduled_at: datetime,
    youtube_privacy_status: str = "private",
    now: datetime | None = None,
) -> Any:
    """Create a scheduled auto-publish for a completed job.

    Validates that ``job_id`` belongs to ``user_id`` and is **done**
    (``TASK_STATE_COMPLETE``), that at least one recognised platform is
    requested, and that ``scheduled_at`` is a real datetime **in the future**;
    then inserts a ``pending`` :class:`ScheduledPublish` row.

    The future-time guard is enforced here (not only in the HTTP controller) so
    that any caller — a Celery task, a management script, or a future internal
    endpoint — cannot insert a past-time schedule that the due-runner would
    publish immediately on the next tick.

    Args:
        session: An active SQLAlchemy session (transaction owned by the caller).
        user_id: The owner scheduling the publish.
        job_id: The completed job whose final output will be published.
        platforms: Target platforms (subset of :data:`ALLOWED_PLATFORMS`).
        scheduled_at: The future UTC time to publish at.
        youtube_privacy_status: YouTube privacy override; defaults to ``private``.
        now: Reference UTC time for the future check (defaults to real
            ``datetime.now(utc)``); tests pass an explicit value for determinism.

    Returns:
        The persisted :class:`ScheduledPublish` row.

    Raises:
        ScheduleError: On a missing/foreign/not-done job, no valid platform, or
            a ``scheduled_at`` that is not a datetime or is not in the future.
    """
    if ScheduledPublishRepository is None or JobRepository is None:
        raise RuntimeError(
            f"persistence layer is not available: {_DB_IMPORT_ERROR}"
        )

    if not isinstance(scheduled_at, datetime):
        raise ScheduleError("scheduled_at must be a datetime")

    effective_now = _now(now)
    if scheduled_at.astimezone(timezone.utc) <= effective_now:
        raise ScheduleError("scheduled_at must be in the future")

    normalized = _normalize_platforms(platforms)
    if not normalized:
        raise ScheduleError("at least one platform is required to schedule")
    unknown = [p for p in normalized if p not in ALLOWED_PLATFORMS]
    if unknown:
        raise ScheduleError(
            f"unsupported platform(s): {', '.join(unknown)}; "
            f"allowed: {', '.join(ALLOWED_PLATFORMS)}"
        )

    job = JobRepository(session).get(job_id)
    if job is None or job.user_id != user_id:
        # Same error for missing and foreign so a caller cannot probe for the
        # existence of another user's job by guessing ids.
        raise ScheduleError(f"job not found: {job_id}")
    if job.state != const.TASK_STATE_COMPLETE:
        raise ScheduleError(
            f"job is not complete (state={job.state}): {job_id}"
        )

    row = ScheduledPublishRepository(session).create(
        user_id=user_id,
        job_id=job_id,
        platforms=normalized,
        scheduled_at=scheduled_at,
        youtube_privacy_status=(youtube_privacy_status or _DEFAULT_YOUTUBE_PRIVACY),
    )
    logger.info(
        f"scheduled publish {row.id} for job {job_id} "
        f"-> {', '.join(normalized)} at {scheduled_at.isoformat()}"
    )
    return row


def list_scheduled(session, user_id: str, status: str | None = None) -> list[Any]:
    """Convenience wrapper: list a user's schedules (optionally by ``status``)."""
    if ScheduledPublishRepository is None:
        raise RuntimeError(
            f"persistence layer is not available: {_DB_IMPORT_ERROR}"
        )
    return ScheduledPublishRepository(session).list_for_user(user_id, status=status)


def cancel_scheduled(session, schedule_id: str, user_id: str) -> bool:
    """Convenience wrapper: cancel a user's still-``pending`` schedule."""
    if ScheduledPublishRepository is None:
        raise RuntimeError(
            f"persistence layer is not available: {_DB_IMPORT_ERROR}"
        )
    return ScheduledPublishRepository(session).cancel(schedule_id, user_id)


def _claim_snapshots(session_factory, now: datetime, limit: int) -> list[dict]:
    """Claim due schedules in one committed transaction; return JSON-safe copies.

    Returns a plain snapshot per claimed row (owner / job / publish settings) so
    no live ORM object escapes the session and the actual (slow, network)
    entitlement verification and publish happen outside any open transaction.
    """
    with session_factory() as session:  # commits the claim flip on exit
        claimed = ScheduledPublishRepository(session).claim_due(now, limit=limit)
        return [
            {
                "id": row.id,
                "user_id": row.user_id,
                "job_id": row.job_id,
                "platforms": list(row.platforms or []),
                "youtube_privacy_status": row.youtube_privacy_status,
            }
            for row in claimed
        ]


def _publish_one(session_factory, item: dict) -> bool:
    """Publish a single claimed schedule; mark it published/failed.

    Returns ``True`` on success, ``False`` on failure. NEVER raises — any error
    (publish failure or a bookkeeping error) is caught and, best-effort, the row
    is marked ``failed`` so the runner loop keeps going.
    """
    schedule_id = item["id"]
    try:
        # Entitlement is checked again at execution time: a schedule may be
        # created days before it runs, and paid distribution access can change
        # in between. Verification failures fail closed and become a visible,
        # sanitised schedule failure the creator can retry after restoring access.
        from app.services.user_entitlements import require_paid_access

        require_paid_access(str(item["user_id"]))

        # Use the same owner-scoped native OAuth connectors as "Publish now";
        # schedules must never post through a shared operator social account.
        from app.domains.publishing.native_service import publish_scheduled_reel_native

        result = publish_scheduled_reel_native(
            str(item["user_id"]),
            item["job_id"],
            item["platforms"],
            youtube_privacy_status=item["youtube_privacy_status"],
        )
        still_processing = any(
            entry.get("status") == "processing"
            for entry in (result.get("results") or [])
            if isinstance(entry, dict)
        )
        with session_factory() as session:
            repo = ScheduledPublishRepository(session)
            if still_processing:
                # Instagram/TikTok are still ingesting: the publish-status sweep
                # resumes these platforms and flips the row when they resolve.
                repo.mark_processing(schedule_id, result)
            else:
                repo.mark_published(schedule_id, result)
        if still_processing:
            logger.info(f"scheduled publish {schedule_id} dispatched; platform processing")
        else:
            logger.info(f"published scheduled publish {schedule_id}")
            _safe_notify_published(item["user_id"], item["job_id"], result)
        return True
    except Exception as exc:  # noqa: BLE001 - the loop must survive any failure
        # Full, unredacted diagnostic goes to the server log only.
        logger.error(f"scheduled publish {schedule_id} failed: {exc}")
        try:
            # Persist a sanitised (secret-scrubbed, length-capped) message: the
            # row.error field is returned to the owner via GET /me/scheduled.
            with session_factory() as session:
                ScheduledPublishRepository(session).mark_failed(
                    schedule_id, _sanitize_error(exc)
                )
        except Exception as mark_exc:  # noqa: BLE001 - best-effort bookkeeping
            logger.error(
                f"failed to mark scheduled publish {schedule_id} failed: "
                f"{mark_exc}"
            )
        _safe_notify_publish_failed(item["user_id"], item["job_id"], _sanitize_error(exc))
        return False


def _safe_notify_published(user_id: str, job_id: str, result: dict) -> None:
    """Best-effort 'your reel is live' notification (never raises)."""
    try:
        from app.services import notifications

        entries = [e for e in (result.get("results") or []) if isinstance(e, dict)]
        notifications.notify_publish_complete(
            str(user_id),
            str(job_id),
            [str(e.get("platform") or "") for e in entries],
            [str(e.get("url") or "") for e in entries],
        )
    except Exception as exc:  # noqa: BLE001 - notification must not break the runner
        logger.warning(f"publish-complete notification failed for job {job_id}: {exc}")


def _safe_notify_publish_failed(user_id: str, job_id: str, error: str) -> None:
    """Best-effort 'publish failed' notification (never raises)."""
    try:
        from app.services import notifications

        notifications.notify_publish_failed(str(user_id), str(job_id), error)
    except Exception as exc:  # noqa: BLE001 - notification must not break the runner
        logger.warning(f"publish-failed notification failed for job {job_id}: {exc}")


# Give a platform this long to finish ingesting before the post is failed.
PROCESSING_TIMEOUT = timedelta(hours=6)


def _resume_entries(item: dict) -> tuple[list[dict], list[str]]:
    """Resume every still-``processing`` platform of one claimed row.

    Returns the updated per-platform result list and any terminal errors.
    """
    from app.domains.publishing.native_service import (
        NativePublishError,
        resume_native_publish,
    )

    entries: list[dict] = []
    errors: list[str] = []
    for entry in item["results"]:
        if not isinstance(entry, dict) or entry.get("status") != "processing":
            entries.append(entry)
            continue
        try:
            resumed = resume_native_publish(
                str(item["user_id"]),
                item["job_id"],
                str(entry.get("platform") or ""),
                str(entry.get("external_id") or ""),
            )
            entries.append(
                {
                    **entry,
                    "status": resumed.status,
                    "external_id": resumed.external_id or entry.get("external_id"),
                    "url": resumed.url or entry.get("url", ""),
                }
            )
        except NativePublishError as exc:
            message = _sanitize_error(exc)
            errors.append(f"{entry.get('platform')}: {message}")
            entries.append({**entry, "status": "failed", "error": message})
    return entries, errors


def _resume_one(session_factory, item: dict, reference: datetime) -> str:
    """Resume one claimed ``processing`` row; return its new status. Never raises."""
    schedule_id = item["id"]
    try:
        entries, errors = _resume_entries(item)
    except Exception as exc:  # noqa: BLE001 - keep the row for the next pass
        logger.error(f"resume of processing publish {schedule_id} failed: {exc}")
        entries, errors = list(item["results"]), []
    result = {**item["result"], "results": entries}
    pending = any(isinstance(e, dict) and e.get("status") == "processing" for e in entries)
    timed_out = pending and (reference - item["since"]) > PROCESSING_TIMEOUT
    if timed_out:
        errors.append("the platform did not finish processing the video in time")
    try:
        with session_factory() as session:
            repo = ScheduledPublishRepository(session)
            if errors:
                result["success"] = False
                repo.mark_processing(schedule_id, result)  # persist per-platform detail
                repo.mark_failed(schedule_id, "; ".join(errors)[:1000])
                status = "failed"
            elif pending:
                repo.mark_processing(schedule_id, result)
                return "processing"
            else:
                repo.mark_published(schedule_id, result)
                status = "published"
    except Exception as exc:  # noqa: BLE001 - bookkeeping is best-effort
        logger.error(f"could not persist resume of {schedule_id}: {exc}")
        return "error"
    if status == "published":
        _safe_notify_published(item["user_id"], item["job_id"], result)
    else:
        _safe_notify_publish_failed(item["user_id"], item["job_id"], "; ".join(errors))
    return status



def resume_processing_publishes(
    now: datetime | None = None,
    limit: int = 20,
    session_factory: Callable[[], ContextManager[Any]] | None = None,
) -> dict[str, int]:
    """Re-poll publishes a platform is still ingesting (beat entrypoint).

    Claims ``processing`` rows (guarded flip, so overlapping sweeps never
    double-publish), resumes each still-processing platform through its native
    connector, and flips the row to ``published`` / ``failed`` or back to
    ``processing``. Never raises.
    """
    summary = {"claimed": 0, "published": 0, "failed": 0, "processing": 0}
    reference = _now(now)
    try:
        factory = session_factory or _default_session_factory()
        with factory() as session:
            rows = ScheduledPublishRepository(session).claim_processing(limit=limit)
            items = []
            for row in rows:
                result = dict(row.result or {})
                since = row.scheduled_at or reference
                if since.tzinfo is None:
                    since = since.replace(tzinfo=timezone.utc)
                items.append(
                    {
                        "id": row.id,
                        "user_id": row.user_id,
                        "job_id": row.job_id,
                        "result": result,
                        "results": list(result.get("results") or []),
                        "since": since,
                    }
                )
    except Exception as exc:  # noqa: BLE001 - never raise out of beat
        logger.error(f"resume_processing_publishes claim failed: {exc}")
        return summary

    summary["claimed"] = len(items)
    for item in items:
        status = _resume_one(factory, item, reference)
        if status in summary:
            summary[status] += 1
    if items:
        logger.info(f"resume_processing_publishes: {summary}")
    return summary


def process_due_publishes(
    now: datetime | None = None,
    limit: int = 20,
    session_factory: Callable[[], ContextManager[Any]] | None = None,
) -> dict[str, int]:
    """Publish every schedule whose time has arrived (the due-runner entrypoint).

    Claims up to ``limit`` due ``pending`` schedules (flipping them to
    ``publishing`` in one committed transaction so a concurrent runner cannot
    double-claim), then publishes each via
    the owner-scoped native publishing service, marking it ``published`` on
    success or ``failed`` (with ``attempts+1``) on error. Exceptions are guarded
    per item — this function NEVER raises out of the loop.

    Args:
        now: The reference UTC time (defaults to real ``datetime.now(utc)``).
            Tests pass an explicit value for determinism.
        limit: Maximum number of schedules to claim/publish this tick.
        session_factory: Context-manager session factory (defaults to
            ``app.models.db.base.get_session``); injectable for tests.

    Returns:
        A summary ``{"claimed": int, "published": int, "failed": int}``.
    """
    summary = {"claimed": 0, "published": 0, "failed": 0}
    reference = _now(now)
    try:
        factory = session_factory or _default_session_factory()
    except Exception as exc:  # noqa: BLE001 - never raise out of the runner
        logger.error(f"process_due_publishes could not open a session: {exc}")
        return summary

    try:
        items = _claim_snapshots(factory, reference, limit)
    except Exception as exc:  # noqa: BLE001 - claim errors must not crash beat
        logger.error(f"process_due_publishes claim step failed: {exc}")
        return summary

    summary["claimed"] = len(items)
    for item in items:
        if _publish_one(factory, item):
            summary["published"] += 1
        else:
            summary["failed"] += 1

    if items:
        logger.info(
            f"process_due_publishes: claimed={summary['claimed']} "
            f"published={summary['published']} failed={summary['failed']}"
        )
    return summary


__all__ = [
    "ALLOWED_PLATFORMS",
    "ScheduleError",
    "cancel_scheduled",
    "list_scheduled",
    "process_due_publishes",
    "resume_processing_publishes",
    "schedule_publish",
]
