"""Cross-network allocator HTTP adapter.

* ``GET  /ads/allocator/report``                         cost per result per network + latest proposal
* ``GET  /ads/allocator/proposals``                      proposal history
* ``POST /ads/allocator/proposals``                      build (or rebuild) today's proposal
* ``GET  /ads/allocator/proposals/{id}``                 one proposal
* ``POST /ads/allocator/proposals/{id}/decision``        approve (optionally edited) or reject
* ``POST /ads/allocator/proposals/{id}/apply``           apply a proposal approved in the approvals feed

Every route is authenticated and owner-scoped. Approving moves money on the
ad platforms; with the platform app keys absent the apply step records the
"Ads not enabled" reason per network instead.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session, require_database, resolve_principal
from app.domains.ads.allocator import service
from app.domains.ads.allocator.stats import MANUAL_NETWORKS, ManualNetwork
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

router = new_router()

_ID = Path(..., pattern="^[a-f0-9]{32}$")
_MANUAL_PATTERN = "^(" + "|".join(sorted(MANUAL_NETWORKS)) + ")$"


class ManualNetworkBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    network: str = Field(..., pattern=_MANUAL_PATTERN)
    spend_minor: int = Field(..., ge=0, le=10_000_000_000)
    results: int = Field(..., ge=0, le=1_000_000_000)
    current_daily_minor: int = Field(default=0, ge=0, le=service.MAX_TOTAL_DAILY_MINOR)
    impressions: int = Field(default=0, ge=0, le=10_000_000_000)


class ProposeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_daily_minor: Optional[int] = Field(default=None, ge=1, le=service.MAX_TOTAL_DAILY_MINOR)
    # ``None`` reuses the manual rows of the last proposal; ``[]`` clears them.
    manual_networks: Optional[list[ManualNetworkBody]] = Field(default=None, max_length=4)


class DecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(..., pattern="^(approve|reject)$")
    note: str = Field(default="", max_length=2000)
    split: Optional[dict[str, float]] = Field(default=None, max_length=6)


def _run(request: Request, fn: Callable[[Any, str], Any], *, bucket: str = "", limit: int = 60) -> Any:
    request_id = base.get_task_id(request)
    require_database(request_id)
    failure: service.AllocatorError | None = None
    result = None
    with get_session() as session:
        user_id = str(resolve_principal(request, session, request_id).id)
        if bucket:
            enforce_rate_limit(request, f"ads:allocator:{bucket}:{user_id}", limit=limit, window_s=3600)
        try:
            result = fn(session, user_id)
        except service.AdsError as exc:
            failure = exc  # platform objects already changed must still be committed
    if failure is not None:
        raise HttpException(task_id=request_id, status_code=failure.status_code,
                            message=f"{request_id}: {failure.message}")
    return result


@router.get("/ads/allocator/report", summary="Which ad network pays off")
def allocator_report(request: Request):
    return utils.get_response(200, _run(request, service.report))


@router.get("/ads/allocator/proposals", summary="Budget split proposals")
def list_proposals(request: Request, limit: int = Query(30, ge=1, le=90)):
    return utils.get_response(200, {"proposals": _run(request, lambda s, u: service.list_proposals(s, u, limit))})


@router.post("/ads/allocator/proposals", summary="Propose today's cross-network budget split")
def create_proposal(request: Request, body: ProposeBody):
    manual = None if body.manual_networks is None else [ManualNetwork(**m.model_dump()) for m in body.manual_networks]
    if manual is not None and len({m.network for m in manual}) != len(manual):
        raise HttpException(task_id=base.get_task_id(request), status_code=422, message="Each network can appear once.")
    return utils.get_response(200, _run(
        request, lambda s, u: service.propose(s, u, total_daily_minor=body.total_daily_minor, manual=manual),
        bucket="propose", limit=30))


@router.get("/ads/allocator/proposals/{proposal_id}", summary="One budget split proposal")
def get_proposal(request: Request, proposal_id: str = _ID):
    return utils.get_response(200, _run(request, lambda s, u: service.proposal_view(service.get_owned(s, u, proposal_id))))


@router.post("/ads/allocator/proposals/{proposal_id}/decision", summary="Approve or reject a budget split")
def decide(request: Request, body: DecisionBody, proposal_id: str = _ID):
    return utils.get_response(200, _run(
        request, lambda s, u: service.decide(s, u, proposal_id, approve=body.decision == "approve", note=body.note,
                                             split=body.split),
        bucket="decide", limit=30))


@router.post("/ads/allocator/proposals/{proposal_id}/apply", summary="Apply an approved budget split")
def apply_approved(request: Request, proposal_id: str = _ID):
    return utils.get_response(200, _run(request, lambda s, u: service.apply_approved(s, u, proposal_id),
                                        bucket="apply", limit=30))


__all__ = ["router"]
