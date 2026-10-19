"""Ad routes (MV14). 404 until OTT_ENABLED and OTT_ADS_LIVE.

* ``GET  /api/v1/ott/ads/vast/{title_id}``             the pre-roll for this play as VAST (or "no ad")
* ``GET  /api/v1/ott/ads/track/{ad_id}/{event}?t=&p=&x=``  our own tracking (signed per event, play and expiry)
* ``GET  /api/v1/ott/studio/ads``                      my ad rules and sponsor slots with counts
* ``PUT  /api/v1/ott/studio/ads/settings``             ads on free titles, on paid tiers, house ads
* ``POST /api/v1/ott/studio/ads``                      a sponsor slot made from one of my titles
* ``POST /api/v1/ott/studio/ads/{ad_id}/deactivate``   stop a sponsor slot
* ``POST /api/v1/admin/ott/ads/house``                 staff: a house ad made from one of our titles (ads flag)
"""

from __future__ import annotations

from datetime import datetime

from fastapi import Depends, Path, Query, Request, Response
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.domains.ott import flags
from app.domains.ott.feeds import api_base
from app.domains.ott.models import OttTitle
from app.domains.ott.service import ensure_channel
from app.domains.ott_commerce.models import OttAd
from app.domains.ott_viewers import session as viewer_session
from app.models.exception import HttpException
from app.utils import utils

from . import service, vast

router = new_router()
_ADS = [Depends(flags.require("ads"))]
NO_STORE = {"Cache-Control": "no-store, private"}
MEDIA_TTL_S = 600
#: QM verify: each VAST answer mints a fresh play id with signed tracking URLs, so an
#: unthrottled loop could add one impression per call. A viewer needs one per play.
VAST_LIMIT, VAST_WINDOW_S = 30, 60


class Settings(BaseModel):
    ads_on_free: bool | None = None
    ads_on_paid: bool | None = None
    house_ads: bool | None = None


class AdCreate(BaseModel):
    title_id: str = Field(..., max_length=32)
    name: str = Field(..., min_length=1, max_length=80)
    sponsor: str = Field("", max_length=80)
    click_url: str = Field("", max_length=500)
    starts_at: datetime | None = None
    ends_at: datetime | None = None


def media_url(title: OttTitle) -> str:
    from app.domains.ott_access import service as access

    return access.source_url(title)


@router.get("/ott/ads/vast/{title_id}", dependencies=_ADS, summary="The pre-roll for this play (VAST)")
def vast_for_title(request: Request, title_id: str = Path(..., max_length=32)):
    from app.domains.ott import catalog_public

    from app.services.ratelimit import enforce_rate_limit

    request_id = base.get_task_id(request)
    _require_db(request_id)
    enforce_rate_limit(request, "ott:ads-vast", VAST_LIMIT, VAST_WINDOW_S)
    with get_session() as session:
        title = session.get(OttTitle, title_id)
        if not catalog_public.watchable(session, title):
            return Response(content=vast.empty(), media_type="application/xml", headers=NO_STORE)
        account = viewer_session.from_request(session, request)
        viewer_id = account.id if account is not None and account.channel_id == title.channel_id else None
        ad = service.decide(session, title, viewer_account_id=viewer_id)
        if ad is None:
            body = vast.empty()
        else:
            body = vast.build(ad, media_url=media_url(session.get(OttTitle, ad.title_id)), api_base=api_base())
    return Response(content=body, media_type="application/xml", headers=NO_STORE)


@router.get("/ott/ads/track/{ad_id}/{event}", dependencies=_ADS, summary="Ad tracking (signed)")
def track(request: Request, ad_id: str = Path(..., max_length=32), event: str = Path(..., max_length=16),
          t: str = Query("", max_length=40), p: str = Query("", max_length=32), x: str = Query("", max_length=12)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        service.record(session, ad_id, event, t, p, x)
    return Response(status_code=204, headers=NO_STORE)


def _studio(request: Request, fn):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            return utils.get_response(200, fn(session, ensure_channel(session, str(user.id))))
        except service.AdError as exc:
            raise HttpException(task_id=request_id, status_code=exc.status_code, message=str(exc),
                                data={"code": exc.code}) from exc


@router.get("/ott/studio/ads", dependencies=_ADS, summary="My ad rules and sponsor slots")
def studio_ads(request: Request):
    return _studio(request, lambda s, ch: service.studio_view(s, ch.id))


@router.put("/ott/studio/ads/settings", dependencies=_ADS, summary="Ad rules for my channel")
def put_settings(request: Request, body: Settings):
    def _put(s, ch):
        service.update_settings(s, ch.id, body.model_dump(exclude_none=True))
        return service.studio_view(s, ch.id)

    return _studio(request, _put)


@router.post("/ott/studio/ads", dependencies=_ADS, summary="Add a sponsor slot")
def create_sponsor(request: Request, body: AdCreate):
    return _studio(request, lambda s, ch: service.ad_view(service.create_ad(s, channel=ch, body=body.model_dump())))


@router.post("/ott/studio/ads/{ad_id}/deactivate", dependencies=_ADS, summary="Stop a sponsor slot")
def deactivate(request: Request, ad_id: str = Path(..., max_length=32)):
    def _off(s, ch):
        ad = s.get(OttAd, ad_id)
        if ad is None or ad.channel_id != ch.id:
            raise service.AdError(404, "not_found", "ad not found")
        ad.active = False
        s.flush()
        return service.ad_view(ad)

    return _studio(request, _off)


@router.post("/admin/ott/ads/house", tags=["Admin"], dependencies=_ADS, summary="Create a house ad (staff)")
def create_house(request: Request, body: AdCreate):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        if not bool(getattr(user, "is_staff", False)):
            raise HttpException(task_id=request_id, status_code=403, message="staff access required")
        try:
            ad = service.create_ad(session, channel=None, body=body.model_dump())
        except service.AdError as exc:
            raise HttpException(task_id=request_id, status_code=exc.status_code, message=str(exc),
                                data={"code": exc.code}) from exc
        return utils.get_response(200, service.ad_view(ad))
