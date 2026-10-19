"""In-app notifications v1 API controller (bell + unread badge + center).

Auth-gated endpoints under ``/api/v1`` that let a creator read and clear the
in-app notifications the server best-effort emits on lifecycle / growth events
(``job_complete`` / ``job_failed`` / ``low_credits`` / ``referral_earned``) —
the in-app counterpart to the external webhook (``app/services/webhooks.py``):

* ``GET  /me/notifications``               — the caller's notifications (newest
  first; ``unread_only`` / ``limit`` filters) plus the live ``unread_count`` so
  the client renders the list and refreshes the bell badge in one call.
* ``GET  /me/notifications/unread_count``  — count-only, cheap enough to poll on
  a short interval for the bell badge without materialising any rows.
* ``POST /me/notifications/{id}/read``     — flip one notification to read
  (ownership enforced; ``404`` for a missing/foreign id).
* ``POST /me/notifications/read_all``      — mark every one of the caller's
  notifications read and report how many were flipped.

Design notes
------------
* **Auth + persistence guard reused.** ``_require_db`` / ``_resolve_user`` /
  ``get_session`` are imported from :mod:`app.controllers.v1.jobs` (the canonical
  guard block behind the single ``base.verify_token`` gate), so both auth paths
  (Clerk JWT + ``x-api-key``) and the get-or-create behaviour are identical to
  the rest of the API and this module stays import-safe.
* **Strictly owner-scoped.** Every read/mutation runs through
  :class:`NotificationRepository`, which filters on the caller's ``user_id`` —
  a caller can never read, count, or flip another user's notification, and a
  guessed id can neither flip nor confirm the existence of a foreign row
  (``404``).
* **Import-safe optional deps.** The ``Notification`` repository (authored by the
  sibling DB agent) is imported inside a guarded block; when it is absent the
  endpoints degrade to a clean ``503`` at request time instead of an
  ``ImportError`` at startup (mirroring ``jobs.py`` / ``ideas.py``).
* Every response uses the MPT envelope ``utils.get_response`` and every error is
  raised as :class:`HttpException`. No secrets are hardcoded.
"""

from __future__ import annotations

from typing import Any

from fastapi import Path, Request
from loguru import logger

from app.config import config
from app.controllers import base
from app.controllers.v1.base import new_router

# Reuse the canonical persistence guard + auth helpers from jobs.py (which owns
# the guarded DB import). When the DB layer is absent these are ``None`` and
# ``_require_db`` raises a clean 503 at request time.
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.models.schema import NotificationsResponse, UnreadCountResponse
from app.utils import utils

# --------------------------------------------------------------------------- #
# Guarded optional import (authored by the sibling DB agent; may be absent at
# compile time). Keeping it guarded makes the module import-safe: a missing
# dependency degrades to a clean 503 at request time.
# --------------------------------------------------------------------------- #
try:
    from app.models.db.models import Notification  # noqa: F401 (re-exported for tests)
    from app.models.db.repositories import NotificationRepository

    _NOTIFICATIONS_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before the DB layer
    Notification = None  # type: ignore[assignment,misc]
    NotificationRepository = None  # type: ignore[assignment,misc]
    _NOTIFICATIONS_IMPORT_ERROR = exc


router = new_router()

# --------------------------------------------------------------------------- #
# Tunables (config-overridable). Cap the number of notifications returned by a
# single list call so a long-lived account cannot request an unbounded page.
# --------------------------------------------------------------------------- #
_DEFAULT_LIST_LIMIT: int = 50
_MAX_LIST_LIMIT: int = 200


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _require_notifications(request_id: str) -> None:
    """Raise 503 when the notification persistence layer is unavailable."""
    if _NOTIFICATIONS_IMPORT_ERROR is not None or NotificationRepository is None:
        logger.error(
            f"notification persistence unavailable, request_id: {request_id}, "
            f"error: {_NOTIFICATIONS_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: notification storage is not available",
        )


def _list_limit() -> int:
    """Default page size for the list endpoint (``reelforge_notifications_limit``)."""
    return int(
        config.app.get("reelforge_notifications_limit", _DEFAULT_LIST_LIMIT)
    )


