"""Channel sales routes (MV13). 404 until OTT_ENABLED and OTT_COMMERCE_LIVE.

Creator (signed in):
* ``GET  /api/v1/ott/studio/commerce``                        payment account state and offers
* ``POST /api/v1/ott/studio/commerce/connect``                Mint's connect link (no key field here)
* ``POST /api/v1/ott/studio/commerce/offers``                 subscription, purchase or rental
* ``POST /api/v1/ott/studio/commerce/offers/{id}/deactivate`` stop selling an offer
* ``GET  /api/v1/ott/studio/commerce/coupons``                my coupon codes (code and end date only)
* ``POST /api/v1/ott/studio/commerce/coupons``                a discount on my own processor (QM1.3)
* ``POST /api/v1/ott/studio/commerce/coupons/{code}/stop``    stop a code here and on my processor
* ``GET  /api/v1/ott/studio/commerce/sales``                  gross sales per title from grant events
Viewer:
* ``GET  /api/v1/ott/c/{handle}/offers``                      what the channel sells (public, cached)
* ``POST /api/v1/ott/viewers/{handle}/checkout``              a hosted checkout on the creator's processor
* ``GET  /api/v1/ott/viewers/{handle}/entitlements``          what I bought here
Mint:
* ``POST /api/v1/ott/webhooks/mint``                          entitlement.granted / entitlement.revoked

Checkout also needs ``OTT_VIEWER_TERMS_LIVE`` (viewer terms after the legal consult, MD16).
"""

from __future__ import annotations

import os

from fastapi import Depends, Path, Query, Request, Response
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.domains.ott import flags
from app.domains.ott.feeds import web_base
from app.domains.ott.models import STATUS_PUBLISHED, OttChannel
from app.domains.ott.service import ensure_channel
from app.domains.ott_viewers import service as viewers, session as viewer_session
from app.models.exception import HttpException
from app.utils import utils

from app.domains.ott_analytics import service as analytics

from . import entitlements, products, webhooks
from .models import OttOffer
from .processor import MintDiscounts

router = new_router()
_LIVE = [Depends(flags.require("commerce"))]
TERMS_ENV = "OTT_VIEWER_TERMS_LIVE"
PUBLIC_CACHE = "public, max-age=15, s-maxage=30"
NO_STORE = {"Cache-Control": "no-store, private"}


class OfferCreate(BaseModel):
    kind: str = Field(..., max_length=8)
    name: str = Field(..., min_length=1, max_length=120)
    price_cents: int = Field(..., ge=50, le=100_000_000)
    currency: str = Field("USD", min_length=3, max_length=3)
    title_id: str | None = Field(None, max_length=32)
    interval: str | None = Field(None, max_length=8)
    rental_hours: int | None = Field(None, ge=1, le=720)


class Checkout(BaseModel):
    offer_id: str = Field(..., max_length=32)
    coupon_code: str | None = Field(None, max_length=16)


class CouponCreate(BaseModel):
    code: str = Field(..., min_length=3, max_length=16)
    kind: str = Field(..., max_length=8)
    percent: float | None = Field(None, gt=0, le=100)
    amount_cents: int | None = Field(None, ge=1, le=100_000_000)
    # Omitted: the currency of the channel's prices (products.coupon_spec).
    currency: str | None = Field(None, min_length=3, max_length=3)
    expires_at: str = Field(..., max_length=40)


def _http(exc: Exception, request_id: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=getattr(exc, "status_code", 400), message=str(exc),
                         data={"code": getattr(exc, "code", "error")})


def mint() -> products.MintSellers:
    return products.MintSellers()


def processor():
    """The creator's processor for discounts: Mint's seller route on the connected account."""
    return MintDiscounts(mint())


def _studio(request: Request, fn):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            return utils.get_response(200, fn(session, ensure_channel(session, str(user.id))))
        except (products.CommerceError, viewers.ViewerError) as exc:
            raise _http(exc, request_id) from exc


@router.get("/ott/studio/commerce", dependencies=_LIVE, summary="My payment account and offers")
def get_commerce(request: Request):
    def _view(session, channel):
        try:
            seller = mint().seller(products.seller_id(channel.id))
            account = {"connected": bool(seller.get("connected")), "provider": seller.get("provider"),
                       "mode": seller.get("mode")}
        except products.CommerceError as exc:
            account = {"connected": False, "error": str(exc)}
        return {"account": account,
                "offers": [products.offer_view(o) for o in products.offers_for(session, channel.id,
                                                                                 active_only=False)]}

    return _studio(request, _view)


@router.post("/ott/studio/commerce/connect", dependencies=_LIVE, summary="Connect my own payment account")
def connect(request: Request):
    return _studio(request, lambda s, ch: {"connect_url": mint().connect(
        products.seller_id(ch.id), f"{web_base()}/studio-ott?connected=1").get("connect_url")})


@router.post("/ott/studio/commerce/offers", dependencies=_LIVE, summary="Sell a subscription, purchase or rental")
def create_offer(request: Request, body: OfferCreate):
    return _studio(request, lambda s, ch: products.offer_view(
        products.create_offer(s, ch, body.model_dump(exclude_none=True), mint=mint())))


