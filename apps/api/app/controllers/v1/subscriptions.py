"""Workspace subscriptions v1 API controller (Enterprise Billing Platform, Epic 3).

Mounted under ``/api/v1``. The subscription *management* surface is USER-authenticated
and gated on the ``billing.manage`` RBAC permission (Epic 1) — a workspace member
without it (e.g. a ``viewer``) gets a clean ``403`` and can never read or mutate the
tenant's billing. The subscription *webhook* is PROVIDER-authenticated (Stripe
signature) and IDEMPOTENT. Creem / Polar subscription events arrive on their
existing ``/billing/webhook/{creem,polar}`` endpoints and are routed to the same
idempotent applier.

Routes
------
* ``GET  /billing/workspace-plans``            — public recurring plan catalog + live rails
* ``GET  /me/workspaces/{id}/subscription``   — the workspace subscription (billing.manage)
* ``POST /me/workspaces/{id}/subscribe``       — recurring checkout via Stripe/Creem/Polar
* ``POST /me/workspaces/{id}/change-plan``     — switch plan AT THE PROVIDER, then locally
* ``POST /me/workspaces/{id}/cancel``          — cancel AT THE PROVIDER, then locally
* ``POST /webhooks/billing/subscription``      — Stripe subscription webhook (verified,
  IDEMPOTENT; a duplicate delivery grants credits at most once and ALWAYS returns ``200``)

Design notes
------------
* **Thin transport.** All money logic (checkout, idempotent fulfilment, entitlement
  grant) lives in :mod:`app.services.subscriptions` (authored by a sibling agent).
  This controller resolves the caller, gates on RBAC, delegates, and envelopes.
* **Import-safe.** The persistence + service layers are pulled in behind guarded
  blocks so importing this module never crashes app startup; a missing layer
  degrades to a clean ``503`` at request time.
* **Webhook never 500s on the happy/duplicate path.** A bad signature is the only
  non-2xx outcome (``400``); any other processing error is logged and acknowledged
  with ``200`` because idempotency + ledger provenance make a provider retry safe.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Path, Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.core.launch import require_checkout_enabled
from app.models.exception import HttpException
from app.models.schema import (
    ChangePlanRequest,
    SubscribeRequest,
    SubscribeResponse,
    SubscriptionResponse,
    SUBSCRIPTION_INTERVALS,
)
from app.utils import utils

# Guarded imports of the subscription service + RBAC + persistence. A partial
# environment degrades to a 503 rather than crashing at import time.
try:  # pragma: no cover - exercised implicitly by the API tests
    from app.models.db.repositories import WorkspaceRepository
    from app.services import rbac
    from app.services import subscriptions as subscriptions_service

    _SUB_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # noqa: BLE001 - import-safe: never crash the module
    WorkspaceRepository = None  # type: ignore[assignment,misc]
    rbac = None  # type: ignore[assignment]
    subscriptions_service = None  # type: ignore[assignment]
    _SUB_IMPORT_ERROR = exc

router = new_router()

# Recurring workspace plans are sold via Stripe, Creem or Polar (merchant-of-
# record rails for sellers Stripe cannot serve). iyzico has no recurring API.
_SUPPORTED_SUB_PROVIDERS: frozenset[str] = frozenset({"stripe", "creem", "polar"})


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _require_backend(request_id: str) -> None:
    """Raise 503 when the DB layer or the subscription service is unavailable."""
    _require_db(request_id)
    if (
        subscriptions_service is None
        or rbac is None
        or WorkspaceRepository is None
        or _SUB_IMPORT_ERROR is not None
    ):
        logger.error(
            f"subscriptions service unavailable, request_id: {request_id}, "
            f"error: {_SUB_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: subscriptions service is not available",
        )


def _load_workspace_or_404(session: Any, workspace_id: str, request_id: str) -> None:
    """Raise a clean ``404`` when the workspace does not exist.

    Resolving existence up front means a non-member hitting a *real* workspace
    gets a ``403`` from the RBAC gate, while any request against an unknown id gets
    a clean ``404`` (never a misleading ``403``).
    """
    if WorkspaceRepository(session).get(workspace_id) is None:
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"{request_id}: workspace not found",
        )


def _require_billing_manage(
    session: Any, request: Request, workspace_id: str, request_id: str
):
    """Resolve the caller + gate on ``billing.manage`` (403 else; 404 unknown ws).

    Tenant isolation is enforced by :func:`rbac.require_permission` — a non-member
    (no membership row) is rejected identically to an under-privileged member, so
    a caller can never read/mutate another tenant's subscription.
    """
    user = _resolve_user(request, session, request_id)
    _load_workspace_or_404(session, workspace_id, request_id)
    try:
        rbac.require_permission(
            session, user.id, workspace_id, rbac.PERM_BILLING_MANAGE
        )
    except PermissionError as exc:
        raise HttpException(
            task_id=request_id, status_code=403, message=f"{request_id}: {exc}"
        )
    return user


def _isoformat(value: Any) -> Optional[str]:
    """Best-effort ISO-8601 rendering of a timestamp; ``None`` stays ``None``."""
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:  # noqa: BLE001 - defensive: never fail a response on a timestamp
        return str(value)


def _subscription_data(row: Any) -> Optional[dict[str, Any]]:
    """Serialize a :class:`Subscription` row into a JSON-safe descriptor (secret-free)."""
    if row is None:
        return None
    return {
        "workspace_id": row.workspace_id,
        "plan_key": row.plan_key,
        "provider": row.provider,
        "provider_ref": getattr(row, "provider_ref", "") or "",
        "status": row.status,
        "interval": getattr(row, "interval", "month") or "month",
        "seats": int(getattr(row, "seats", 1) or 1),
        "current_period_end": _isoformat(getattr(row, "current_period_end", None)),
        "created_at": _isoformat(getattr(row, "created_at", None)),
        "updated_at": _isoformat(getattr(row, "updated_at", None)),
    }


# --------------------------------------------------------------------------- #
# Management endpoints (USER-authenticated + RBAC billing.manage)
# --------------------------------------------------------------------------- #
@router.get(
    "/billing/workspace-plans",
    summary="Public catalog of recurring workspace plans + available payment rails",
)
def list_workspace_plans(request: Request):
    """Return the self-serve workspace plans with live prices and, per interval,
    the payment rails that are configured to sell them (secret-free, public)."""
    request_id = base.get_task_id(request)
    try:
        from app.services.billing import workspace_plans

        plans = workspace_plans.catalog()
    except Exception as exc:  # noqa: BLE001 - config/catalog failure -> 503
        logger.error(f"workspace plan catalog failed, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: workspace plans are unavailable",
        )
    return utils.get_response(200, {"plans": plans})


@router.get(
    "/me/workspaces/{workspace_id}/subscription",
    response_model=SubscriptionResponse,
    summary="Read a workspace's subscription (billing.manage)",
)
def get_subscription(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Return the workspace's subscription (tenant-scoped; ``null`` when unset)."""
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        _require_billing_manage(session, request, workspace_id, request_id)
        row = subscriptions_service.get_subscription(session, workspace_id)
        data = _subscription_data(row)

    return utils.get_response(200, data)


