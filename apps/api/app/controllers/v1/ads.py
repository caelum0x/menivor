"""Paid ads HTTP adapter — launch Ad Studio variants on Meta / TikTok.

* ``GET    /ads/status``                                  gate: which platforms are enabled (public-safe)
* ``GET    /ads/connections/{platform}``                  connection + selectable ad accounts / identities
* ``POST   /ads/connections/{platform}/start``            OAuth authorize URL (signed state)
* ``POST   /ads/connections/{platform}/callback``         exchange code, store encrypted token
* ``PUT    /ads/connections/{platform}/account``          choose ad account + page / identity
* ``DELETE /ads/connections/{platform}``                  disconnect
* ``GET    /ads/campaigns``                               caller's campaigns with totals
* ``POST   /ads/campaigns``                               launch from Ad Studio variants
* ``GET    /ads/campaigns/{key}``                         campaign + per-creative report
* ``POST   /ads/campaigns/{key}/sync``                    advance processing ads, pull stats
* ``GET    /ads/campaigns/{key}/allocation``              preview the next Thompson split
* ``POST   /ads/campaigns/{key}/optimize``                apply the Thompson split now
* ``POST   /ads/campaigns/{key}/start`` | ``/pause``      campaign on / off on the platform
* ``POST   /ads/campaigns/{key}/archive``                 pause on the platform and archive

Every route but ``/ads/status`` is authenticated and owner-scoped. With the
platform app keys absent every mutating route answers 503 "Ads not enabled".
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import Path, Request
from pydantic import BaseModel, ConfigDict, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session, require_database, resolve_principal
from app.domains.ads import config, optimizer, reporting, service, store
from app.domains.ads.platforms import Audience
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

router = new_router()

_PLATFORM = Path(..., pattern="^(meta|tiktok)$")
_KEY = Path(..., pattern="^[a-f0-9]{16}$")


class CallbackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1, max_length=2048)
    state: str = Field(..., min_length=1, max_length=1024)


class AccountBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    identity_id: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9_\-]*$")
    identity_name: str = Field(default="", max_length=40)
    currency: str = Field(default="", max_length=3)


class AudienceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    countries: list[str] = Field(default_factory=lambda: ["US"], min_length=1, max_length=25)
    age_min: int = Field(default=18, ge=18, le=65)
    age_max: int = Field(default=65, ge=18, le=65)
    gender: str = Field(default="all", pattern="^(all|male|female)$")


class LaunchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., min_length=1, max_length=32)
    platform: str = Field(..., pattern="^(meta|tiktok)$")
    variant_ids: list[str] = Field(..., min_length=1, max_length=service.MAX_CREATIVES)
    daily_budget_minor: int = Field(..., ge=1, le=service.MAX_DAILY_BUDGET_MINOR)
    audience: AudienceBody = Field(default_factory=AudienceBody)
    name: str = Field(default="", max_length=200)
    landing_url: str = Field(default="", max_length=2048)
    primary_text: str = Field(default="", max_length=2000)
    headline: str = Field(default="", max_length=255)
    cta: str = Field(default="SHOP_NOW", max_length=20)
    optimize_for: str = Field(default="ctr", pattern="^(ctr|leads)$")
    auto_optimize: bool = True
    start_now: bool = False


def _auth(session: Any, request: Request, request_id: str) -> str:
    return str(resolve_principal(request, session, request_id).id)


def _error(request_id: str, exc: service.AdsError) -> HttpException:
    return HttpException(task_id=request_id, status_code=exc.status_code, message=f"{request_id}: {exc.message}")


def _run(request: Request, fn: Callable[[Any, str], Any], *, bucket: str = "", limit: int = 60) -> Any:
    """Run ``fn(session, user_id)``; commit partial platform state even when it fails.

    A platform failure midway (e.g. a campaign created but one ad set rejected)
    has already created real objects on the ad account, so the recorded ids must
    be committed before the error is returned.
    """
    request_id = base.get_task_id(request)
    require_database(request_id)
    failure: service.AdsError | None = None
    result = None
    with get_session() as session:
        user_id = _auth(session, request, request_id)
        if bucket:
            enforce_rate_limit(request, f"ads:{bucket}:{user_id}", limit=limit, window_s=3600)
        try:
            result = fn(session, user_id)
        except service.AdsError as exc:
            failure = exc
    if failure is not None:
        raise _error(request_id, failure)
    return result


def _ok(data: Any) -> dict:
    return utils.get_response(200, data)


def _media(rows: list[tuple[Any, dict]]) -> dict[str, dict]:
    return {v.id: {"poster_url": item.get("poster_url") or None} for v, item in rows}


def _campaign(key: str, rows: list[tuple[Any, dict]]) -> dict:
    return reporting.campaign_view(key, rows, _media(rows))


# ------------------------------------------------------------------ gate
@router.get("/ads/status", summary="Which paid-ads platforms are enabled")
def ads_status():
    return _ok(config.status())


# ----------------------------------------------------------- connections
@router.get("/ads/connections/{platform}", summary="Ad-account connection state")
def get_connection(request: Request, platform: str = _PLATFORM):
    return _ok(_run(request, lambda s, u: service.connection_detail(s, u, platform)))


@router.post("/ads/connections/{platform}/start", summary="Start the ad-account OAuth connect")
def start_connect(request: Request, platform: str = _PLATFORM):
    return _ok(_run(request, lambda s, u: service.connect_url(u, platform), bucket="connect", limit=20))


@router.post("/ads/connections/{platform}/callback", summary="Finish the ad-account OAuth connect")
def finish_connect(request: Request, body: CallbackBody, platform: str = _PLATFORM):
    return _ok(_run(request, lambda s, u: service.finish_connect(s, u, platform, body.code, body.state),
                    bucket="connect", limit=20))


@router.put("/ads/connections/{platform}/account", summary="Choose the ad account and page / identity")
def choose_account(request: Request, body: AccountBody, platform: str = _PLATFORM):
    return _ok(_run(request, lambda s, u: service.choose_account(
        s, u, platform, body.account_id, body.identity_id, body.currency, body.identity_name), bucket="account", limit=30))


@router.delete("/ads/connections/{platform}", summary="Disconnect the ad account")
def disconnect(request: Request, platform: str = _PLATFORM):
    return _ok(_run(request, lambda s, u: service.disconnect(s, u, platform)))


# ------------------------------------------------------------- campaigns
@router.get("/ads/campaigns", summary="The caller's paid campaigns")
def list_campaigns(request: Request):
    def load(session: Any, user_id: str) -> dict:
        items = [reporting.campaign_summary(k, rows) for k, rows in store.campaigns(session, user_id).items()]
        return {"campaigns": items, "total": len(items), "gate": config.status()}

    return _ok(_run(request, load))


@router.post("/ads/campaigns", summary="Launch a campaign from Ad Studio variants")
def launch(request: Request, body: LaunchBody):
    req = service.LaunchRequest(
        project_id=body.project_id, platform=body.platform, variant_ids=tuple(dict.fromkeys(body.variant_ids)),
        daily_budget_minor=body.daily_budget_minor,
        audience=Audience(countries=tuple(c.strip().upper() for c in body.audience.countries if c.strip()),
                          age_min=body.audience.age_min, age_max=body.audience.age_max, gender=body.audience.gender),
        name=body.name, landing_url=body.landing_url, primary_text=body.primary_text, headline=body.headline,
        cta=body.cta, optimize_for=body.optimize_for, auto_optimize=body.auto_optimize, start_now=body.start_now,
    )

    def run(session: Any, user_id: str) -> dict:
        key, rows = service.launch(session, user_id, req)
        return _campaign(key, rows)

    return _ok(_run(request, run, bucket="launch", limit=10))


@router.get("/ads/campaigns/{key}", summary="Campaign report")
def get_campaign(request: Request, key: str = _KEY):
    def load(session: Any, user_id: str) -> dict:
        rows = store.campaign_rows(session, user_id, key)
        if not rows:
            raise service.AdsError(404, "Campaign not found.")
        return _campaign(key, rows)

    return _ok(_run(request, load))


@router.post("/ads/campaigns/{key}/sync", summary="Advance processing ads and pull spend / CTR / CPL")
def sync_campaign(request: Request, key: str = _KEY):
    return _ok(_run(request, lambda s, u: _campaign(key, optimizer.sync(s, u, key)), bucket="sync", limit=120))


@router.get("/ads/campaigns/{key}/allocation", summary="Preview the next Thompson budget split")
def preview_allocation(request: Request, key: str = _KEY):
    return _ok(_run(request, lambda s, u: optimizer.preview(s, u, key)))


@router.post("/ads/campaigns/{key}/optimize", summary="Apply the Thompson budget split now")
def optimize_campaign(request: Request, key: str = _KEY):
    return _ok(_run(request, lambda s, u: _campaign(key, optimizer.optimize(s, u, key)), bucket="optimize", limit=30))


@router.post("/ads/campaigns/{key}/start", summary="Turn the campaign on")
def start_campaign(request: Request, key: str = _KEY):
    return _ok(_run(request, lambda s, u: _campaign(key, service.set_status(s, u, key, True)), bucket="status", limit=60))


@router.post("/ads/campaigns/{key}/pause", summary="Turn the campaign off")
def pause_campaign(request: Request, key: str = _KEY):
    return _ok(_run(request, lambda s, u: _campaign(key, service.set_status(s, u, key, False)), bucket="status", limit=60))


@router.post("/ads/campaigns/{key}/archive", summary="Pause on the platform and archive")
def archive_campaign(request: Request, key: str = _KEY):
    return _ok(_run(request, lambda s, u: _campaign(key, service.archive(s, u, key)), bucket="status", limit=60))


__all__ = ["router"]
