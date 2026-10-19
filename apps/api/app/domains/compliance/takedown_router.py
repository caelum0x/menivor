"""HTTP surface for content reports (MN5).

* ``POST /api/v1/legal/reports`` - public, no account. Creates a ticket and
  alerts the owner. Rate-limited per caller.
* ``GET  /api/v1/admin/takedown/reports`` - staff list (``?status=open``).
* ``POST /api/v1/admin/takedown/reports/{id}/{block|dismiss|restore}`` - staff
  actions; ``block`` soft-blocks the reported video's media.
"""

from __future__ import annotations

from typing import Any

from fastapi import Body, Path, Query, Request
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.domains.compliance import takedown
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

router = new_router()

REPORT_RATE_LIMIT = 5
REPORT_RATE_WINDOW_S = 3600
_ACTIONS = {"block": takedown.block, "dismiss": takedown.dismiss, "restore": takedown.restore}


class ReportRequest(BaseModel):
    content: str = Field(..., description="Link or id of the video being reported")
    reason: str = Field(..., description=f"One of: {', '.join(takedown.REASONS)}")
    details: str = Field("", description="What is wrong with it")
    email: str = Field(..., description="Where we can reply")


@router.post("/legal/reports", tags=["Legal"], summary="Report a video made with Menivor")
def create_content_report(request: Request, body: ReportRequest = Body(...)) -> Any:
    request_id = base.get_task_id(request)
    enforce_rate_limit(request, "legal:report", REPORT_RATE_LIMIT, REPORT_RATE_WINDOW_S)
    _require_db(request_id)
    with get_session() as session:
        try:
            report = takedown.create_report(
                session,
                content_ref=body.content,
                reason=body.reason,
                details=body.details,
                reporter_email=body.email,
            )
        except takedown.TakedownError as exc:
            raise HttpException(task_id=request_id, status_code=400, message=str(exc))
        data = {"ticket_id": report.id, "status": "received", "video_found": report.job_id is not None}
    return utils.get_response(200, data)


def _staff(request: Request, session: Any, request_id: str) -> Any:
    user = _resolve_user(request, session, request_id)
    if not bool(getattr(user, "is_staff", False)):
        raise HttpException(task_id=request_id, status_code=403, message="staff access required")
    return user


@router.get("/admin/takedown/reports", tags=["Admin"], summary="Content reports (staff)")
def list_content_reports(
    request: Request, status: str = Query("", description="open, blocked, dismissed or restored")
) -> Any:
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        _staff(request, session, request_id)
        rows = [takedown.report_view(r) for r in takedown.list_reports(session, status=status)]
    return utils.get_response(200, rows)


@router.post("/admin/takedown/reports/{report_id}/{action}", tags=["Admin"], summary="Act on a report (staff)")
def act_on_content_report(
    request: Request,
    report_id: str = Path(...),
    action: str = Path(..., description="block, dismiss or restore"),
) -> Any:
    request_id = base.get_task_id(request)
    handler = _ACTIONS.get(action)
    if handler is None:
        raise HttpException(task_id=request_id, status_code=404, message="unknown action")
    _require_db(request_id)
    with get_session() as session:
        user = _staff(request, session, request_id)
        report = handler(session, report_id, f"staff:{user.id}")
        if report is None:
            raise HttpException(task_id=request_id, status_code=404, message="report not found")
        data = takedown.report_view(report)
    return utils.get_response(200, data)


__all__ = ["router"]