@router.post(
    "/me/workspaces/{workspace_id}/subscribe",
    response_model=SubscribeResponse,
    summary="Start a Stripe checkout for a workspace subscription (billing.manage)",
)
def subscribe(
    request: Request,
    body: SubscribeRequest,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Open a Stripe checkout for a workspace subscription and return its url.

    RBAC-gated on ``billing.manage`` (a ``viewer`` gets ``403``). Only the Stripe
    rail is supported. No subscription row / credit grant happens here — both are
    created idempotently by the subscription webhook once Stripe confirms payment.
    An unknown/non-purchasable plan maps to ``400``.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)
    # A subscription checkout is a paid checkout: closed until public launch
    # (pilot staff on the allow-list can still exercise it).
    require_checkout_enabled(request_id)

    if body.provider not in _SUPPORTED_SUB_PROVIDERS:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=(
                f"{request_id}: subscriptions are available via "
                f"{', '.join(sorted(_SUPPORTED_SUB_PROVIDERS))}"
            ),
        )
    if body.interval not in SUBSCRIPTION_INTERVALS:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=(
                f"{request_id}: invalid interval "
                f"(expected one of {', '.join(sorted(SUBSCRIPTION_INTERVALS))})"
            ),
        )

    # Resolve the caller + gate inside the session, then release the connection
    # before the (slow) provider HTTP call — only primitive values leave.
    with get_session() as session:
        user = _require_billing_manage(session, request, workspace_id, request_id)
        user_id = user.id
        user_email = getattr(user, "email", "") or ""
        current = subscriptions_service.get_subscription(session, workspace_id)
        current_status = str(getattr(current, "status", "") or "").lower()
        already_live = bool(getattr(current, "provider_ref", "")) and current_status in (
            "active",
            "trialing",
            "past_due",
        )
    if already_live:
        # A second checkout would open a SECOND recurring charge for the same
        # workspace; switching plans goes through change-plan instead.
        raise HttpException(
            task_id=request_id,
            status_code=409,
            message=(
                f"{request_id}: this workspace already has a subscription; "
                "switch plans or cancel it first"
            ),
        )

    try:
        result = subscriptions_service.create_subscription(
            workspace_id=workspace_id,
            user_id=user_id,
            plan_key=body.plan_key,
            user_email=user_email,
            provider=body.provider,
            interval=body.interval,
            seats=body.seats,
        )
    except ValueError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: invalid subscribe request: {exc}",
        )
    except subscriptions_service.ProviderUnavailableError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: {exc}",
        )
    except HttpException:
        raise
    except Exception as exc:  # noqa: BLE001 - provider failure -> 502
        logger.error(f"subscribe failed, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: payment provider is unavailable",
        )

    checkout_url = (
        result.get("checkout_url") if isinstance(result, dict) else None
    )
    if not checkout_url:
        logger.error(
            f"subscribe returned no checkout url, request_id: {request_id}, "
            f"workspace: {workspace_id}, plan: {body.plan_key}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: payment provider returned no checkout url",
        )

    return utils.get_response(200, dict(result))


