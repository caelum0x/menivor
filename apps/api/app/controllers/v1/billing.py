"""ReelForge billing v1 API controller (Stripe + iyzico + Creem + Polar).

Routes served under ``/api/v1`` via :func:`app.controllers.v1.base.new_router`.
Every response uses the MPT envelope ``utils.get_response(status, data, message)``
and every client-facing error is raised as :class:`HttpException`.

Endpoints
---------
* ``GET  /api/v1/billing/plans``          -> public credit-plan catalogue.
* ``GET  /api/v1/billing/providers``      -> enabled payment providers (those with
  configured secrets) for the checkout UI.
* ``POST /api/v1/billing/checkout``       -> create a provider checkout session
  (auth via ``x-api-key``); provider in {stripe, iyzico, creem, polar}; returns
  ``{checkout_url}``.
* ``GET/POST /api/v1/billing/card-check`` -> web unlock status / open the $1
  Creem card check that credits 1 reel and unlocks the free signup reels.
* ``POST /api/v1/billing/creem/confirm`` -> credit a pack from Creem's SIGNED
  success redirect (no webhook needed); idempotent with the Creem webhook.
* ``POST /api/v1/billing/webhook/stripe`` -> Stripe webhook. Reads the raw body,
  verifies the ``Stripe-Signature`` header in the service, is idempotent, and
  returns ``200`` fast. A duplicate event NEVER produces a 5xx.
* ``POST /api/v1/billing/webhook/creem``  -> Creem webhook. Raw body + the
  ``creem-signature`` header verified in the service; idempotent; ``200`` fast.
* ``POST /api/v1/billing/webhook/polar``  -> Polar webhook. Raw body + the
  Standard-Webhooks ``webhook-*`` headers verified in the service; idempotent;
  ``200`` fast.
* ``POST /api/v1/billing/webhook/iyzico`` -> iyzico callback. The posted ``token``
  is exchanged server-to-server for the authoritative payment result (that
  retrieval *is* the verification); idempotent; returns ``200`` fast.

Design notes
------------
* **Secrets stay in config.** SDK calls, signature verification and Redis-SETNX
  idempotency all live in the *billing service* (``app.services.billing.service``,
  authored by a sibling agent). This controller is a thin, import-safe transport
  layer: validate request shape, resolve the caller, delegate, envelope.
* **Import-safe.** The billing service and the persistence layer are pulled in
  behind guarded blocks (mirroring ``jobs.py``/``storage/r2.py``) so merely
  importing this module never crashes app startup; a missing layer degrades to a
  clean ``503`` at request time instead of an ``ImportError``.
* **Webhooks never 500 on the happy/duplicate path.** Bad signatures are the only
  non-2xx webhook outcome (``400``); any other processing error is logged and
  acknowledged with ``200`` because idempotency plus ledger provenance make a
  provider retry safe and a 5xx would only trigger a retry storm.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl

from fastapi import Request
from loguru import logger
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.launch import require_checkout_enabled
from app.models.exception import HttpException
from app.models.schema import (
    CheckoutRequest,
    CheckoutResponse,
    PlansResponse,
    ProvidersResponse,
)
from app.utils import utils

# --------------------------------------------------------------------------- #
# Guarded persistence-layer import (authored by sibling agents; may be absent at
# import time). Keeps this module import-safe — a missing layer degrades to a
# 503 at request time rather than an ImportError at startup.
# --------------------------------------------------------------------------- #
try:
    from app.models.db.base import get_session
    from app.models.db.models import User
    from app.services import workspaces as workspaces_service

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # noqa: BLE001  # pragma: no cover - before DB layer exists
    get_session = None  # type: ignore[assignment]
    User = None  # type: ignore[assignment]
    workspaces_service = None  # type: ignore[assignment]
    _DB_IMPORT_ERROR = exc


router = new_router()

# Providers accepted at the API boundary; the service enforces per-provider
# secret configuration and plan pricing.
_SUPPORTED_PROVIDERS: tuple[str, ...] = ("stripe", "iyzico", "creem", "polar", "dodo", "paddle")


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _require_db(request_id: str) -> None:
    """Raise 503 when the persistence layer could not be imported."""
    if _DB_IMPORT_ERROR is not None or get_session is None:
        logger.error(
            f"persistence layer unavailable, request_id: {request_id}, "
            f"error: {_DB_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: persistence layer is not available",
        )


def _import_service(request_id: str):
    """Lazily import the billing service module (503 when absent).

    The service owns the Stripe/iyzico SDK calls, signature verification and the
    Redis-SETNX idempotency guard; it is authored by a sibling agent and may not
    exist yet, so importing it is guarded and surfaced as a clean 503.
    """
    try:
        from app.services.billing import service

        return service
    except Exception as exc:  # noqa: BLE001 - surfaced as a clean 503
        logger.error(f"billing service unavailable, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: billing service is not available",
        )


def _resolve_user(request: Request, session: Any, request_id: str):
    """Resolve the caller like every other authenticated route.

    Accepts a signed-in web session (Clerk JWT), a mobile Supabase bearer, a
    device/account key hashed onto ``User.api_key_hash``, or a per-user API key.
    Raises 401 when none resolves.
    """
    from app.core.auth.principal import resolve_principal

    return resolve_principal(request, session, request_id)


def _require_workspace_admin(
    session: Any, workspace_id: str, actor_user_id: str, request_id: str
) -> None:
    """Authorize ``actor_user_id`` as an ``admin`` (or higher) of ``workspace_id``.

    Called only when a checkout request targets a workspace's SHARED credit pool,
    *before* any provider session is created — so the workspace id can only reach
    Stripe metadata after this gate passes and the webhook (which trusts that
    server-set metadata) can safely fund the pool.

    Mapping:

    * missing workspaces layer          -> ``503`` (degraded service).
    * unknown workspace                 -> ``404`` (cannot fund a nonexistent pool).
    * caller is not an admin/owner       -> ``403`` (includes plain members and
      non-members, since :func:`workspaces.require_role` raises ``PermissionError``
      for both).
    * malformed role configuration       -> ``400`` (defensive; should not happen).
    """
    if workspaces_service is None:  # pragma: no cover - guarded with _require_db
        logger.error(
            f"workspaces layer unavailable, request_id: {request_id}, "
            f"error: {_DB_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: workspaces layer is not available",
        )

    # Unknown workspace -> 404 rather than a misleading 403; a pool that does not
    # exist can never be funded.
    if workspaces_service.get_membership(session, workspace_id, actor_user_id) is None:
        repo = workspaces_service.WorkspaceRepository(session)
        if repo.get(workspace_id) is None:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: workspace not found",
            )

    try:
        workspaces_service.require_role(
            session, workspace_id, actor_user_id, workspaces_service.ROLE_ADMIN
        )
    except PermissionError as exc:
        # Not a member, or a member below admin -> forbidden.
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message=(
                f"{request_id}: admin role required to buy workspace credits: {exc}"
            ),
        )
    except ValueError as exc:  # pragma: no cover - defensive; role is a constant
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: invalid workspace authorization request: {exc}",
        )


def _looks_like_signature_error(exc: Exception) -> bool:
    """Best-effort detection of a webhook signature/verification failure.

    Complements the service's own ``WebhookVerificationError`` so that a raw
    provider-SDK signature error (e.g. Stripe's ``SignatureVerificationError``)
    is still mapped to a 400 rather than swallowed as a generic error.
    """
    name = type(exc).__name__.lower()
    return "signature" in name or "verification" in name


def _envelope_result(result: Any) -> dict:
    """Normalise a service return value into envelope ``data`` (always a dict)."""
    return result if isinstance(result, dict) else {"status": "ok"}


async def _extract_iyzico_token(request: Request) -> str:
    """Extract the iyzico callback ``token`` from form, query, or JSON body.

    iyzico posts ``application/x-www-form-urlencoded`` with a ``token`` field on
    its redirect/callback; query-string and JSON fallbacks make the endpoint
    resilient to integration variants. Body reads are cached by Starlette, so
    reading form then JSON is safe.
    """
    try:
        form = await request.form()
        token = form.get("token")
        if token:
            return str(token)
    except Exception as exc:  # noqa: BLE001 - form parsing is best-effort
        logger.debug(f"iyzico token form parse skipped: {exc}")

    token = request.query_params.get("token")
    if token:
        return str(token)

    try:
        body = await request.json()
        if isinstance(body, dict) and body.get("token"):
            return str(body["token"])
    except Exception as exc:  # noqa: BLE001 - JSON parsing is best-effort
        logger.debug(f"iyzico token json parse skipped: {exc}")

    return ""


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.get("/billing/plans", response_model=PlansResponse, summary="List credit plans")
def list_plans(request: Request):
    """Return the public credit-plan catalogue (Free / Starter / Pro).

    No auth required — pricing is public. The plan catalogue (credits + price per
    ``plan_key``) is owned by the billing service so checkout and this listing
    never drift apart.
    """
    request_id = base.get_task_id(request)
    service = _import_service(request_id)
    try:
        plans = service.list_plans()
    except Exception as exc:  # noqa: BLE001 - catalogue read failure -> 502
        logger.error(f"list_plans failed, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: unable to load plans",
        )
    return utils.get_response(200, plans)


@router.get(
    "/billing/providers",
    response_model=ProvidersResponse,
    summary="List enabled payment providers",
)
def list_providers(request: Request):
    """Return the payment providers that are configured (enabled) for checkout.

    No auth required. A provider appears only when its required secret(s) are
    present in config, so the UI renders only the rails that will actually work
    (Stripe / iyzico / Creem / Polar). Secret detection lives in the billing
    service; this endpoint never reads provider secrets directly.
    """
    request_id = base.get_task_id(request)
    # Do not disclose or advertise configured payment rails before the explicit
    # public launch gate is open. Provider credentials are operational secrets,
    # not a feature toggle.
    try:
        require_checkout_enabled(request_id)
    except HttpException:
        return utils.get_response(200, {"providers": []})
    service = _import_service(request_id)
    try:
        providers = service.list_enabled_providers()
    except Exception as exc:  # noqa: BLE001 - provider probe failure -> 502
        logger.error(f"list_providers failed, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: unable to load providers",
        )
    return utils.get_response(200, {"providers": list(providers)})


@router.post(
    "/billing/checkout",
    response_model=CheckoutResponse,
    summary="Create a checkout session",
)
def create_checkout(request: Request, body: CheckoutRequest):
    """Create a provider checkout session and return its ``checkout_url``.

    Order: validate ``provider``/``plan_key`` at the boundary -> authenticate the
    caller (``x-api-key``) -> when a ``workspace_id`` is supplied, require the
    caller to be an ``admin`` (or higher) of that workspace -> delegate to the
    billing service (which builds the Stripe/iyzico session with the user id, and
    optionally the workspace id, encoded in provider metadata so the webhook can
    credit the right personal balance or shared pool). Credits are granted only on
    webhook confirmation, never here.

    When ``workspace_id`` is present the purchase funds the workspace's SHARED
    credit pool; the admin authorization gate runs *before* the provider session
    is created, so the workspace id can only reach Stripe metadata after the check
    passes. Personal checkout (no ``workspace_id``) is unchanged.
    """
    request_id = base.get_task_id(request)
    require_checkout_enabled(request_id)

    provider = (getattr(body, "provider", "") or "").strip().lower()
    plan_key = (getattr(body, "plan_key", "") or "").strip()
    workspace_id = (getattr(body, "workspace_id", None) or "").strip() or None
    if provider not in _SUPPORTED_PROVIDERS:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=(
                f"{request_id}: unsupported provider "
                f"(expected one of {', '.join(_SUPPORTED_PROVIDERS)})"
            ),
        )
    if not plan_key:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: plan_key is required",
        )

    _require_db(request_id)
    service = _import_service(request_id)

    # Resolve the caller, then release the DB connection *before* the (slow)
    # provider HTTP call — only primitive, JSON-safe values leave the session.
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        user_id = user.id
        user_email = user.email
        # Authorize the workspace-pool purchase (admin+) inside the same session,
        # before releasing the connection for the slow provider HTTP call. This
        # is the only place the workspace id is trusted enough to reach Stripe
        # metadata; the webhook relies on that server-set metadata.
        if workspace_id is not None:
            _require_workspace_admin(session, workspace_id, user_id, request_id)

    try:
        checkout_url = service.create_checkout(
            user_id=user_id,
            user_email=user_email,
            plan_key=plan_key,
            provider=provider,
            workspace_id=workspace_id,
        )
    except service.PaymentsPaused as exc:
        raise HttpException(
            task_id=request_id,
            status_code=409,
            message=str(exc),
            data={"code": "payments_paused"},
        )
    except ValueError as exc:
        # Unknown plan_key / provider-config rejection -> client error.
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: invalid checkout request: {exc}",
        )
    except HttpException:
        raise
    except Exception as exc:  # noqa: BLE001 - provider failure -> 502
        logger.error(f"create_checkout failed, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: payment provider is unavailable",
        )

    url = (
        checkout_url.get("checkout_url")
        if isinstance(checkout_url, dict)
        else checkout_url
    )
    if not url:
        logger.error(
            f"create_checkout returned no url, request_id: {request_id}, "
            f"provider: {provider}, plan: {plan_key}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: payment provider returned no checkout url",
        )

    return utils.get_response(200, {"checkout_url": str(url)})


class CardCheckRequest(BaseModel):
    """Where to continue after paying (a same-site path, default ``/create``)."""

    next: str | None = Field(default=None, max_length=700)


def _card_check_module():
    from app.services.billing import card_check

    return card_check


@router.get("/billing/card-check", summary="Card-check (free reels unlock) status")
def card_check_status(request: Request):
    """``{unlocked, available, credits, price_usd, card_check_credits, free_credits}``.

    ``unlocked`` is true once the account holds its free signup reels or has
    paid for anything; the web shows the $1 unlock step only while it is false.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    card_check = _card_check_module()
    from app.services.billing import payments_mode

    with get_session() as session:
        user_id = _resolve_user(request, session, request_id).id
    if payments_mode.payments_paused():
        # No card check while paused: this month's free reels instead (once).
        try:
            payments_mode.grant_free_monthly(user_id)
        except Exception as exc:  # noqa: BLE001 - status must still render
            logger.error(f"free monthly grant failed, request_id: {request_id}: {exc}")
    else:
        # MENIVOR_FREE_FIRST_REEL: one reel before the card check (once per person).
        from app.services.billing import first_reel

        try:
            first_reel.maybe_grant(user_id)
        except Exception as exc:  # noqa: BLE001 - status must still render
            logger.error(f"free first reel grant failed, request_id: {request_id}: {exc}")
    with get_session() as session:
        data = card_check.status(session, user_id)
    return utils.get_response(200, data)


@router.post("/billing/card-check", summary="Start the $1 card check")
def start_card_check(request: Request, body: CardCheckRequest | None = None):
    """Open the $1 Creem checkout that unlocks the free reels (credited as 1 reel).

    Not behind the checkout launch flag: it is the mandatory activation step
    for web accounts, and only needs Creem configured.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    card_check = _card_check_module()
    from app.services.billing import payments_mode

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        user_id = user.id
        user_email = str(getattr(user, "email", "") or "")
        if user_email.endswith("@users.reelforge"):
            user_email = ""
        unlocked = card_check.is_unlocked(session, user_id)
    if payments_mode.payments_paused():
        payments_mode.grant_free_monthly(user_id)
        raise HttpException(
            task_id=request_id,
            status_code=409,
            message="Menivor is free while we move to a new payment partner. Go to Create to make a reel.",
            data={"code": "payments_paused"},
        )
    if unlocked:
        raise HttpException(
            task_id=request_id,
            status_code=409,
            message="Your free reels are already unlocked. Go to Create to make a reel.",
        )
    try:
        result = card_check.start_checkout(
            user_id, body.next if body else None, user_email=user_email
        )
    except card_check.CardCheckUnavailable as exc:
        logger.error(f"card check unavailable, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=(
                "Card payments are not switched on yet. Try again in a few minutes, "
                "or email support@menivor.com and we will unlock your account."
            ),
        )
    except Exception as exc:  # noqa: BLE001 - provider failure -> retryable 502
        logger.error(f"card check checkout failed, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message="The payment page did not open. Click the button again in a moment.",
        )
    return utils.get_response(200, result)


class CreemConfirmRequest(BaseModel):
    """The raw query string Creem appended to our success URL."""

    query: str = Field(..., min_length=1, max_length=4096)


@router.post("/billing/creem/confirm", summary="Confirm a Creem checkout redirect")
def confirm_creem_checkout(request: Request, body: CreemConfirmRequest):
    """Credit a pack from Creem's signed success redirect (works with no webhook).

    No auth header is needed: the redirect signature (salted with our Creem API
    key) is the proof of payment, and the buyer + pack come from the signed
    ``request_id`` / ``product_id``. Idempotent with the webhook, so a refresh or a
    later webhook never grants twice. Deliberately NOT behind the checkout launch
    gate: a buyer who already paid must always receive their credits.
    """
    request_id = base.get_task_id(request)
    service = _import_service(request_id)
    pairs = parse_qsl(body.query.lstrip("?"), keep_blank_values=True)

    verification_error = getattr(service, "RedirectVerificationError", ValueError)
    try:
        result = service.confirm_creem_redirect(pairs)
    except verification_error as exc:  # type: ignore[misc]
        logger.warning(f"creem redirect rejected, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=(
                "We could not verify this payment link. If you were charged, "
                "your credits arrive automatically once the payment confirms; "
                "contact support with your receipt if they do not."
            ),
        )
    except Exception as exc:  # noqa: BLE001 - grant failure -> retryable 502
        logger.error(f"creem redirect grant failed, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message="Your payment went through but crediting failed. Refresh this page to retry.",
        )
    return utils.get_response(200, result)


@router.post("/billing/webhook/stripe", summary="Stripe payment webhook")
async def stripe_webhook(request: Request):
    """Handle a Stripe webhook: verify signature, grant credits, ack fast.

    The raw request body and ``Stripe-Signature`` header are handed to the
    service, which verifies the signature (``stripe.webhook_secret``) and applies
    the Redis-SETNX idempotency guard on the event id. Invalid signatures return
    ``400``; every other outcome — including duplicates and transient processing
    errors — returns ``200`` so a genuine duplicate is never answered with a 5xx.
    """
    request_id = base.get_task_id(request)
    service = _import_service(request_id)

    payload = await request.body()
    signature = request.headers.get("Stripe-Signature", "")

    verification_error = getattr(service, "WebhookVerificationError", ValueError)
    try:
        result = service.handle_stripe_webhook(payload=payload, signature=signature)
    except verification_error as exc:  # type: ignore[misc] - bad signature / payload
        logger.warning(
            f"stripe webhook signature verification failed, "
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
                f"stripe webhook signature verification failed, "
                f"request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=400,
                message=f"{request_id}: invalid webhook signature",
            )
        # Idempotency + ledger provenance make reprocessing safe; ack with 200 so
        # we don't provoke a provider retry storm on a transient error.
        logger.error(f"stripe webhook processing error, request_id: {request_id}: {exc}")
        return utils.get_response(200, {"status": "error_logged"})

    return utils.get_response(200, _envelope_result(result))


@router.post("/billing/webhook/creem", summary="Creem payment webhook")
async def creem_webhook(request: Request):
    """Handle a Creem webhook: verify signature, grant credits, ack fast.

    The raw request body and ``creem-signature`` header are handed to the service,
    which verifies the HMAC-SHA256 signature (``creem.webhook_secret``) and applies
    the Redis-SETNX idempotency guard on the event id. Invalid signatures return
    ``400``; every other outcome — including duplicates and transient processing
    errors — returns ``200`` so a genuine duplicate is never answered with a 5xx.
    """
    request_id = base.get_task_id(request)
    service = _import_service(request_id)

    payload = await request.body()
    signature = request.headers.get("creem-signature", "")

    verification_error = getattr(service, "WebhookVerificationError", ValueError)
    try:
        result = service.handle_creem_webhook(payload=payload, signature=signature)
    except verification_error as exc:  # type: ignore[misc] - bad signature / payload
        logger.warning(
            f"creem webhook signature verification failed, "
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
                f"creem webhook signature verification failed, "
                f"request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=400,
                message=f"{request_id}: invalid webhook signature",
            )
        # Idempotency + ledger provenance make reprocessing safe; ack with 200 so
        # we don't provoke a provider retry storm on a transient error.
        logger.error(f"creem webhook processing error, request_id: {request_id}: {exc}")
        return utils.get_response(200, {"status": "error_logged"})

    return utils.get_response(200, _envelope_result(result))


class DodoConfirmRequest(BaseModel):
    """Ids Dodo appended to our return URL (verified server-side with Dodo)."""

    payment_id: str | None = Field(default=None, max_length=128)
    subscription_id: str | None = Field(default=None, max_length=128)


@router.post("/billing/dodo/confirm", summary="Confirm a Dodo Payments checkout return")
def confirm_dodo_checkout(request: Request, body: DodoConfirmRequest):
    """Credit a Dodo purchase from the browser return, idempotent with the webhook.

    The return URL is not signed, so the ids are only hints: the payment (or
    subscription) is read back from Dodo with our API key and must belong to
    the signed-in user. Not behind the checkout gate: a buyer who paid must
    always receive their credits. ``{pending: true}`` while Dodo is settling.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    from app.services.billing import dodo_billing

    payment_id = (body.payment_id or "").strip()
    subscription_id = (body.subscription_id or "").strip()
    if not payment_id and not subscription_id:
        raise HttpException(
            task_id=request_id, status_code=400, message="payment_id or subscription_id is required"
        )
    with get_session() as session:
        user_id = _resolve_user(request, session, request_id).id
    try:
        result = dodo_billing.confirm_return(
            user_id=user_id, payment_id=payment_id, subscription_id=subscription_id
        )
    except dodo_billing.ConfirmError as exc:
        raise HttpException(task_id=request_id, status_code=400, message=str(exc))
    except Exception as exc:  # noqa: BLE001 - provider/grant failure -> retryable
        logger.error(f"dodo confirm failed, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message="We could not confirm the payment yet. Refresh this page in a moment.",
        )
    return utils.get_response(200, result)


async def _dodo_webhook(request: Request):
    request_id = base.get_task_id(request)
    from app.services.billing import dodo_billing, standard_webhooks

    payload = await request.body()
    try:
        result = dodo_billing.handle_webhook(payload, dict(request.headers))
    except standard_webhooks.SignatureError as exc:
        logger.warning(f"dodo webhook rejected, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id, status_code=400, message=f"{request_id}: invalid webhook signature"
        )
    except Exception as exc:  # noqa: BLE001 - let Dodo retry; grants are idempotent
        logger.error(f"dodo webhook processing error, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id, status_code=500, message=f"{request_id}: webhook processing failed"
        )
    return utils.get_response(200, result)


@router.post("/billing/webhook/dodo", summary="Dodo Payments webhook")
async def dodo_webhook(request: Request):
    """Verify (Standard Webhooks) and apply a Dodo Payments event.

    Invalid signatures -> 400. Processing errors -> 500 so Dodo retries; every
    grant is idempotent (ledger reason + event id), so retries never double-grant.
    """
    return await _dodo_webhook(request)


@router.post("/billing/webhooks/dodo", summary="Dodo Payments webhook (alias)", include_in_schema=False)
async def dodo_webhook_alias(request: Request):
    return await _dodo_webhook(request)


@router.post("/billing/webhook/paddle", summary="Paddle Billing webhook")
async def paddle_webhook(request: Request):
    """Verify ``Paddle-Signature`` and fulfil a completed pack transaction."""
    request_id = base.get_task_id(request)
    from app.services.billing import paddle_client

    payload = await request.body()
    try:
        balance = paddle_client.handle_webhook(payload, request.headers.get("paddle-signature", ""))
    except ValueError as exc:
        logger.warning(f"paddle webhook rejected, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id, status_code=400, message=f"{request_id}: invalid webhook signature"
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"paddle webhook processing error, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id, status_code=500, message=f"{request_id}: webhook processing failed"
        )
    return utils.get_response(200, {"balance": balance})


@router.post("/billing/webhook/polar", summary="Polar payment webhook")
async def polar_webhook(request: Request):
    """Handle a Polar webhook: verify signature, grant credits, ack fast.

    The raw request body and the Standard-Webhooks headers (``webhook-id`` /
    ``webhook-timestamp`` / ``webhook-signature``) are handed to the service, which
    verifies the signature (``polar.webhook_secret``) and applies the Redis-SETNX
    idempotency guard on the event id. Invalid signatures (or a stale timestamp)
    return ``400``; every other outcome — including duplicates and transient
    processing errors — returns ``200`` so a genuine duplicate is never answered
    with a 5xx.
    """
    request_id = base.get_task_id(request)
    service = _import_service(request_id)

    payload = await request.body()
    # Pass the full header set; the service/client reads the webhook-* headers
    # case-insensitively (Starlette normalises header keys to lower-case).
    headers = dict(request.headers)

    verification_error = getattr(service, "WebhookVerificationError", ValueError)
    try:
        result = service.handle_polar_webhook(payload=payload, headers=headers)
    except verification_error as exc:  # type: ignore[misc] - bad signature / payload
        logger.warning(
            f"polar webhook signature verification failed, "
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
                f"polar webhook signature verification failed, "
                f"request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=400,
                message=f"{request_id}: invalid webhook signature",
            )
        # Idempotency + ledger provenance make reprocessing safe; ack with 200 so
        # we don't provoke a provider retry storm on a transient error.
        logger.error(f"polar webhook processing error, request_id: {request_id}: {exc}")
        return utils.get_response(200, {"status": "error_logged"})

    return utils.get_response(200, _envelope_result(result))


@router.post("/billing/webhook/iyzico", summary="iyzico payment callback")
async def iyzico_webhook(request: Request):
    """Handle an iyzico callback: exchange the ``token`` for the payment result.

    iyzico posts a ``token`` that the service exchanges server-to-server (using
    ``iyzico.api_key``/``iyzico.secret_key``) for the authoritative payment
    result — that retrieval *is* the verification. The service applies the
    Redis-SETNX idempotency guard before granting credits. A missing token is a
    ``400``; any processing error is logged and acked with ``200`` (idempotent).
    """
    request_id = base.get_task_id(request)
    service = _import_service(request_id)

    token = await _extract_iyzico_token(request)
    if not token:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: missing iyzico token",
        )

    try:
        result = service.handle_iyzico_callback(token=token)
    except HttpException:
        raise
    except Exception as exc:  # noqa: BLE001 - idempotent; ack with 200
        logger.error(f"iyzico callback processing error, request_id: {request_id}: {exc}")
        return utils.get_response(200, {"status": "error_logged"})

    return utils.get_response(200, _envelope_result(result))
