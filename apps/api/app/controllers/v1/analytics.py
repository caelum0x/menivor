"""ReelForge Creator Analytics controller (BI dashboard).

A single, auth-gated, strictly caller-scoped endpoint that surfaces the richer
business-intelligence view computed by :mod:`app.services.analytics` over the
data ReelForge already records (``Job`` / ``JobEvent`` / ``CreditLedger``):

* ``GET /me/analytics?days=`` — the caller's funnel, cost-over-time, credit
  burn-rate + live balance, render-time distribution and usage breakdowns
  (:func:`app.services.analytics.creator_analytics`), merged with their
  most-used templates/hooks (:func:`app.services.analytics.top_content`).

Design notes
------------
* **Auth + persistence guard reused.** ``_require_db`` / ``_resolve_user`` /
  ``get_session`` are imported from :mod:`app.controllers.v1.jobs` (the canonical
  guard shared by every ``/me`` surface), so the two auth paths (Clerk JWT +
  ``x-api-key``) and the get-or-create behaviour are identical to the rest of the
  API and this module stays import-safe. A missing DB layer degrades to a clean
  ``503`` at request time instead of an ImportError at startup.
* **Strictly caller-scoped.** The service is invoked only with the *resolved*
  caller's ``user.id`` — there is no code path that reads another user's data, so
  a creator can never observe another creator's jobs, spend or render times.
* **Cheap enough to poll.** ``days`` is clamped to a sane ``1..365`` window so a
  dashboard poll can never request an unbounded scan.
* Every response uses the MPT envelope ``utils.get_response`` and every error is
  raised as :class:`HttpException`.
"""

from __future__ import annotations

from typing import Any

from fastapi import Query, Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router

# Reuse the canonical persistence guard + auth helpers from jobs.py (which owns
# the guarded DB import). When the DB layer is absent these raise a clean 503.
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.models.schema import AnalyticsResponse
from app.utils import utils

router = new_router()

# Sane bounds for the trailing analytics window (in days). A dashboard poll is
# clamped into this range so a bad/hostile ``days`` value can never request an
# unbounded scan; the service applies its own defence-in-depth clamp as well.
_MIN_DAYS: int = 1
_MAX_DAYS: int = 365
_DEFAULT_DAYS: int = 30

# Max entries per ``top_content`` list (templates / hooks).
_TOP_LIMIT: int = 10


def _clamp_days(days: int) -> int:
    """Clamp ``days`` to the supported ``_MIN_DAYS.._MAX_DAYS`` window.

    A non-integer / invalid value falls back to the default window rather than
    raising, so the dashboard is resilient to a malformed query parameter.
    """
    try:
        value = int(days)
    except (TypeError, ValueError):
        return _DEFAULT_DAYS
    return max(_MIN_DAYS, min(value, _MAX_DAYS))


@router.get(
    "/me/analytics",
    response_model=AnalyticsResponse,
    summary="Current user's BI analytics dashboard",
)
def me_analytics(
    request: Request,
    days: int = Query(
        _DEFAULT_DAYS,
        ge=_MIN_DAYS,
        le=_MAX_DAYS,
        description="Trailing window size in days (clamped to 1..365).",
    ),
):
    """Return the authenticated caller's BI analytics (strictly caller-scoped).

    Merges :func:`creator_analytics` (funnel, cost-over-time, credit burn +
    balance, render-time percentiles, usage breakdowns) with
    :func:`top_content` (most-used templates/hooks) under a ``top_content`` key.
    Every figure is computed only for the resolved caller — never another user.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)

    try:
        from app.services.analytics import creator_analytics, top_content
    except Exception as exc:  # noqa: BLE001 - analytics service optional at import
        logger.error(
            f"analytics service unavailable, request_id: {request_id}: {exc}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: analytics service is not available",
        )

    window_days = _clamp_days(days)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            data: dict[str, Any] = creator_analytics(session, user.id, window_days)
            data["top_content"] = top_content(session, user.id, limit=_TOP_LIMIT)
        except Exception as exc:  # noqa: BLE001 - aggregation failure -> 502
            logger.error(
                f"creator_analytics failed for {user.id}, "
                f"request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=502,
                message=f"{request_id}: failed to compute analytics",
            )
    return utils.get_response(200, data)