@router.post(
    "/me/workspaces/{workspace_id}/change-plan",
    response_model=SubscriptionResponse,
    summary="Change a workspace's subscription plan (billing.manage)",
)
def change_plan(
    request: Request,
    body: ChangePlanRequest,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Switch the workspace's subscription plan — ``billing.manage``.

    Upserts the single subscription row to ``plan_key`` (status ``active``) so the
    entitlement gate reflects it immediately. An unknown plan maps to ``400``. A
    change to a paid tier without a verified, provider-backed subscription maps to
    ``402`` (Payment Required) — the entitlement flip must be earned via Stripe
    checkout, never granted by a direct DB write.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        user = _require_billing_manage(session, request, workspace_id, request_id)
        try:
            row = subscriptions_service.change_plan(
                session,
                workspace_id=workspace_id,
                plan_key=body.plan_key,
                actor_user_id=user.id,
            )
        except ValueError as exc:
            raise HttpException(
                task_id=request_id,
                status_code=400,
                message=f"{request_id}: invalid plan change: {exc}",
            )
        except PermissionError as exc:
            raise HttpException(
                task_id=request_id,
                status_code=402,
                message=f"{request_id}: {exc}",
            )
        except Exception as exc:  # noqa: BLE001 - provider rejected the switch
            logger.error(f"change-plan provider call failed, request_id: {request_id}: {exc}")
            raise HttpException(
                task_id=request_id,
                status_code=502,
                message=(
                    f"{request_id}: the payment provider could not switch the plan; "
                    "nothing was changed"
                ),
            )
        data = _subscription_data(row)

    return utils.get_response(200, data)


@router.post(
    "/me/workspaces/{workspace_id}/cancel",
    response_model=SubscriptionResponse,
    summary="Cancel a workspace's subscription (billing.manage)",
)
def cancel_subscription(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Cancel the workspace's subscription (status -> ``canceled``) — ``billing.manage``.

    The entitlement gate then falls back to the base/free plan (no premium extra
    survives). ``404`` when the workspace has no subscription.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        user = _require_billing_manage(session, request, workspace_id, request_id)
        try:
            row = subscriptions_service.cancel_subscription(
                session, workspace_id=workspace_id, actor_user_id=user.id
            )
        except Exception as exc:  # noqa: BLE001 - provider refused the cancel
            logger.error(f"cancel provider call failed, request_id: {request_id}: {exc}")
            raise HttpException(
                task_id=request_id,
                status_code=502,
                message=(
                    f"{request_id}: the payment provider could not cancel the "
                    "subscription; it is still active — please retry"
                ),
            )
        if row is None:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: no subscription to cancel",
            )
        data = _subscription_data(row)

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# Webhook (PROVIDER-authenticated; IDEMPOTENT; always 200 on the happy/dup path)
# --------------------------------------------------------------------------- #
def _looks_like_signature_error(exc: Exception) -> bool:
    """Best-effort detection of a webhook signature/verification failure."""
    name = type(exc).__name__.lower()
    return "signature" in name or "verification" in name


@router.post(
    "/webhooks/billing/subscription",
    summary="Stripe subscription webhook (verified, IDEMPOTENT, always 200 on duplicate)",
)
async def subscription_webhook(request: Request):
    """Verify a Stripe subscription webhook and apply it IDEMPOTENTLY.

    The raw body + ``Stripe-Signature`` header are handed to
    :func:`app.services.subscriptions.handle_subscription_webhook`, which verifies
    the signature and dedupes fulfilment on the provider event id (Redis SETNX) AND
    the durable ledger reason — so a redelivered event grants credits/entitlements
    at most once. An invalid signature returns ``400``; every other outcome —
    including duplicates and transient processing errors — returns ``200`` so a
    genuine duplicate is never answered with a 5xx (which would trigger a retry
    storm).
    """
    request_id = base.get_task_id(request)
    if subscriptions_service is None:
        logger.error(
            f"subscriptions service unavailable, request_id: {request_id}, "
            f"error: {_SUB_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: subscriptions service is not available",
        )

    payload = await request.body()
    signature = request.headers.get("Stripe-Signature", "")

    try:
        result = subscriptions_service.handle_subscription_webhook(
            payload=payload, signature=signature
        )
    except ValueError as exc:  # bad signature / malformed payload
        logger.warning(
            f"subscription webhook signature verification failed, "
            f"request_id: {request_id}: {exc}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: invalid webhook signature",
        )
    except Exception as exc:  # noqa: BLE001
        if _looks_like_signature_error(exc):
            logger.warning(
                f"subscription webhook signature verification failed, "
                f"request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=400,
                message=f"{request_id}: invalid webhook signature",
            )
        # Idempotency + ledger provenance make reprocessing safe; ack with 200 so
        # we don't provoke a provider retry storm on a transient error.
        logger.error(
            f"subscription webhook processing error, request_id: {request_id}: {exc}"
        )
        return utils.get_response(200, {"status": "error_logged"})

    data = result if isinstance(result, dict) else {"status": "ignored"}
    return utils.get_response(200, data)
