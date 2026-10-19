"""ReelForge Scheduled Publishing API controller.

Auth-gated, strictly owner-scoped endpoints (served under ``/api/v1`` via
:func:`app.controllers.v1.base.new_router`) that let a creator queue a *finished*
reel to auto-publish to social platforms (tiktok | instagram | youtube_shorts)
through the creator's connected native accounts at a future UTC time. A background Celery-beat
due-runner (owned by the workers layer) publishes claimed schedules; this module
only creates, lists and cancels them.

Endpoints
---------
* ``POST   /jobs/{job_id}/schedule`` — queue a schedule for a completed, owned
  job. ``404`` unknown/foreign job, ``409`` job not done, ``400`` empty/invalid
  platforms or a ``scheduled_at`` that is unparseable or in the past.
* ``GET    /me/scheduled``           — the caller's schedules (optional
  ``?status=`` filter).
* ``DELETE /me/scheduled/{id}``      — cancel a still-``pending`` schedule
  (``404`` unknown/foreign, ``409`` no longer pending).

Design notes
------------
* **Auth + persistence guard reused.** ``_require_db`` / ``_resolve_user`` /
  ``get_session`` come from :mod:`app.controllers.v1.jobs` (the canonical guard),
  so the two auth paths (Clerk JWT + ``x-api-key``, get-or-create) and the 503
  degradation are identical to the rest of the API and this module stays
  import-safe.
* **Ownership / lifecycle decided here.** The controller resolves the caller,
  loads the ``Job`` and ``ScheduledPublish`` rows itself and maps missing/foreign
  ⇒ ``404``, wrong-state ⇒ ``409`` (mirroring ``studio.publish_job``) so those
  outcomes are deterministic even when the scheduler service is monkeypatched in
  tests. Row creation itself is delegated to
  :func:`app.services.scheduler.schedule_publish`.
* Every response uses the MPT envelope ``utils.get_response`` and every error is
  raised as :class:`HttpException`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import Path, Query, Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.launch import require_publishing_enabled

# Reuse the canonical persistence guard + auth helpers from jobs.py (which owns
# the guarded DB import). When the DB layer is absent these are ``None`` and
# ``_require_db`` raises a clean 503 at request time.
from app.controllers.v1.jobs import Job, _require_db, _resolve_user, get_session
# NOTE: ``app.domains.publishing.native_service`` is imported lazily inside the
# handler below (see ``_verify_native_connections``) rather than at module load.
# A top-level import here forms a circular import: importing that submodule runs
# ``app.domains.publishing.__init__`` -> ``.router`` -> references
# ``app.controllers.v1.schedule.router`` before this module has finished defining
# it. Deferring the import breaks the cycle regardless of import order.
from app.models.const import TASK_STATE_COMPLETE
from app.models.exception import HttpException
from app.models.schema import (
    ScheduledListResponse,
    ScheduledResponse,
    ScheduleRequest,
)
from app.services import scheduler
from app.services.billing.pro_access import require_pro_action
from app.utils import utils

router = new_router()


# --------------------------------------------------------------------------- #
# Guarded schedule-repository import (authored by the sibling DB agent; may be
# absent at compile time). Keeps this module import-safe — a missing layer
# degrades to a clean 503 at request time (via ``_require_schedules``).
# --------------------------------------------------------------------------- #
try:
    from app.models.db.repositories import (
        SCHEDULE_STATUS_PENDING as _SCHEDULE_STATUS_PENDING,
    )
    from app.models.db.repositories import ScheduledPublishRepository

    _SCHEDULE_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before the DB layer
    _SCHEDULE_STATUS_PENDING = "pending"
    ScheduledPublishRepository = None  # type: ignore[assignment,misc]
    _SCHEDULE_IMPORT_ERROR = exc


def _require_schedules(request_id: str) -> None:
    """Raise 503 when the scheduled-publish persistence layer is unavailable."""
    if _SCHEDULE_IMPORT_ERROR is not None or ScheduledPublishRepository is None:
        logger.error(
            f"scheduled-publish layer unavailable, request_id: {request_id}, "
            f"error: {_SCHEDULE_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: scheduling is not available",
        )


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _parse_scheduled_at(raw: str, request_id: str) -> datetime:
    """Parse an ISO-8601 timestamp into an aware UTC ``datetime``.

    Accepts a trailing ``Z`` (treated as ``+00:00``) and normalises a naive
    value to UTC. Raises ``400`` on an unparseable / empty value — untrusted
    input is never allowed to reach the service layer half-validated.
    """
    text = (raw or "").strip()
    if not text:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: scheduled_at is required",
        )
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except (ValueError, TypeError) as exc:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: scheduled_at must be an ISO-8601 datetime",
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _schedule_public_data(row: Any) -> dict:
    """Serialise a ``ScheduledPublish`` row to the public envelope."""
    scheduled_at = getattr(row, "scheduled_at", None)
    return {
        "id": getattr(row, "id", None),
        "job_id": getattr(row, "job_id", None),
        "platforms": list(getattr(row, "platforms", None) or []),
        "scheduled_at": scheduled_at.isoformat() if scheduled_at else None,
        "status": getattr(row, "status", None),
        "youtube_privacy_status": getattr(row, "youtube_privacy_status", None),
        "attempts": getattr(row, "attempts", None),
        "error": getattr(row, "error", None) or "",
    }


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.post(
    "/jobs/{job_id}/schedule",
    response_model=ScheduledResponse,
    summary="Schedule a completed job to auto-publish at a future UTC time",
)
def schedule_job(
    request: Request,
    body: ScheduleRequest,
    job_id: str = Path(..., description="Job ID"),
):
    """Queue a completed, owned job to auto-publish at ``scheduled_at``.

    Order: auth → ownership (``404`` unknown/foreign) → completeness (``409``
    when not done) → input validation (``400`` empty/invalid platforms or a
    past/unparseable ``scheduled_at``) → :func:`scheduler.schedule_publish`.
    """
    request_id = base.get_task_id(request)
    require_publishing_enabled(request_id)
    _require_db(request_id)
    _require_schedules(request_id)

    platforms = [
        str(p).strip()
        for p in (getattr(body, "platforms", None) or [])
        if str(p).strip()
    ]
    if not platforms:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: at least one platform is required",
        )
    unknown = [p for p in platforms if p not in scheduler.ALLOWED_PLATFORMS]
    if unknown:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=(
                f"{request_id}: unsupported platform(s): {', '.join(unknown)}; "
                f"allowed: {', '.join(scheduler.ALLOWED_PLATFORMS)}"
            ),
        )

    scheduled_at = _parse_scheduled_at(getattr(body, "scheduled_at", ""), request_id)
    if scheduled_at <= datetime.now(timezone.utc):
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: scheduled_at must be in the future",
        )

    youtube_privacy_status = getattr(body, "youtube_privacy_status", None)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        require_pro_action(str(user.id), request_id, action="scheduled publish")

        job = session.get(Job, job_id)
        if job is None or job.user_id != user.id:
            # Same 404 for missing and foreign so a caller cannot probe for the
            # existence of another user's job by guessing ids.
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: job not found",
            )
        if job.state != TASK_STATE_COMPLETE:
            raise HttpException(
                task_id=request_id,
                status_code=409,
                message=f"{request_id}: job is not complete; cannot schedule",
            )

        from app.domains.publishing.native_service import (
            NativePublishError,
            require_native_connections,
        )

        try:
            require_native_connections(str(user.id), platforms)
        except NativePublishError as exc:
            raise HttpException(
                task_id=request_id,
                status_code=exc.status_code,
                message=f"{request_id}: {exc}",
            ) from exc
        except HttpException:
            raise
        except Exception as exc:  # noqa: BLE001 - optional native layer
            logger.error(
                f"native connection verification unavailable, request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=503,
                message=f"{request_id}: publishing connections are unavailable",
            ) from exc

        try:
            row = scheduler.schedule_publish(
                session,
                user_id=user.id,
                job_id=job_id,
                platforms=platforms,
                scheduled_at=scheduled_at,
                youtube_privacy_status=(youtube_privacy_status or "private"),
            )
        except HttpException:
            raise
        except scheduler.ScheduleError as exc:
            # Defensive: the controller already validated ownership/state/input,
            # but the service re-validates — surface any residual rejection as a
            # 400 rather than leaking a 500.
            raise HttpException(
                task_id=request_id,
                status_code=400,
                message=f"{request_id}: {exc}",
            )
        except Exception as exc:  # noqa: BLE001 - persistence failure -> 502
            logger.error(
                f"schedule_publish failed for job {job_id}, "
                f"request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=502,
                message=f"{request_id}: failed to schedule publish",
            )

        data = _schedule_public_data(row)

    return utils.get_response(200, data)


@router.get(
    "/me/scheduled",
    response_model=ScheduledListResponse,
    summary="List the caller's scheduled publishes",
)
def list_scheduled(
    request: Request,
    status: str | None = Query(
        default=None, description="Optional status filter (e.g. pending)"
    ),
):
    """Return the caller's schedules, soonest-due first (optional ``status``).

    Strictly owner-scoped: only the authenticated caller's rows are ever
    returned, so a schedule can never be observed across tenants.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_schedules(request_id)

    normalized_status = (status or "").strip() or None

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            rows = scheduler.list_scheduled(
                session, user.id, status=normalized_status
            )
        except Exception as exc:  # noqa: BLE001 - persistence failure -> 502
            logger.error(
                f"list_scheduled failed, request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=502,
                message=f"{request_id}: failed to list scheduled publishes",
            )
        data = [_schedule_public_data(row) for row in rows]

    return utils.get_response(200, data)


