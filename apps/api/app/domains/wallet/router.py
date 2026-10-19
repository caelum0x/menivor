"""Wallet HTTP domain — balance, activity, transfers, checkout, webhook.

Routes served under ``/api/v1`` via :func:`app.controllers.v1.base.new_router`.
Every response uses the MPT envelope and every error is raised as
:class:`HttpException`. The persistence layer is imported behind a guarded block
so importing this module never crashes startup (clean ``503`` when absent).

Endpoints (PROVIDER_MARKETPLACE_PLAN.md §4.3):
* ``GET  /wallet``                       balance snapshot (available/reserved)
* ``GET  /wallet/activity``              ledger activity, newest first
* ``GET  /wallet/recipients/{handle}``   resolve a public handle or Mint address
* ``GET  /wallet/transfers/{id}``        sender-only transfer status + proof
* ``POST /wallet/transfers``             send Mint-backed AI tokens idempotently
* ``POST /wallet/purchase-quotes``       checkout money breakdown (no charge)
* ``POST /wallet/checkout``              create idempotent intent — LAUNCH-GATED
* ``POST /wallet/webhooks/{provider}``   confirm + grant — LAUNCH-GATED

Money safety: balance/activity/quote are always available so a client can show
state and a fresh quote, but any path that could *create a charge or a grant*
(checkout, webhook) is fail-closed behind the launch gate until finance/legal
and payment-webhook operations are ready.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.idempotency import read_idempotency_key
from app.models.exception import HttpException
from app.utils import utils

from .schemas import (
    CheckoutRequest,
    DestinationProfileRequest,
    DestinationProfileStateRequest,
    PurchaseQuoteRequest,
    ReceiveAddressRequest,
    SavedRecipientRequest,
    TransferPolicyRequest,
    TransferChallengeRequest,
    TransferRequest,
)

# --------------------------------------------------------------------------- #
# Guarded persistence-layer import.
# --------------------------------------------------------------------------- #
try:
    from app.core.auth import resolve_principal
    from app.core.launch import require_checkout_enabled, require_payment_webhooks_enabled
    from app.domains.wallet.service import WalletError, WalletService
    from app.domains.wallet.webhooks import process_wallet_webhook
    from app.models.db.base import get_session

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before DB layer exists
    resolve_principal = None  # type: ignore[assignment]
    require_checkout_enabled = None  # type: ignore[assignment]
    require_payment_webhooks_enabled = None  # type: ignore[assignment]
    WalletError = Exception  # type: ignore[assignment,misc]
    WalletService = None  # type: ignore[assignment]
    process_wallet_webhook = None  # type: ignore[assignment]
    get_session = None  # type: ignore[assignment]
    _DB_IMPORT_ERROR = exc


router = new_router()


def _require_db(request_id: str) -> None:
    if _DB_IMPORT_ERROR is not None or get_session is None or WalletService is None:
        logger.error(
            f"wallet persistence unavailable, request_id: {request_id}, "
            f"error: {_DB_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: persistence layer is not available",
        )


def _resolve_user(request: Request, session: Any, request_id: str):
    return resolve_principal(request, session, request_id)


def _wallet_session_factory(provider: str):
    """Return the selected provider's wallet checkout factory.

    Provider selection is explicit: a Stripe request can never silently create
    a Creem checkout. Imports remain lazy so balance-only deployments do not
    initialize payment SDKs during application startup.
    """
    try:
        if provider == "creem":
            from app.services.billing import creem_client

            return creem_client.create_wallet_checkout_session
        if provider == "stripe":
            from app.services.billing import stripe_client

            return stripe_client.create_wallet_checkout_session
    except Exception as exc:  # noqa: BLE001 - normalize at the service boundary
        raise RuntimeError(
            f"{provider} wallet session factory is unavailable: {exc}"
        ) from exc
    raise ValueError(f"unsupported wallet payment provider: {provider}")


def _require_workspace_topup(
    session: Any, workspace_id: str, user_id: str, request_id: str
) -> None:
    """Gate a workspace top-up on the caller's spend role (topup = admin/owner)."""
    try:
        from app.domains.spend.roles import TOPUP
        from app.domains.spend.service import SpendError, SpendPolicyService

        SpendPolicyService(session).assert_can(TOPUP, workspace_id, user_id)
    except SpendError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=exc.status_code,
            message=f"{request_id}: {exc.message}",
        ) from exc
    except HttpException:
        raise
    except Exception as exc:  # noqa: BLE001 - spend layer optional -> fail closed
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message=f"{request_id}: workspace top-up is not permitted",
        ) from exc


