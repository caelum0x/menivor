"""Credit-pack v1 routes (catalog, card checkout, store redemption).

Endpoints (all under ``/api/v1``, MPT envelope via ``utils.get_response``):

* ``GET  /credit-packs[?currency=TRY]`` -- public pack catalog with per-rail
  availability; ``currency=TRY`` adds an approximate display price from the
  configured rate (checkout still charges USD).
* ``POST /credit-packs/{pack_id}/checkout`` -- authenticated.
    - ``{"channel": "web"}`` (default): opens a Creem hosted checkout and returns
      ``{checkout_url}``; ``503`` when Creem/pack product is not configured.
      Credits are granted only by the verified Creem webhook.
    - ``{"channel": "store", "transaction_id", "product_id"?}``: verifies the
      App Store / Play transaction through RevenueCat and grants the pack once.
* ``GET  /billing/store/credit-packs`` and
  ``POST /billing/store/credit-packs/redeem`` -- the store-rail contract the
  mobile app ships with (``src/shared/billing/store-credits.ts``). Same logic.

Store listing answers ``503`` when the rail is not live (no RevenueCat server
key, or checkout not open for this launch phase) so the app hides the buy UI
and nobody can pay for credits the server cannot grant. Redemption is never
launch-gated: a buyer who already paid must always be credited.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import Path, Query, Request
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.auth import resolve_principal
from app.core.launch.policy import checkout_enabled, require_checkout_enabled
from app.models.db.base import get_session
from app.models.exception import HttpException
from app.utils import utils

router = new_router()


def _packs():
    """The credit-pack domain module, imported lazily.

    ``app.domains.billing`` composes this controller into its router at package
    import, so a module-level import here would be circular whenever this file
    is imported first (e.g. directly by a test).
    """
    from app.domains.billing import credit_packs

    return credit_packs

_PACK_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,39}$"


class CreditPackCheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    channel: Literal["web", "store"] = "web"
    transaction_id: Optional[str] = Field(default=None, max_length=200)
    product_id: Optional[str] = Field(default=None, max_length=200)
    platform: Optional[str] = Field(default=None, max_length=20)


class StoreRedeemRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    product_id: str = Field(min_length=1, max_length=200)
    transaction_id: str = Field(min_length=1, max_length=200)
    purchased_at: Optional[str] = Field(default=None, max_length=64)
    platform: Optional[str] = Field(default=None, max_length=20)


def _raise(request_id: str, exc: Any) -> None:
    raise HttpException(
        task_id=request_id,
        status_code=exc.status_code,
        message=f"{request_id}: {exc}",
    ) from exc


def _caller(request: Request, request_id: str) -> tuple[str, str]:
    """Resolve the caller and release the DB session before provider calls."""
    with get_session() as session:
        user = resolve_principal(request, session, request_id)
        return str(user.id), str(getattr(user, "email", "") or "")


def _redeem(
    request: Request,
    request_id: str,
    *,
    product_id: str,
    transaction_id: str,
    expected_pack: Any = None,
) -> dict[str, Any]:
    packs = _packs()
    user_id, _email = _caller(request, request_id)
    try:
        return packs.redeem_store_purchase(
            user_id=user_id,
            product_id=product_id,
            transaction_id=transaction_id,
            expected_pack=expected_pack,
        )
    except packs.CreditPackError as exc:
        if exc.status_code >= 500:
            logger.error(f"store redemption failed, request_id: {request_id}: {exc}")
        _raise(request_id, exc)
    raise AssertionError("unreachable")  # pragma: no cover


@router.get("/credit-packs", summary="List one-time credit packs")
def list_credit_packs(
    request: Request,
    currency: Optional[str] = Query(default=None, max_length=8),
):
    packs = _packs()
    request_id = base.get_task_id(request)
    live = checkout_enabled()
    rows = [packs.serialize_pack(pack, currency) for pack in packs.list_packs()]
    if not live:
        # Before the public launch gate opens nothing is purchasable; say so
        # instead of advertising rails that would 403 at checkout.
        rows = [
            {**row, "web_checkout_available": False, "store_purchase_available": False}
            for row in rows
        ]
    rate = packs.try_per_usd()
    return utils.get_response(
        200,
        {
            "packs": rows,
            "charge_currency": packs.CHARGE_CURRENCY,
            "checkout_open": live,
            "display_rates": {"TRY": rate} if rate is not None else {},
        },
    )


@router.post("/credit-packs/{pack_id}/checkout", summary="Buy a credit pack")
def checkout_credit_pack(
    request: Request,
    body: CreditPackCheckoutRequest,
    pack_id: str = Path(..., pattern=_PACK_ID_PATTERN),
):
    packs = _packs()
    request_id = base.get_task_id(request)
    try:
        pack = packs.get_pack(pack_id)
    except packs.CreditPackError as exc:
        _raise(request_id, exc)

    if body.channel == "store":
        transaction_id = (body.transaction_id or "").strip()
        if not transaction_id:
            raise HttpException(
                task_id=request_id,
                status_code=422,
                message=f"{request_id}: transaction_id is required for store purchases",
            )
        result = _redeem(
            request,
            request_id,
            product_id=(body.product_id or pack.store_product_id).strip(),
            transaction_id=transaction_id,
            expected_pack=pack,
        )
        return utils.get_response(200, result)

    require_checkout_enabled(request_id)
    if not packs.web_rail_ready(pack):
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: card checkout for credit packs is not configured",
        )
    user_id, email = _caller(request, request_id)
    try:
        result = packs.create_web_checkout(pack, user_id, email)
    except packs.CreditPackError as exc:
        _raise(request_id, exc)
    return utils.get_response(200, result)


@router.get("/billing/store/credit-packs", summary="Store-billed credit packs")
def list_store_credit_packs(request: Request):
    packs = _packs()
    request_id = base.get_task_id(request)
    if not checkout_enabled() or not packs.store_rail_ready():
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: in-app credit packs are not on sale",
        )
    return utils.get_response(
        200,
        {
            "packs": [
                {
                    "product_id": pack.store_product_id,
                    "credits": pack.credits,
                    "label": pack.label,
                    "pack_id": pack.id,
                }
                for pack in packs.list_packs()
            ]
        },
    )


@router.post("/billing/store/credit-packs/redeem", summary="Redeem a store credit pack")
def redeem_store_credit_pack(request: Request, body: StoreRedeemRequest):
    request_id = base.get_task_id(request)
    result = _redeem(
        request,
        request_id,
        product_id=body.product_id.strip(),
        transaction_id=body.transaction_id.strip(),
    )
    return utils.get_response(200, result)
