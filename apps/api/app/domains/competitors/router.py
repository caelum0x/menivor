"""Competitor tracker HTTP surface (owner-scoped). Official ad-library APIs only.

    GET    /competitors                       tracked brands + source connection state + alert count
    POST   /competitors                       track a brand (page ids / advertiser ids / search words)
    DELETE /competitors/{brand_id}
    POST   /competitors/{brand_id}/refresh    pull the official libraries now
    GET    /competitors/ads                   ads ranked by longevity (?brand_id, ?tier, ?only_new)
    GET    /competitors/alerts                new ads since the last refresh
    POST   /competitors/alerts/dismiss        mark alerts seen (all, or ``ad_ids``)
    POST   /competitors/ads/{ad_id}/clone     "Clone this": a clone brief for Ad Clone + an Inspiration
"""

from __future__ import annotations

from typing import Optional

from fastapi import Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session
from app.domains._http import Call
from app.domains.competitors import models as _models  # noqa: F401  (registers tables)
from app.domains.competitors import service
from app.utils import utils

router = new_router()
_ERRORS = (service.CompetitorError,)


def _id():
    return Path(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")

TRANSPORT = None  # tests swap in a recording transport


class BrandBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., min_length=1, max_length=200)
    meta_page_ids: list[str] = Field(default_factory=list, max_length=10)
    tiktok_advertiser_ids: list[str] = Field(default_factory=list, max_length=10)
    search_terms: str = Field(default="", max_length=100)
    countries: list[str] = Field(default_factory=list, max_length=20)
    space_id: Optional[str] = Field(default=None, max_length=32)


class DismissBody(BaseModel):
    ad_ids: list[str] = Field(default_factory=list, max_length=200)


class CloneBody(BaseModel):
    space_id: Optional[str] = Field(default=None, max_length=32)


def _call(request: Request, key: str = "") -> Call:
    return Call(request, _ERRORS, f"competitors:{key}" if key else "", get_session)


@router.get("/competitors", summary="Tracked competitor brands and ad-library connection state")
def list_brands(request: Request):
    with _call(request) as (session, user_id):
        return utils.get_response(200, {"brands": service.list_brands(session, user_id),
                                        "sources": service.sources_status(),
                                        "alerts": service.alerts(session, user_id)["count"]})


@router.post("/competitors", summary="Track a competitor brand")
def add_brand(request: Request, body: BrandBody):
    with _call(request, "write") as (session, user_id):
        return utils.get_response(200, {"brand": service.add_brand(
            session, user_id, name=body.name, meta_page_ids=body.meta_page_ids,
            tiktok_advertiser_ids=body.tiktok_advertiser_ids, search_terms=body.search_terms,
            countries=body.countries, space_id=body.space_id)})


@router.delete("/competitors/{brand_id}", summary="Stop tracking a brand")
def delete_brand(request: Request, brand_id: str = _id()):
    with _call(request, "write") as (session, user_id):
        service.delete_brand(session, user_id, brand_id)
        return utils.get_response(200, {"deleted": brand_id})


@router.post("/competitors/{brand_id}/refresh", summary="Pull the official ad libraries for this brand now")
def refresh(request: Request, brand_id: str = _id()):
    with Call(request, _ERRORS, "competitors:refresh", get_session, limit=60) as (session, user_id):
        return utils.get_response(200, service.refresh(session, user_id, brand_id, transport=TRANSPORT))


@router.get("/competitors/ads", summary="Competitor ads ranked by longevity (the winner signal)")
def list_ads(request: Request, brand_id: str = Query(default="", max_length=32),
             tier: str = Query(default="", pattern=r"^(|winner|proven|testing|unknown)$"),
             only_new: bool = Query(default=False)):
    with _call(request) as (session, user_id):
        return utils.get_response(200, {"ads": service.list_ads(session, user_id, brand_id=brand_id or None,
                                                                tier=tier or None, only_new=only_new)})


@router.get("/competitors/alerts", summary="New competitor ads since the last refresh")
def alerts(request: Request):
    with _call(request) as (session, user_id):
        return utils.get_response(200, service.alerts(session, user_id))


@router.post("/competitors/alerts/dismiss", summary="Mark new-ad alerts as seen")
def dismiss(request: Request, body: DismissBody):
    with _call(request, "write") as (session, user_id):
        return utils.get_response(200, {"dismissed": service.dismiss_alerts(session, user_id, body.ad_ids)})


@router.post("/competitors/ads/{ad_id}/clone", summary="Clone this: send the ad into Ad Clone (brief, $0)")
def clone(request: Request, body: Optional[CloneBody] = None, ad_id: str = _id()):
    with _call(request, "clone") as (session, user_id):
        return utils.get_response(200, service.clone_brief(session, user_id, ad_id,
                                                           space_id=(body.space_id if body else None)))


__all__ = ["router"]
