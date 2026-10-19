"""Publishing Calendar service for ReelForge.

Backs a creator's publishing CALENDAR — a month/week grid of their scheduled +
already-published reels — built entirely on top of the EXISTING
:class:`~app.models.db.models.ScheduledPublish` table and its
:class:`~app.models.db.repositories.ScheduledPublishRepository` (no new table, no
migration). This module only *reads* a safe, owner-scoped window of schedules and
*reschedules* a still-``pending`` one; the actual publishing is still owned by
:mod:`app.services.scheduler` / the due-runner.

Design notes
------------
* **Strictly owner-scoped.** Every read/write goes through the repository's
  owner-scoped methods (``list_in_range`` / ``get_for_user`` / ``reschedule``),
  which all filter ``ScheduledPublish.user_id == user_id``. A caller can never
  observe or move another creator's schedule by guessing its id.
* **Safe DTO only.** :func:`calendar_view` projects each row to a minimal,
  render-only dict — ``id`` / ``job_id`` / ``platforms`` / ``scheduled_at`` /
  ``status`` — deliberately omitting ``user_id``, the opaque ``result`` payload,
  the (potentially secret-bearing) ``error`` string, ``attempts`` and
  ``youtube_privacy_status``. No cross-tenant data and no private financials ever
  reach the API/frontend.
* **UTC everywhere.** All boundaries are normalised to aware UTC. Naive inputs
  are treated as UTC. The frontend renders these in the creator's own timezone.
* **Bounded window.** The requested range is validated (``start < end``, else a
  :class:`CalendarError`) and **clamped** to at most :data:`MAX_CALENDAR_RANGE_DAYS`
  so a request can never fan out an unbounded scan.
* **Import-safe.** The persistence layer is pulled in through a guarded block so
  merely importing this module never crashes app startup; the session-dependent
  entrypoints raise a clear ``RuntimeError`` when the DB layer is absent.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

# --------------------------------------------------------------------------- #
# Guarded persistence-layer import (keeps this module import-safe even when the
# DB layer / driver is not yet configured).
# --------------------------------------------------------------------------- #
try:
    from app.models.db.repositories import (
        SCHEDULE_STATUS_PENDING as _SCHEDULE_STATUS_PENDING,
    )
    from app.models.db.repositories import ScheduledPublishRepository

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before DB layer exists
    _SCHEDULE_STATUS_PENDING = "pending"
    ScheduledPublishRepository = None  # type: ignore[assignment,misc]
    _DB_IMPORT_ERROR = exc


#: Maximum span (in days) a single calendar query may cover. A wider requested
#: window is clamped down to this so a client can never trigger an unbounded
#: range scan; ~92 days comfortably spans a three-month grid.
MAX_CALENDAR_RANGE_DAYS: int = 92


class CalendarError(ValueError):
    """Raised on an invalid calendar request or a non-pending reschedule.

    A ``ValueError`` subclass so a caller catching either sees it; ownership
    failures raise :class:`PermissionError` instead (see :func:`reschedule_publish`).
    """


def _require_db() -> None:
    """Raise a clear ``RuntimeError`` when the persistence layer is unavailable."""
    if _DB_IMPORT_ERROR is not None or ScheduledPublishRepository is None:
        raise RuntimeError(
            f"persistence layer is not available: {_DB_IMPORT_ERROR}"
        )


def _ensure_utc(value: datetime) -> datetime:
    """Normalise a datetime to aware UTC (a naive value is assumed to be UTC).

    Raises :class:`CalendarError` when ``value`` is not a ``datetime`` so an
    untrusted boundary can never reach the query half-validated.
    """
    if not isinstance(value, datetime):
        raise CalendarError("start and end must be datetimes")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _validate_range(
    start_utc: datetime, end_utc: datetime
) -> tuple[datetime, datetime]:
    """Normalise, validate and clamp a calendar window to at most 92 days.

    Both bounds are coerced to aware UTC. An inverted / empty range
    (``start >= end``) is rejected with a :class:`CalendarError`. A window wider
    than :data:`MAX_CALENDAR_RANGE_DAYS` is clamped by pulling ``end`` back to
    ``start + MAX_CALENDAR_RANGE_DAYS`` so the query is always bounded.
    """
    start = _ensure_utc(start_utc)
    end = _ensure_utc(end_utc)
    if start >= end:
        raise CalendarError("start must be strictly before end")
    limit = timedelta(days=MAX_CALENDAR_RANGE_DAYS)
    if datetime.max.replace(tzinfo=timezone.utc) - start > limit:
        max_end = start + limit
        if end > max_end:
            end = max_end
    return start, end


def _safe_dto(row: Any) -> dict:
    """Project a ``ScheduledPublish`` row to the minimal, render-only calendar DTO.

    Exposes ONLY ``id`` / ``job_id`` / ``platforms`` / ``scheduled_at`` (ISO-8601
    UTC) / ``status`` — never ``user_id``, ``result``, ``error``, ``attempts`` or
    ``youtube_privacy_status`` — so no cross-tenant data or private field is ever
    serialised to the API/frontend.
    """
    scheduled_at = getattr(row, "scheduled_at", None)
    # Emit a normalised aware-UTC ISO-8601 string so the API is consistent per
    # the "times are UTC in the API" contract regardless of backend (a SQLite
    # DateTime round-trips naive; a naive value is a UTC value here).
    scheduled_iso = (
        _ensure_utc(scheduled_at).isoformat() if scheduled_at else None
    )
    return {
        "id": getattr(row, "id", None),
        "job_id": getattr(row, "job_id", None),
        "platforms": list(getattr(row, "platforms", None) or []),
        "scheduled_at": scheduled_iso,
        "status": getattr(row, "status", None),
    }


def calendar_view(
    session,
    user_id: str,
    start_utc: datetime,
    end_utc: datetime,
) -> list[dict]:
    """Return the caller's schedules in ``[start_utc, end_utc]`` as safe DTOs.

    The window is normalised to UTC, validated (``start < end``) and clamped to
    at most :data:`MAX_CALENDAR_RANGE_DAYS`. Every row is owner-scoped (only
    ``user_id``'s schedules) and projected via :func:`_safe_dto`, soonest-due
    first — suitable for direct rendering in a month/week grid.

    Args:
        session: An active SQLAlchemy session (transaction owned by the caller).
        user_id: The owner whose calendar is being read.
        start_utc: Inclusive lower bound of the window.
        end_utc: Inclusive upper bound of the window.

    Returns:
        A list of safe DTO dicts (``id`` / ``job_id`` / ``platforms`` /
        ``scheduled_at`` / ``status``), ordered by ``scheduled_at`` ascending.

    Raises:
        CalendarError: On a non-datetime or inverted / empty range.
        RuntimeError: When the persistence layer is unavailable.
    """
    _require_db()
    start, end = _validate_range(start_utc, end_utc)
    rows = ScheduledPublishRepository(session).list_in_range(user_id, start, end)
    return [_safe_dto(row) for row in rows]


def reschedule_publish(
    session,
    user_id: str,
    schedule_id: str,
    new_scheduled_at: datetime,
) -> dict:
    """Move a still-``pending`` schedule owned by ``user_id`` to a new UTC time.

    Verifies ownership and pending-only status before the guarded UPDATE so the
    outcome is deterministic:

    * a missing / foreign id raises :class:`PermissionError` (the two are
      indistinguishable so a guessed id can neither move nor confirm the
      existence of a foreign schedule);
    * a non-``pending`` schedule (already publishing / published / failed /
      canceled) raises :class:`CalendarError` and the row is left untouched.

    Args:
        session: An active SQLAlchemy session (transaction owned by the caller).
        user_id: The owner performing the reschedule.
        schedule_id: The schedule to move.
        new_scheduled_at: The new target time (normalised to aware UTC).

    Returns:
        The updated safe DTO (see :func:`_safe_dto`).

    Raises:
        CalendarError: On a bad time or a non-pending schedule.
        PermissionError: When the schedule is missing or owned by another user.
        RuntimeError: When the persistence layer is unavailable.
    """
    _require_db()
    new_at = _ensure_utc(new_scheduled_at)

    repo = ScheduledPublishRepository(session)
    existing = repo.get_for_user(schedule_id, user_id)
    if existing is None:
        # Same failure for missing and foreign so a caller cannot probe for the
        # existence of another user's schedule by guessing ids.
        raise PermissionError("scheduled publish not found")
    if existing.status != _SCHEDULE_STATUS_PENDING:
        raise CalendarError(
            f"scheduled publish is not pending (status={existing.status}); "
            f"cannot reschedule"
        )

    row = repo.reschedule(schedule_id, user_id, new_at)
    if row is None:
        # Lost a race with the due-runner (claimed between the read and the
        # guarded UPDATE): report a conflict rather than a false success.
        raise CalendarError("scheduled publish is no longer pending")

    logger.info(
        f"rescheduled publish {schedule_id} -> {new_at.isoformat()} "
        f"for user {user_id}"
    )
    return _safe_dto(row)


__all__ = [
    "MAX_CALENDAR_RANGE_DAYS",
    "CalendarError",
    "calendar_view",
    "reschedule_publish",
]