@router.delete(
    "/me/scheduled/{schedule_id}",
    response_model=ScheduledResponse,
    summary="Cancel a still-pending scheduled publish",
)
def cancel_scheduled(
    request: Request,
    schedule_id: str = Path(..., description="Scheduled-publish ID"),
):
    """Cancel a still-``pending`` schedule owned by the caller.

    ``404`` when the id is unknown or belongs to another user (the two are
    indistinguishable so a guessed id can neither cancel nor confirm the
    existence of a foreign schedule); ``409`` when the schedule is no longer
    pending (already publishing / published / failed / canceled).
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_schedules(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        repo = ScheduledPublishRepository(session)

        row = repo.get_owned(schedule_id, user.id)
        if row is None:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: scheduled publish not found",
            )
        if row.status != _SCHEDULE_STATUS_PENDING:
            raise HttpException(
                task_id=request_id,
                status_code=409,
                message=(
                    f"{request_id}: scheduled publish is not pending "
                    f"(status={row.status}); cannot cancel"
                ),
            )

        try:
            canceled = scheduler.cancel_scheduled(session, schedule_id, user.id)
        except Exception as exc:  # noqa: BLE001 - persistence failure -> 502
            logger.error(
                f"cancel_scheduled failed for {schedule_id}, "
                f"request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=502,
                message=f"{request_id}: failed to cancel scheduled publish",
            )
        if not canceled:
            # Lost a race with the due-runner (row claimed between the read and
            # the cancel): report a conflict rather than a false success.
            raise HttpException(
                task_id=request_id,
                status_code=409,
                message=f"{request_id}: scheduled publish is no longer pending",
            )

        data = {"id": schedule_id, "status": "canceled"}

    return utils.get_response(200, data)