def _map_wallet_error(exc: Exception, request_id: str) -> HttpException:
    status_code = int(getattr(exc, "status_code", 400) or 400)
    message = str(getattr(exc, "message", "") or "invalid wallet request")
    return HttpException(
        task_id=request_id, status_code=status_code, message=f"{request_id}: {message}"
    )


@router.get("/wallet", summary="Wallet balance")
def get_wallet(request: Request, source_account_id: str | None = None):
    """Return the caller's wallet balance (available + reserved)."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        service = WalletService(session)
        try:
            data = (
                service.balance_for_source(user.id, source_account_id)
                if source_account_id
                else service.balance_view(user.id)
            )
        except WalletError as exc:
            raise _map_wallet_error(exc, request_id) from exc
    return utils.get_response(200, data)


@router.get("/wallet/activity", summary="Wallet activity")
def get_wallet_activity(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    source_account_id: str | None = None,
):
    """Return the caller's ledger activity, newest first."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        service = WalletService(session)
        try:
            rows = (
                service.activity_for_source(
                    user.id,
                    source_account_id,
                    limit=limit,
                    offset=offset,
                )
                if source_account_id
                else service.activity(user.id, limit=limit, offset=offset)
            )
        except WalletError as exc:
            raise _map_wallet_error(exc, request_id) from exc
    return utils.get_response(200, {"activity": rows})


@router.get("/wallet/sources", summary="List authorized wallet sources")
def get_wallet_sources(request: Request):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            sources = WalletService(session).source_views(user.id)
        except WalletError as exc:
            raise _map_wallet_error(exc, request_id) from exc
    return utils.get_response(200, {"sources": sources})


@router.post("/wallet/receive-addresses", summary="Get a wallet receive address")
def get_wallet_receive_address(request: Request, body: ReceiveAddressRequest):
    """Provision/replay a stable public Mint address for an authorized source."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            data = WalletService(session).receive_address_view(
                user.id, body.source_account_id
            )
            session.commit()
        except WalletError as exc:
            raise _map_wallet_error(exc, request_id) from exc
    return utils.get_response(200, data)


@router.get("/wallet/destinations", summary="List managed receive identities")
def get_wallet_destinations(request: Request):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            rows = WalletService(session).destination_profiles(user.id)
        except WalletError as exc:
            raise _map_wallet_error(exc, request_id) from exc
    return utils.get_response(200, {"destinations": rows})


@router.post(
    "/wallet/destinations",
    summary="Create a Mint-backed receive identity",
    status_code=201,
)
def create_wallet_destination(request: Request, body: DestinationProfileRequest):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            data = WalletService(session).create_destination_profile(
                user.id,
                kind=body.kind,
                slug=body.slug,
                display_name=body.display_name,
                workspace_source_account_id=body.workspace_source_account_id,
            )
            session.commit()
        except WalletError as exc:
            raise _map_wallet_error(exc, request_id) from exc
    return utils.get_response(201, data)


@router.get(
    "/wallet/destinations/{destination_id}/balance",
    summary="Read a managed destination balance",
)
def get_wallet_destination_balance(request: Request, destination_id: str):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            data = WalletService(session).destination_profile_balance(
                user.id, destination_id
            )
        except WalletError as exc:
            raise _map_wallet_error(exc, request_id) from exc
    return utils.get_response(200, data)


@router.get(
    "/wallet/destinations/{destination_id}/activity",
    summary="Read a managed destination activity feed",
)
def get_wallet_destination_activity(
    request: Request, destination_id: str, limit: int = 50, offset: int = 0
):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            rows = WalletService(session).destination_profile_activity(
                user.id, destination_id, limit=limit, offset=offset
            )
        except WalletError as exc:
            raise _map_wallet_error(exc, request_id) from exc
    return utils.get_response(200, {"activity": rows})


@router.patch(
    "/wallet/destinations/{destination_id}",
    summary="Activate or deactivate a receive identity",
)
def patch_wallet_destination(
    request: Request,
    destination_id: str,
    body: DestinationProfileStateRequest,
):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            data = WalletService(session).set_destination_profile_active(
                user.id, destination_id, active=body.active
            )
            session.commit()
        except WalletError as exc:
            raise _map_wallet_error(exc, request_id) from exc
    return utils.get_response(200, data)


@router.put("/wallet/transfer-policy", summary="Configure wallet send limits")
def put_wallet_transfer_policy(request: Request, body: TransferPolicyRequest):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            data = WalletService(session).set_transfer_policy(
                user.id,
                source_account_id=body.source_account_id,
                per_transfer_limit_micros=body.per_transfer_limit_micros,
                daily_limit_micros=body.daily_limit_micros,
            )
        except WalletError as exc:
            raise _map_wallet_error(exc, request_id) from exc
    return utils.get_response(200, data)


@router.get("/wallet/recipients/{handle}", summary="Resolve token recipient")
def resolve_wallet_recipient(request: Request, handle: str):
    """Resolve an exact public handle without revealing private account data."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            data = WalletService(session).resolve_recipient(user.id, handle)
        except WalletError as exc:
            raise _map_wallet_error(exc, request_id) from exc
    return utils.get_response(200, data)


