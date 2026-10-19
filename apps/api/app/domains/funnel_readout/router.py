"""Funnel read-out routes (MR1).

* ``GET  /api/v1/admin/funnel/readout?since=YYYY-MM-DD`` - staff only (403
  otherwise; 404 for non-staff under the production allowlist).
* ``POST /api/v1/funnel/attribution`` - the signed-in user's first-touch UTM
  and referrer, sent once by the web after sign-up (first touch wins).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import Body, Query, Request
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.domains.funnel_readout import service
from app.models.exception import HttpException
from app.utils import utils

router = new_router()


class AttributionRequest(BaseModel):
    utm_source: str = Field("", max_length=120)
    utm_medium: str = Field("", max_length=120)
    utm_campaign: str = Field("", max_length=120)
    referrer: str = Field("", max_length=300)


def _parse_since(raw: str, request_id: str) -> datetime:
    if not raw:
        return service.DEFAULT_SINCE
    try:
        return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HttpException(task_id=request_id, status_code=422, message="since must be YYYY-MM-DD") from exc


@router.get("/admin/funnel/readout", tags=["Admin"], summary="Funnel read-out per user (staff)")
def funnel_readout(request: Request, since: str = Query("", max_length=10)) -> Any:
    request_id = base.get_task_id(request)
    start = _parse_since(since, request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        if not bool(getattr(user, "is_staff", False)):
            raise HttpException(task_id=request_id, status_code=403, message="staff access required")
        data = service.readout_payload(session, start)
    return utils.get_response(200, data)


@router.post("/funnel/attribution", summary="Record the first-touch source (once)")
def funnel_attribution(request: Request, body: AttributionRequest = Body(...)) -> Any:
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        written = service.record_attribution(
            session,
            str(user.id),
            utm_source=body.utm_source,
            utm_medium=body.utm_medium,
            utm_campaign=body.utm_campaign,
            referrer=body.referrer,
        )
    return utils.get_response(200, {"recorded": written})


__all__ = ["router"]
