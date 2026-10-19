"""Personal monthly plans (Creator / Pro / Agency) — web billing v1 API.

* ``GET  /api/v1/billing/monthly-plans``           -> public catalog (no auth).
* ``GET  /api/v1/billing/monthly-plan``            -> my plan, renewal date,
  included reels left, balance and the recommended upgrade.
* ``POST /api/v1/billing/monthly-plan/checkout``   -> Creem recurring checkout.
* ``POST /api/v1/billing/monthly-plan/change``     -> switch plan (upgrade now).
* ``POST /api/v1/billing/monthly-plan/cancel``     -> one-click renewal off.
* ``POST /api/v1/billing/monthly-plan/portal``     -> Creem customer portal URL.

Webhooks arrive on the existing ``/billing/webhook/creem`` endpoint and the
signed return on ``/billing/creem/confirm`` (routed in the billing service).
Errors carry copy the web shows as-is. Mobile (RevenueCat) is separate.
"""

from __future__ import annotations

from fastapi import Request
from loguru import logger
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.launch import require_checkout_enabled
from app.models.exception import HttpException
from app.utils import utils

router = new_router()

_UNAVAILABLE = "Monthly plans are not on sale yet. Credit packs work in the meantime."
_PROVIDER_DOWN = "The payment provider did not answer. Click again in a moment."


class MonthlyCheckoutRequest(BaseModel):
    plan_key: str = Field(..., min_length=1, max_length=40)
    interval: str = Field(default="month", max_length=10)


class MonthlyChangeRequest(BaseModel):
    plan_key: str = Field(..., min_length=1, max_length=40)


def _fail(request_id: str, status: int, message: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=status, message=message)


def _user(request: Request, request_id: str) -> tuple[str, str]:
    """(user id, email) of the signed-in caller; 401 otherwise, 503 without a DB."""
    try:
        from app.models.db.base import get_session
    except Exception as exc:  # noqa: BLE001 - persistence missing -> 503
        logger.error(f"monthly plans: persistence unavailable, request_id: {request_id}: {exc}")
        raise _fail(request_id, 503, "Billing is temporarily unavailable.")
    from app.core.auth.principal import resolve_principal

    with get_session() as session:
        user = resolve_principal(request, session, request_id)
        return str(user.id), str(getattr(user, "email", "") or "")


def _actions():
    from app.services.billing import creator_plan_actions

    return creator_plan_actions


def _subs():
    from app.services.billing import creator_subscriptions

    return creator_subscriptions


@router.get("/billing/monthly-plans", summary="Monthly plans catalog")
def monthly_plans(request: Request):
    """Public catalog: price per month/year, reels, per-reel price, availability."""
    from app.services.billing import creator_plans

    return utils.get_response(
        200,
        {
            "plans": creator_plans.catalog(),
            "yearly_months_charged": creator_plans.YEARLY_MONTHS_CHARGED,
            "best_pack_per_reel_cents": int(round(creator_plans.best_pack_per_reel_usd() * 100)),
        },
    )


@router.get("/billing/monthly-plan", summary="My monthly plan")
def my_monthly_plan(request: Request):
    request_id = base.get_task_id(request)
    user_id, _ = _user(request, request_id)
    try:
        data = _actions().status(user_id)
    except Exception as exc:  # noqa: BLE001 - status read failure -> 502
        logger.error(f"monthly plan status failed, request_id: {request_id}: {exc}")
        raise _fail(request_id, 502, "Could not load your plan. Refresh to try again.")
    return utils.get_response(200, data)


@router.post("/billing/monthly-plan/checkout", summary="Subscribe to a monthly plan")
def monthly_checkout(request: Request, body: MonthlyCheckoutRequest):
    request_id = base.get_task_id(request)
    require_checkout_enabled(request_id)
    user_id, email = _user(request, request_id)
    try:
        data = _actions().start_checkout(
            user_id=user_id, user_email=email, plan_key=body.plan_key, interval=body.interval
        )
    except _subs().AlreadySubscribed as exc:
        raise _fail(request_id, 409, str(exc))
    except _actions().PaymentsPaused as exc:
        raise _fail(request_id, 409, str(exc))
    except ValueError as exc:
        raise _fail(request_id, 400, str(exc))
    except RuntimeError as exc:
        logger.error(f"monthly checkout failed, request_id: {request_id}: {exc}")
        configured = "not configured" not in str(exc)
        raise _fail(request_id, 502 if configured else 503, _PROVIDER_DOWN if configured else _UNAVAILABLE)
    return utils.get_response(200, data)


@router.post("/billing/monthly-plan/change", summary="Switch monthly plan")
def monthly_change(request: Request, body: MonthlyChangeRequest):
    request_id = base.get_task_id(request)
    user_id, _ = _user(request, request_id)
    try:
        data = _actions().change_plan(user_id, body.plan_key)
    except _subs().NoSubscription as exc:
        raise _fail(request_id, 404, str(exc))
    except ValueError as exc:
        raise _fail(request_id, 400, str(exc))
    except RuntimeError as exc:
        logger.error(f"monthly plan change failed, request_id: {request_id}: {exc}")
        raise _fail(request_id, 502, "Your plan was not changed. Try again in a moment.")
    return utils.get_response(200, data)


@router.post("/billing/monthly-plan/cancel", summary="Turn off renewal")
def monthly_cancel(request: Request):
    request_id = base.get_task_id(request)
    user_id, _ = _user(request, request_id)
    try:
        data = _actions().cancel(user_id)
    except _subs().NoSubscription as exc:
        raise _fail(request_id, 404, str(exc))
    except (RuntimeError, ValueError) as exc:
        logger.error(f"monthly plan cancel failed, request_id: {request_id}: {exc}")
        raise _fail(
            request_id,
            502,
            "Renewal is still on: the payment provider did not confirm. Try again, or email support@menivor.com.",
        )
    return utils.get_response(200, data)


@router.post("/billing/monthly-plan/portal", summary="Open the billing portal")
def monthly_portal(request: Request):
    request_id = base.get_task_id(request)
    user_id, _ = _user(request, request_id)
    try:
        url = _actions().portal(user_id)
    except _subs().NoSubscription as exc:
        raise _fail(request_id, 404, str(exc))
    except (RuntimeError, ValueError) as exc:
        logger.error(f"monthly plan portal failed, request_id: {request_id}: {exc}")
        raise _fail(request_id, 502, _PROVIDER_DOWN)
    return utils.get_response(200, {"url": url})