def _clamp_limit(limit: Any) -> int:
    """Clamp a caller-supplied ``limit`` to ``[1, _MAX_LIST_LIMIT]``.

    Falls back to the configured default when ``limit`` is missing or not an
    integer, so a malformed query value can never yield an invalid or unbounded
    page.
    """
    try:
        value = int(limit) if limit is not None else _list_limit()
    except (TypeError, ValueError):
        value = _list_limit()
    return max(1, min(_MAX_LIST_LIMIT, value))


def _notification_public_data(row: Any) -> dict:
    """Serialise a ``Notification`` row to its public, JSON-safe envelope.

    ``data`` is copied (immutable read) so a later mutation of the returned dict
    cannot bleed back into the ORM-managed row.
    """
    created_at = getattr(row, "created_at", None)
    return {
        "id": row.id,
        "kind": row.kind,
        "title": row.title,
        "body": getattr(row, "body", "") or "",
        "data": dict(getattr(row, "data", None) or {}),
        "read": bool(getattr(row, "read", False)),
        "created_at": created_at.isoformat() if created_at is not None else None,
    }


# --------------------------------------------------------------------------- #
# GET /me/notifications  (list + unread_count)
# --------------------------------------------------------------------------- #
@router.get(
    "/me/notifications",
    response_model=NotificationsResponse,
    summary="List the caller's notifications with the live unread count",
)
def list_notifications(
    request: Request,
    unread_only: bool = False,
    limit: int | None = None,
):
    """Return the caller's notifications (newest first) plus their unread count.

    ``unread_only`` restricts the list to unread rows; ``limit`` bounds the page
    (clamped to a sane maximum). ``unread_count`` is always the caller's total
    unread count (independent of the page / filter) so the bell badge stays
    correct even on a filtered or truncated list. Strictly caller-scoped.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_notifications(request_id)

    page_limit = _clamp_limit(limit)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        repo = NotificationRepository(session)
        rows = repo.list_for_user(
            user.id, limit=page_limit, unread_only=bool(unread_only)
        )
        data = {
            "notifications": [_notification_public_data(r) for r in rows],
            "unread_count": repo.unread_count(user.id),
        }

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# GET /me/notifications/unread_count  (cheap bell-badge poll)
# --------------------------------------------------------------------------- #
@router.get(
    "/me/notifications/unread_count",
    response_model=UnreadCountResponse,
    summary="The caller's unread notification count (cheap bell-badge poll)",
)
def unread_count(request: Request):
    """Return only the caller's unread count — cheap enough to poll frequently."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_notifications(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        count = NotificationRepository(session).unread_count(user.id)

    return utils.get_response(200, {"unread_count": count})


# --------------------------------------------------------------------------- #
# POST /me/notifications/{notification_id}/read  (mark one read)
# --------------------------------------------------------------------------- #
@router.post(
    "/me/notifications/{notification_id}/read",
    summary="Mark one of the caller's notifications read",
)
def mark_notification_read(
    request: Request,
    notification_id: str = Path(..., description="Notification ID"),
):
    """Flip one notification to read. Returns ``404`` for a missing/foreign id.

    Ownership is enforced in the repository (``mark_read``): a notification that
    does not belong to the caller is indistinguishable from a missing one, so a
    guessed id can never flip — or even confirm the existence of — another user's
    notification. Marking an already-read notification is an idempotent success.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_notifications(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        marked = NotificationRepository(session).mark_read(
            notification_id, user.id
        )
        if not marked:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: notification not found",
            )

    return utils.get_response(200, {"id": notification_id, "read": True})


# --------------------------------------------------------------------------- #
# POST /me/notifications/read_all  (mark all read)
# --------------------------------------------------------------------------- #
@router.post(
    "/me/notifications/read_all",
    summary="Mark all of the caller's notifications read",
)
def mark_all_notifications_read(request: Request):
    """Mark every unread notification for the caller read; report how many flipped.

    Owner-scoped bulk update — only the caller's own unread rows are touched. The
    caller's ``unread_count`` is therefore ``0`` after this call.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_notifications(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        updated = NotificationRepository(session).mark_all_read(user.id)

    return utils.get_response(200, {"updated": int(updated), "unread_count": 0})
