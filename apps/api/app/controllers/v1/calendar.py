"""ReelForge Publishing Calendar API controller.

Auth-gated, strictly owner-scoped endpoints (served under ``/api/v1`` via
:func:`app.controllers.v1.base.new_router`) that back a creator's publishing
CALENDAR — a month/week grid of their scheduled + already-published reels — and
let them RESCHEDULE a still-``pending`` publish (drag to a new time). Everything
is built on the EXISTING :class:`~app.models.db.models.ScheduledPublish` table
and its repository (no new table, no migration); this module only *reads* an
owner-scoped window and *moves* one still-pending schedule. Cancelling a
schedule is served by the existing ``DELETE /me/scheduled/{id}`` endpoint in
:mod:`app.controllers.v1.schedule` and is deliberately NOT duplicated here.

Endpoints
---------
* ``GET   /me/calendar?start=&end=`` — the caller's schedules whose
  ``scheduled_at`` falls in the ``[start, end]`` UTC window (both ISO-8601). The
  window is clamped to at most ``MAX_CALENDAR_RANGE_DAYS`` days; an inverted /
  empty / unparseable range is a clean ``400``.
* ``PATCH /me/calendar/{schedule_id}`` — move a still-``pending`` schedule to a
  new future UTC time (body ``{scheduled_at}``). ``404`` unknown/foreign,
  ``409`` no longer pending, ``400`` a missing/unparseable/past ``scheduled_at``.

Design notes
------------
* **Auth + persistence guard reused.** ``_require_db`` / ``_resolve_user`` /
  ``get_session`` come from :mod:`app.controllers.v1.jobs` (the canonical guard),
  so both auth paths (Clerk JWT + ``x-api-key``, get-or-create) and the 503
  degradation are identical to the rest of the API and this module stays
  import-safe.
* **Ownership / lifecycle live in the service.** The controller delegates to
  :mod:`app.services.calendar`, mapping its typed failures to HTTP: a
  :class:`~app.services.calendar.CalendarError` on the window is a ``400``; on a
  reschedule a :class:`PermissionError` (missing/foreign) is a ``404`` and a
  :class:`~app.services.calendar.CalendarError` (non-pending / lost race) is a
  ``409``. Missing and foreign are indistinguishable so a guessed id can neither
  move nor confirm the existence of a foreign schedule.
* **Local Pydantic schemas.** ``CalendarEntryModel`` / ``CalendarResponse`` /
  ``RescheduleRequest`` / ``RescheduleResponse`` are defined HERE (not in
  ``app/models/schema.py``) to stay disjoint from the concurrent workflow.
* Every response uses the MPT envelope ``utils.get_response`` and every error is
  raised as :class:`HttpException`. Times are UTC in the API; the frontend
  renders them in the creator's own timezone. No secrets are hardcoded.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import Path, Query, Request
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from app.controllers import base
from app.controllers.v1.base import new_router

# Reuse the canonical persistence guard + auth helpers from jobs.py (which owns
# the guarded DB import). When the DB layer is absent these are ``None`` and
# ``_require_db`` raises a clean 503 at request time.
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.models.schema import BaseResponse
from app.utils import utils

router = new_router()


# --------------------------------------------------------------------------- #
# Guarded calendar-service import (depends on the DB layer authored by the
# sibling agent; may be absent at compile time). Keeps this module import-safe —
# a missing layer degrades to a clean 503 at request time (via
# ``_require_calendar``).
# --------------------------------------------------------------------------- #
try:
    from app.services import calendar as calendar_service

    _CALENDAR_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before the DB layer
    calendar_service = None  # type: ignore[assignment]
    _CALENDAR_IMPORT_ERROR = exc


# --------------------------------------------------------------------------- #
# Local Pydantic schemas (intentionally NOT added to app/models/schema.py so this
# controller stays fully disjoint from the concurrent workflow editing that file)
# --------------------------------------------------------------------------- #
class CalendarEntryModel(BaseModel):
    """One calendar entry — the safe, render-only projection of a schedule.

    Mirrors :func:`app.services.calendar._safe_dto`: exactly these five fields,
    never ``user_id`` / ``result`` / ``error`` / ``attempts`` /
    ``youtube_privacy_status`` — no cross-tenant data, no private financials.
    """

    id: str
    job_id: Optional[str] = None
    platforms: List[str] = Field(default_factory=list)
    scheduled_at: Optional[str] = None
    status: str = "pending"


class CalendarResponse(BaseResponse):
    """``GET /api/v1/me/calendar`` — the caller's window of schedules.

    ``data`` defaults to ``[]`` because the shared ``utils.get_response`` envelope
    drops a falsy payload — an empty window must still validate.
    """

    data: List[CalendarEntryModel] = Field(default_factory=list)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": [
                    {
                        "id": "a1b2...",
                        "job_id": "job-123",
                        "platforms": ["tiktok", "instagram"],
                        "scheduled_at": "2026-09-01T12:00:00+00:00",
                        "status": "pending",
                    }
                ],
            }
        }
    )


class RescheduleRequest(BaseModel):
    """Request body for ``PATCH /api/v1/me/calendar/{schedule_id}``.

    ``scheduled_at`` is the new target time as an ISO-8601 UTC timestamp (a
    trailing ``Z`` is accepted; a naive value is treated as UTC).
    """

    scheduled_at: str = Field(..., min_length=1, max_length=64)


class RescheduleResponse(BaseResponse):
    """``PATCH /api/v1/me/calendar/{schedule_id}`` — the moved schedule."""

    data: Optional[CalendarEntryModel] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "id": "a1b2...",
                    "job_id": "job-123",
                    "platforms": ["tiktok"],
                    "scheduled_at": "2026-09-02T09:30:00+00:00",
                    "status": "pending",
                },
            }
        }
    )


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _require_calendar(request_id: str) -> None:
    """Raise 503 when the publishing-calendar service is unavailable."""
    if _CALENDAR_IMPORT_ERROR is not None or calendar_service is None:
        logger.error(
            f"calendar service unavailable, request_id: {request_id}, "
            f"error: {_CALENDAR_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: the publishing calendar is not available",
        )


def _parse_iso(raw: str, request_id: str, field: str) -> datetime:
    """Parse an ISO-8601 timestamp into an aware UTC ``datetime``.

    Accepts a trailing ``Z`` (treated as ``+00:00``) and normalises a naive value
    to UTC. Raises ``400`` on an empty / unparseable value — untrusted input is
    never allowed to reach the service layer half-validated.
    """
    text = (raw or "").strip()
    if not text:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: {field} is required",
        )
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except (ValueError, TypeError) as exc:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: {field} must be an ISO-8601 datetime",
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# --------------------------------------------------------------------------- #
# GET /me/calendar
# --------------------------------------------------------------------------- #
@router.get(
    "/me/calendar",
    response_model=CalendarResponse,
    summary="The caller's scheduled + published reels in a UTC window",
)
def get_calendar(
    request: Request,
    start: str = Query(..., description="Inclusive ISO-8601 UTC lower bound"),
    end: str = Query(..., description="Inclusive ISO-8601 UTC upper bound"),
):
    """Return the caller's schedules in ``[start, end]`` (clamped to <=92 days).

    Strictly owner-scoped: only the authenticated caller's rows are ever
    returned. An inverted / empty / unparseable range is a clean ``400``; an
    over-wide window is clamped by the service rather than rejected.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_calendar(request_id)

    start_utc = _parse_iso(start, request_id, "start")
    end_utc = _parse_iso(end, request_id, "end")

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            data = calendar_service.calendar_view(
                session, user.id, start_utc, end_utc
            )
        except calendar_service.CalendarError as exc:
            raise HttpException(
                task_id=request_id,
                status_code=400,
                message=f"{request_id}: {exc}",
            ) from exc
        except HttpException:
            raise
        except Exception as exc:  # noqa: BLE001 - persistence failure -> 502
            logger.error(
                f"calendar_view failed, request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=502,
                message=f"{request_id}: failed to load the calendar",
            )

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# PATCH /me/calendar/{schedule_id}
# --------------------------------------------------------------------------- #
@router.patch(
    "/me/calendar/{schedule_id}",
    response_model=RescheduleResponse,
    summary="Reschedule a still-pending publish to a new future UTC time",
)
def reschedule_calendar_entry(
    request: Request,
    body: RescheduleRequest,
    schedule_id: str = Path(..., description="Scheduled-publish ID"),
):
    """Move a still-``pending`` schedule owned by the caller to ``scheduled_at``.

    Order: auth → input validation (``400`` on a missing/unparseable/past
    ``scheduled_at``) → ownership + pending-only (delegated to the service).
    ``404`` when the id is unknown or belongs to another user (indistinguishable
    so a guessed id can neither move nor confirm a foreign schedule); ``409``
    when the schedule is no longer pending (publishing / published / failed /
    canceled, or claimed by the due-runner mid-request).
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_calendar(request_id)

    new_at = _parse_iso(getattr(body, "scheduled_at", ""), request_id, "scheduled_at")
    if new_at <= datetime.now(timezone.utc):
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: scheduled_at must be in the future",
        )

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            data = calendar_service.reschedule_publish(
                session, user.id, schedule_id, new_at
            )
        except PermissionError as exc:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: scheduled publish not found",
            ) from exc
        except calendar_service.CalendarError as exc:
            raise HttpException(
                task_id=request_id,
                status_code=409,
                message=f"{request_id}: {exc}",
            ) from exc
        except HttpException:
            raise
        except Exception as exc:  # noqa: BLE001 - persistence failure -> 502
            logger.error(
                f"reschedule_publish failed for {schedule_id}, "
                f"request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=502,
                message=f"{request_id}: failed to reschedule the publish",
            )

    return utils.get_response(200, data)
