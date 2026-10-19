"""Ad-fatigue HTTP surface (same scope rules as Settings > Integrations).

    GET  /ad-fatigue               per-creative fatigue (?ad_account_id, ?days, ?workspace_id, ?brand_space_id)
    POST /ad-fatigue/variations    "Make variations": a pending Brand Agent batch (approval needed)
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session
from app.domains._http import Call
from app.domains.ad_fatigue import service
from app.domains.brand_agent.gate import GateError
from app.domains.brand_agent.spaces import SpaceError
from app.domains.integrations.errors import IntegrationError
from app.domains.integrations.scope import resolve
from app.utils import utils

router = new_router()
_ERRORS = (IntegrationError, GateError, SpaceError)


class VariationsBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ad_account_id: str = Field(..., min_length=1, max_length=32)
    entity_id: str = Field(..., min_length=1, max_length=160)
    media: Literal["video", "image"] = "video"
    space_id: Optional[str] = Field(default=None, max_length=32)
    workspace_id: Optional[str] = Field(default=None, max_length=32)


@router.get("/ad-fatigue", summary="Fatigue per creative: frequency, CTR decay, CPA drift and a 0-100 score")
def fatigue_report(request: Request, ad_account_id: str = Query(default="", max_length=32),
                   days: int = Query(default=14, ge=7, le=60), workspace_id: str = Query(default="", max_length=32),
                   brand_space_id: str = Query(default="", max_length=32)):
    with Call(request, _ERRORS, "fatigue:read", get_session) as (session, user_id):
        scope = resolve(session, user_id, workspace_id=workspace_id or None, brand_space_id=brand_space_id or None)
        return utils.get_response(200, service.report(session, scope, ad_account_id=ad_account_id or None,
                                                      days=days))


@router.post("/ad-fatigue/variations", summary="Make variations of a tired creative (queued for approval)")
def make_variations(request: Request, body: VariationsBody):
    with Call(request, _ERRORS, "fatigue:write", get_session, limit=120) as (session, user_id):
        scope = resolve(session, user_id, workspace_id=body.workspace_id)
        return utils.get_response(200, service.make_variations(
            session, scope, ad_account_id=body.ad_account_id, entity_id=body.entity_id, space_id=body.space_id,
            media=body.media))


__all__ = ["router"]