@router.post("/ott/studio/commerce/offers/{offer_id}/deactivate", dependencies=_LIVE, summary="Stop selling")
def deactivate(request: Request, offer_id: str = Path(..., max_length=32)):
    def _off(session, channel):
        offer = session.get(OttOffer, offer_id)
        if offer is None or offer.channel_id != channel.id:
            raise products.CommerceError(404, "not_found", "offer not found")
        offer.active = False
        session.flush()
        return products.offer_view(offer)

    return _studio(request, _off)


@router.get("/ott/studio/commerce/coupons", dependencies=_LIVE, summary="My coupon codes")
def list_coupons(request: Request):
    return _studio(request, lambda s, ch: {"coupons": [products.coupon_view(c)
                                                       for c in products.coupons_for(s, ch.id)]})


@router.post("/ott/studio/commerce/coupons", dependencies=_LIVE, summary="A coupon on my own payment account")
def create_coupon(request: Request, body: CouponCreate):
    return _studio(request, lambda s, ch: products.coupon_view(
        products.create_coupon(s, ch, body.model_dump(exclude_none=True), processor=processor())))


@router.post("/ott/studio/commerce/coupons/{code}/stop", dependencies=_LIVE, summary="Stop a coupon here")
def stop_coupon(request: Request, code: str = Path(..., max_length=16)):
    return _studio(request, lambda s, ch: products.coupon_view(
        products.stop_coupon(s, ch, code, processor=processor())))


@router.get("/ott/studio/commerce/sales", dependencies=_LIVE, summary="Gross sales per title")
def sales(request: Request, days: int = Query(30, ge=1, le=90)):
    def _sales(session, channel):
        rows = analytics.sales_by_title(session, channel, days=days)
        return {"days": days, "sales": rows, "sales_totals": analytics.sales_totals(rows)}

    return _studio(request, _sales)


@router.get("/ott/c/{handle}/offers", dependencies=_LIVE, summary="What this channel sells (public)")
def public_offers(request: Request, response: Response, handle: str = Path(..., max_length=40)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        try:
            channel = viewers.published_channel(session, handle)
        except viewers.ViewerError as exc:
            raise _http(exc, request_id) from exc
        offers = [products.offer_view(o) for o in products.offers_for(session, channel.id)]
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return utils.get_response(200, {"offers": offers, "checkout_open": _terms_live()})


def _terms_live() -> bool:
    return (os.getenv(TERMS_ENV) or "").strip().lower() in {"1", "true", "yes", "on"}


@router.post("/ott/viewers/{handle}/checkout", dependencies=_LIVE, summary="Buy on the creator's own checkout")
def checkout(request: Request, body: Checkout, response: Response, handle: str = Path(..., max_length=40)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    if not _terms_live():
        raise HttpException(task_id=request_id, status_code=503, message="Buying on channels opens soon.",
                            data={"code": "terms_pending"})
    with get_session() as session:
        try:
            viewer = viewers.resolve(session, request.headers.get(viewer_session.HEADER) or "", handle)
            offer = session.get(OttOffer, body.offer_id)
            if offer is None or offer.channel_id != viewer.channel_id or not offer.active:
                raise products.CommerceError(404, "not_found", "offer not found")
            channel = session.get(OttChannel, viewer.channel_id)
            if channel is None or channel.status != STATUS_PUBLISHED:
                raise products.CommerceError(404, "not_found", "channel not found")
            code = products.usable_coupon(session, channel.id, body.coupon_code) if body.coupon_code else None
            back = f"{web_base()}/c/{channel.handle}"
            target = f"{back}/{offer.title_id}" if offer.title_id else back
            session_view = mint().checkout(products.seller_id(channel.id), sku=offer.sku, buyer_ref=viewer.id,
                                           success_url=f"{target}?purchase=done", cancel_url=target,
                                           discount_code=code)
        except (products.CommerceError, viewers.ViewerError) as exc:
            raise _http(exc, request_id) from exc
    response.headers.update(NO_STORE)
    return utils.get_response(200, {"url": session_view.get("url")})


@router.get("/ott/viewers/{handle}/entitlements", dependencies=_LIVE, summary="What I bought on this channel")
def my_entitlements(request: Request, response: Response, handle: str = Path(..., max_length=40)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        try:
            viewer = viewers.resolve(session, request.headers.get(viewer_session.HEADER) or "", handle)
        except viewers.ViewerError as exc:
            raise _http(exc, request_id) from exc
        items = entitlements.viewer_entitlements(session, viewer.id)
    response.headers.update(NO_STORE)
    return utils.get_response(200, {"items": items})


@router.post("/ott/webhooks/mint", dependencies=_LIVE, summary="Mint entitlement events (signed)")
async def mint_webhook(request: Request):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    payload = await request.body()
    try:
        body = webhooks.verify(payload, dict(request.headers))
        with get_session() as session:
            result = webhooks.handle(session, body)
    except webhooks.WebhookRefused as exc:
        raise HttpException(task_id=request_id, status_code=exc.status_code, message=str(exc),
                            data={"code": "refused"}) from exc
    return utils.get_response(200, result)
