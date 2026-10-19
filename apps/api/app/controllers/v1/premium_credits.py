"""Premium voice and AI-video credits: balances, packs and Dodo checkout.

* ``GET  /billing/premium``          - the caller's premium balances, the packs
  on sale and how AI-video credits are priced (3x provider cost, 1 credit = 1
  US cent).
* ``POST /billing/premium/checkout`` - open a Dodo checkout for one pack.
  Credits land once, from the ``payment.succeeded`` webhook or the verified
  browser return (``POST /billing/dodo/confirm``), never here.

A standard reel credit never pays for ElevenLabs or AI-video / presenter
provider calls; these balances do (see ``app.services.billing.premium_credits``).
"""

from __future__ import annotations

from fastapi import Request
from loguru import logger
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.auth import resolve_principal
from app.core.launch import require_checkout_enabled
from app.models.db.base import get_session
from app.models.exception import HttpException
from app.services.billing import premium_credits
from app.utils import utils

router = new_router()


class PremiumCheckoutRequest(BaseModel):
    pack_key: str = Field(min_length=1, max_length=40)


def _caller(request: Request, request_id: str) -> dict[str, str]:
    with get_session() as session:
        user = resolve_principal(request, session, request_id)
        return {"id": str(user.id), "email": str(getattr(user, "email", "") or "")}


@router.get("/billing/premium", summary="Premium voice and AI-video credits")
def premium_status(request: Request):
    request_id = base.get_task_id(request)
    user = _caller(request, request_id)
    return utils.get_response(
        200,
        {
            "balances": premium_credits.balances(user["id"]),
            "packs": [pack.as_dict() for pack in premium_credits.list_packs()],
            "ai_video_markup": premium_credits.AI_VIDEO_MARKUP,
            "ai_video_credit_usd": 0.01,
        },
    )


@router.post("/billing/premium/checkout", summary="Buy a premium voice or AI-video pack")
def premium_checkout(request: Request, body: PremiumCheckoutRequest):
    request_id = base.get_task_id(request)
    require_checkout_enabled(request_id)
    pack = premium_credits.get_pack(body.pack_key)
    if pack is None:
        raise HttpException(task_id=request_id, status_code=400, message=f"{request_id}: unknown pack")

    from app.services.billing import dodo_billing, payments_mode

    if payments_mode.active_provider() != payments_mode.DODO:
        raise HttpException(
            task_id=request_id,
            status_code=409,
            message="Premium packs are not on sale right now.",
            data={"code": "payments_paused"},
        )
    user = _caller(request, request_id)
    try:
        result = dodo_billing.open_premium_checkout(user, pack)
    except ValueError as exc:
        logger.error(f"premium checkout not configured, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=409,
            message="This pack is not on sale yet.",
            data={"code": "pack_not_configured"},
        ) from exc
    except Exception as exc:  # noqa: BLE001 - provider failure -> 502
        logger.error(f"premium checkout failed, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: payment provider is unavailable",
        ) from exc
    url = str((result or {}).get("checkout_url") or "")
    if not url:
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: payment provider returned no checkout url",
        )
    return utils.get_response(200, {"checkout_url": url, "pack": pack.as_dict()})