@router.post("/wallet/transfers", summary="Send AI tokens to a public handle")
def transfer_wallet_tokens(request: Request, body: TransferRequest):
    """Ask Mint to move balance; durable retries never request a second debit."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    idempotency_key = read_idempotency_key(request, request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            data = WalletService(session).transfer(
                user.id,
                source_account_id=body.source_account_id,
                challenge_id=body.challenge_id,
                recipient_handle=body.recipient_handle,
                amount_micros=body.amount_micros,
                idempotency_key=idempotency_key or "",
            )
        except WalletError as exc:
            raise _map_wallet_error(exc, request_id) from exc
    return utils.get_response(200, data)


@router.post("/wallet/transfer-challenges", summary="Review an AI-token transfer")
def create_wallet_transfer_challenge(request: Request, body: TransferChallengeRequest):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    idempotency_key = read_idempotency_key(request, request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            data = WalletService(session).create_transfer_challenge(
                user.id,
                source_account_id=body.source_account_id,
                recipient_handle=body.recipient_handle,
                saved_recipient_id=body.saved_recipient_id,
                amount_micros=body.amount_micros,
                idempotency_key=idempotency_key or "",
            )
        except WalletError as exc:
            raise _map_wallet_error(exc, request_id) from exc
    return utils.get_response(200, data)


@router.get("/wallet/saved-recipients", summary="List saved transfer recipients")
def get_saved_recipients(request: Request, source_account_id: str):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            rows = WalletService(session).list_saved_recipients(
                user.id, source_account_id=source_account_id
            )
        except WalletError as exc:
            raise _map_wallet_error(exc, request_id) from exc
    return utils.get_response(200, {"recipients": rows})


@router.post("/wallet/saved-recipients", summary="Save an identity-bound recipient")
def save_wallet_recipient(request: Request, body: SavedRecipientRequest):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            data = WalletService(session).save_recipient(
                user.id,
                source_account_id=body.source_account_id,
                recipient_handle=body.recipient_handle,
                label=body.label,
            )
        except WalletError as exc:
            raise _map_wallet_error(exc, request_id) from exc
    return utils.get_response(200, data)


@router.delete(
    "/wallet/saved-recipients/{saved_recipient_id}",
    summary="Delete a saved recipient",
)
def delete_wallet_recipient(
    request: Request, saved_recipient_id: str, source_account_id: str
):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            WalletService(session).delete_saved_recipient(
                user.id,
                saved_recipient_id,
                source_account_id=source_account_id,
            )
        except WalletError as exc:
            raise _map_wallet_error(exc, request_id) from exc
    return utils.get_response(200, {"deleted": True})


@router.get(
    "/wallet/transfers/{transfer_id}", summary="Get sender-owned transfer status"
)
def get_wallet_transfer(request: Request, transfer_id: str):
    """Return durable transfer state/proof only to the authenticated sender."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            data = WalletService(session).transfer_status(user.id, transfer_id)
        except WalletError as exc:
            raise _map_wallet_error(exc, request_id) from exc
    return utils.get_response(200, data)


