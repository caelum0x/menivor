"""HTTP surface for Launch Kit (Menivor Growth phase 3, owner-scoped first-100-users tooling).

    GET    /launch-kit/platforms                 curated launch directories + this product's state
    POST   /launch-kit/platforms/status           record what was actually submitted (human-reported)
    POST   /launch-kit/pain-points/search          Reddit pain-point search + drafted replies
    GET    /launch-kit/pain-points/drafts          saved drafts (?product_name, ?status)
    POST   /launch-kit/pain-points/drafts/{id}     approve/dismiss a draft (never "posted")
    GET    /launch-kit/backlinks                   competitor backlinks (?domain, ?allow_live)
    GET    /launch-kit/checklist                   10-step playbook checklist for one product
    POST   /launch-kit/checklist/step               mark one playbook step done/pending

Nothing in this router submits to a launch directory, posts to Reddit, spends backlink
credits by default, or performs any other external account action; see
app.domains.launch_kit.service's module docstring.
"""

from __future__ import annotations

from fastapi import Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session
from app.domains._http import Call
from app.domains.launch_kit import models as _models  # noqa: F401  (registers tables)
from app.domains.launch_kit import service
from app.utils import utils

router = new_router()
_ERRORS = (service.LaunchKitError,)

#: Tests swap in a recording transport (mirrors competitors/router.py's TRANSPORT).
TRANSPORT = None


def _id():
    return Path(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")


def _call(request: Request, key: str = "", limit: int = 120) -> Call:
    return Call(request, _ERRORS, f"launch_kit:{key}" if key else "launch_kit", get_session, limit=limit)


class PlatformStatusBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    product_name: str = Field(..., min_length=1, max_length=200)
    platform_id: str = Field(..., min_length=1, max_length=64)
    status: str = Field(..., pattern=r"^(not_started|submitted|live)$")
    note: str = Field(default="", max_length=500)


class PainPointSearchBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query: str = Field(..., min_length=1, max_length=300)
    subreddits: list[str] = Field(default_factory=list, max_length=10)
    product_name: str = Field(default="", max_length=200)
    limit: int = Field(default=10, ge=1, le=25)


class DraftStatusBody(BaseModel):
    status: str = Field(..., pattern=r"^(drafted|approved|dismissed)$")


class StepStatusBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    product_name: str = Field(..., min_length=1, max_length=200)
    step_key: str = Field(..., min_length=1, max_length=64)
    status: str = Field(..., pattern=r"^(pending|done)$")
    note: str = Field(default="", max_length=500)


@router.get("/launch-kit/platforms", summary="Curated launch directories + this product's submission state")
def list_platforms(request: Request, product_name: str = Query(default="", max_length=200),
                   category: str = Query(default="", max_length=32)):
    with _call(request) as (session, user_id):
        return utils.get_response(200, service.list_launch_platforms(
            session, user_id, product_name=product_name or None, product_category=category or None))


@router.post("/launch-kit/platforms/status", summary="Record what you actually submitted on a directory")
def set_platform_status(request: Request, body: PlatformStatusBody):
    with _call(request, "write") as (session, user_id):
        return utils.get_response(200, service.set_platform_status(
            session, user_id, product_name=body.product_name, platform_id=body.platform_id,
            status=body.status, note=body.note))


@router.post("/launch-kit/pain-points/search", summary="Reddit pain-point threads + a drafted reply (never posted)")
def search_pain_points(request: Request, body: PainPointSearchBody):
    with _call(request, "search", limit=30) as (session, user_id):
        return utils.get_response(200, service.find_pain_point_threads(
            session, user_id, query=body.query, subreddits=body.subreddits or None,
            product_name=body.product_name, limit=body.limit, transport=TRANSPORT))


@router.get("/launch-kit/pain-points/drafts", summary="Saved pain-point reply drafts")
def list_pain_point_drafts(request: Request, status: str = Query(default="", pattern=r"^(|drafted|approved|dismissed)$"),
                           product_name: str = Query(default="", max_length=200)):
    with _call(request) as (session, user_id):
        return utils.get_response(200, {"drafts": service.list_pain_point_drafts(
            session, user_id, status=status or None, product_name=product_name or None)})


@router.post("/launch-kit/pain-points/drafts/{draft_id}", summary="Approve or dismiss a drafted reply")
def set_draft_status(request: Request, body: DraftStatusBody, draft_id: str = _id()):
    with _call(request, "write") as (session, user_id):
        return utils.get_response(200, service.set_pain_point_draft_status(session, user_id, draft_id, body.status))


@router.get("/launch-kit/backlinks", summary="Competitor backlinks (free fallback unless allow_live is set)")
def backlinks(request: Request, domain: str = Query(..., min_length=3, max_length=255),
             allow_live: bool = Query(default=False)):
    with _call(request) as (_session, _user_id):
        return utils.get_response(200, service.find_competitor_backlinks(domain, transport=TRANSPORT,
                                                                          allow_live=allow_live))


@router.get("/launch-kit/checklist", summary="10-step distribution playbook checklist for one product")
def checklist(request: Request, product_name: str = Query(..., min_length=1, max_length=200)):
    with _call(request) as (session, user_id):
        return utils.get_response(200, service.get_launch_checklist(session, user_id, product_name=product_name))


@router.post("/launch-kit/checklist/step", summary="Mark one playbook step done/pending")
def mark_step(request: Request, body: StepStatusBody):
    with _call(request, "write") as (session, user_id):
        return utils.get_response(200, service.mark_playbook_step(
            session, user_id, product_name=body.product_name, step_key=body.step_key, status=body.status,
            note=body.note))


__all__ = ["router"]
