"""Review queue HTTP surface (owner-scoped, rate limited).

    GET  /review/queue                 pending creatives + reason chips + stats
    POST /review/{item_id}/decide      approve | reject | regenerate (+ reason chip)
"""

from __future__ import annotations

from typing import Literal

from fastapi import Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session, require_database, resolve_principal
from app.domains.creative_review import service
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

router = new_router()
_ID = Path(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
_WINDOW_S = 3600


def build_deps():
    from app.domains.brand_agent.router import build_deps as agent_deps

    return agent_deps()


class DecideBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    decision: Literal["approve", "reject", "regenerate"]
    reason: str = Field(default="", max_length=32)
    note: str = Field(default="", max_length=500)
    #: Regenerate only: the user pressed the button that shows the credit price (that is the approval).
    confirm_spend: bool = False


def _caller(request: Request, request_id: str) -> str:
    require_database(request_id)
    with get_session() as session:
        return str(resolve_principal(request, session, request_id).id)


def _fail(request_id: str, exc: service.ReviewError) -> HttpException:
    return HttpException(task_id=request_id, status_code=exc.status_code, message=f"{request_id}: {exc.message}")


@router.get("/review/queue", summary="Creatives waiting for a swipe: approve, reject or regenerate")
def review_queue(request: Request, space_id: str = Query(default="", max_length=32),
                 limit: int = Query(default=30, ge=1, le=100)):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    enforce_rate_limit(request, f"review:list:{user_id}", limit=600, window_s=_WINDOW_S)
    try:
        return utils.get_response(200, service.queue(user_id, space_id=space_id or None, limit=limit))
    except service.ReviewError as exc:
        raise _fail(request_id, exc) from exc


@router.post("/review/{item_id}/decide", summary="Approve, reject or regenerate one creative with a reason chip")
def review_decide(request: Request, body: DecideBody, item_id: str = _ID):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    enforce_rate_limit(request, f"review:decide:{user_id}", limit=600, window_s=_WINDOW_S)
    try:
        out = service.decide(user_id, item_id, body.decision, reason=body.reason, note=body.note,
                             confirm_spend=body.confirm_spend, deps_factory=build_deps)
    except service.ReviewError as exc:
        raise _fail(request_id, exc) from exc
    return utils.get_response(200, out)


__all__ = ["router"]