@router.post("/wallet/purchase-quotes", summary="Quote a wallet top-up")
def purchase_quote(request: Request, body: PurchaseQuoteRequest):
    """Compute the checkout money breakdown (credit + fee + tax + total). No charge."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        # Authenticated so a caller only ever quotes against their own context.
        _resolve_user(request, session, request_id)
        try:
            quote = WalletService(session).purchase_quote(body.amount_usd)
        except WalletError as exc:
            raise _map_wallet_error(exc, request_id) from exc
    return utils.get_response(200, quote)


@router.post("/wallet/checkout", summary="Start a wallet top-up (launch-gated)")
def checkout(request: Request, body: CheckoutRequest):
    """Create an idempotent checkout intent. Fail-closed behind the launch gate.

    Requires an ``Idempotency-Key`` header so a repeated submit resolves to one
    intent (never two charges). The provider redirect session is created by the
    billing domain once payment rails are live.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    require_checkout_enabled(request_id)
    idempotency_key = read_idempotency_key(request, request_id)
    workspace_id = (body.workspace_id or "").strip() or None
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        # A workspace top-up requires the caller's role to allow funding the pool.
        if workspace_id:
            _require_workspace_topup(session, workspace_id, user.id, request_id)
        try:
            data = WalletService(session).create_checkout(
                user.id,
                amount_usd=body.amount_usd,
                provider=body.provider,
                idempotency_key=idempotency_key or "",
                session_factory=_wallet_session_factory(body.provider),
                workspace_id=workspace_id,
            )
        except WalletError as exc:
            raise _map_wallet_error(exc, request_id) from exc
    return utils.get_response(200, data)


@router.post(
    "/wallet/webhooks/{payment_provider}",
    summary="Payment webhook: verify + grant (launch-gated)",
)
async def payment_webhook(
    request: Request, payment_provider: Literal["creem", "stripe"]
):
    """Verify a payment webhook and grant the matching intent's credit.

    Fail-closed: gated behind the launch flag (403 in pilot) so no grant path is
    reachable until checkout is publicly enabled. The signature is verified by
    the provider client; a forged/malformed body is rejected with 400 and grants
    nothing. Granting is idempotent (:meth:`WalletService.confirm_intent`), so a
    duplicate provider delivery can never double-credit a wallet.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    require_payment_webhooks_enabled(request_id)
    payload = await request.body()
    with get_session() as session:
        try:
            result = process_wallet_webhook(
                session,
                payment_provider,
                payload,
                dict(request.headers),
                correlation_id=request_id,
            )
        except ValueError as exc:
            # Bad signature / malformed body / missing intent metadata -> 400.
            raise HttpException(
                task_id=request_id,
                status_code=400,
                message=f"{request_id}: {exc}",
            ) from exc
        except WalletError as exc:
            raise _map_wallet_error(exc, request_id) from exc
        except RuntimeError as exc:
            # Provider verifier unavailable (SDK missing / webhook secret
            # unset) -> clean fail-closed 503, never a stack-trace 500. No
            # grant path is reachable because verification never ran.
            raise HttpException(
                task_id=request_id,
                status_code=503,
                message=f"{request_id}: {payment_provider} webhook verification is unavailable",
            ) from exc
    return utils.get_response(200, result)
