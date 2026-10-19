"""One-time credit packs: catalog, card checkout (Creem) and store redemption.

A credit pack is a one-time purchase that adds render credits to the buyer's
personal balance (1 credit == 1 finished reel). Two rails sell the same packs:

* **Web (card)** -- a hosted Creem checkout. Creem is the merchant of record and
  charges in USD; the pack id, credit count and buyer id ride in the checkout
  metadata, and the existing ``POST /billing/webhook/creem`` handler grants the
  credits through :func:`app.services.billing.service.fulfill_purchase` (Redis
  SETNX + ledger-reason dedupe, so a replayed webhook never double-credits).
* **Store (App Store / Play)** -- the mobile app buys a consumable through
  RevenueCat, then asks the backend to redeem the store transaction. The backend
  re-reads the caller's RevenueCat subscriber record (App User ID == backend user
  id), confirms the transaction exists for the pack's store product, and grants
  the pack exactly once keyed on the transaction id.

Catalog source of truth: the locked pack credits/prices live in
:mod:`app.services.billing.plans` (Starter 30 / Pro 120), so ``/billing/plans``,
``/credit-packs`` and the Creem webhook can never disagree about how many
credits a pack is worth. Per-rail ids and the display-only TRY rate are read
from config / environment (never hardcoded secrets):

* Creem product id: ``config.creem.<pack>_product_id`` (existing plan key).
* Store product id: env ``REVENUECAT_CREDIT_PACK_<PACK>_PRODUCT_ID`` or
  ``config.revenuecat.credit_pack_<pack>_product_id``; defaults to
  ``menivor_credits_<credits>``. A default id grants nothing unless RevenueCat
  actually reports a paid transaction for it.
* Display rate: env ``CREDIT_PACK_TRY_PER_USD`` or
  ``config.app.credit_pack_try_per_usd``. Display only -- checkout currency stays
  USD because that is what the Creem products are priced in.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.parse import quote

from loguru import logger

from app.config import config

try:  # ``requests`` is optional at import/compile time.
    import requests

    _REQUESTS_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only without requests
    requests = None  # type: ignore[assignment]
    _REQUESTS_IMPORT_ERROR = exc


CHARGE_CURRENCY: str = "USD"
DISPLAY_CURRENCY_TRY: str = "TRY"
STORE_PROVIDER: str = "revenuecat"

_EVENT_KEY_PREFIX: str = "billing:evt"
_EVENT_TTL_SECONDS: int = 30 * 24 * 60 * 60
_REASON_MAX_LEN: int = 80
_DEFAULT_RC_BASE_URL: str = "https://api.revenuecat.com/v1"
_DEFAULT_RC_TIMEOUT_SECONDS: float = 5.0
_MAX_TRANSACTION_ID_LEN: int = 200


# ---------------------------------------------------------------------------
# Errors (mapped to HTTP status codes by the controller)
# ---------------------------------------------------------------------------


class CreditPackError(Exception):
    """Base error carrying the HTTP status the controller should return."""

    status_code: int = 400

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code


class PackNotFoundError(CreditPackError):
    status_code = 404


class RailNotConfiguredError(CreditPackError):
    """The requested payment rail has no credentials/product configured."""

    status_code = 503


class ProviderUnavailableError(CreditPackError):
    """The provider could not be reached or returned an untrustworthy answer."""

    status_code = 502


class TransactionNotFoundError(CreditPackError):
    """RevenueCat has no record (yet) of this transaction for the caller.

    404 on purpose: the mobile client keeps the purchase pending and retries,
    because a just-completed store purchase can take a moment to sync.
    """

    status_code = 404


class TransactionConflictError(CreditPackError):
    """The transaction exists but cannot be redeemed by this caller/pack."""

    status_code = 409


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CreditPack:
    """Immutable, JSON-safe description of one purchasable credit pack."""

    id: str
    label: str
    credits: int
    price_usd: float
    creem_product_id: str
    store_product_id: str

    @property
    def key(self) -> str:
        """Alias read by ``creem_client`` to fill the ``plan_key`` metadata."""
        return self.id


def _section(name: str) -> Mapping[str, Any]:
    section = getattr(config, name, None)
    if section is None:
        return {}
    try:
        return dict(section)
    except Exception:  # noqa: BLE001 - non-mapping guard
        return {}


def _store_product_id(pack_id: str, credits: int) -> str:
    env_value = os.getenv(f"REVENUECAT_CREDIT_PACK_{pack_id.upper()}_PRODUCT_ID", "")
    if env_value.strip():
        return env_value.strip()
    configured = str(
        _section("revenuecat").get(f"credit_pack_{pack_id}_product_id", "") or ""
    ).strip()
    return configured or f"menivor_credits_{credits}"


def list_packs() -> list[CreditPack]:
    """Return the purchasable packs in catalog order (free grant excluded)."""
    from app.services.billing.plans import list_plans

    return [
        CreditPack(
            id=plan.key,
            label=f"{plan.display_name} pack",
            credits=int(plan.credits),
            price_usd=float(plan.price_usd),
            creem_product_id=plan.creem_product_id,
            store_product_id=_store_product_id(plan.key, int(plan.credits)),
        )
        for plan in list_plans(purchasable_only=True)
    ]


def get_pack(pack_id: str) -> CreditPack:
    """Return the pack for ``pack_id`` (case-insensitive) or raise 404."""
    wanted = (pack_id or "").strip().lower()
    for pack in list_packs():
        if pack.id == wanted:
            return pack
    raise PackNotFoundError(f"unknown credit pack {pack_id!r}")


def get_pack_by_store_product(product_id: str) -> CreditPack:
    """Return the pack sold under store ``product_id`` or raise 400."""
    wanted = (product_id or "").strip()
    for pack in list_packs():
        if pack.store_product_id == wanted:
            return pack
    raise CreditPackError(f"store product {product_id!r} is not a credit pack", 400)


def try_per_usd() -> float | None:
    """Configured display-only USD->TRY rate, or ``None`` when unset/invalid."""
    raw: Any = os.getenv("CREDIT_PACK_TRY_PER_USD", "") or _section("app").get(
        "credit_pack_try_per_usd"
    )
    if raw in (None, ""):
        return None
    try:
        rate = float(raw)
    except (TypeError, ValueError):
        logger.warning(f"credit packs: ignoring non-numeric TRY rate {raw!r}")
        return None
    if not math.isfinite(rate) or rate <= 0:
        return None
    return rate


# ---------------------------------------------------------------------------
# Rail availability
# ---------------------------------------------------------------------------


def _creem_success_url() -> str:
    url = str(_section("creem").get("success_url", "") or "").strip()
    return url or str(_section("stripe").get("success_url", "") or "").strip()


def web_rail_ready(pack: CreditPack) -> bool:
    """True when a Creem card checkout can be opened for ``pack``."""
    api_key = str(_section("creem").get("api_key", "") or "").strip()
    return bool(api_key and pack.creem_product_id and _creem_success_url())


def store_rail_ready() -> bool:
    """True when the server can verify store purchases through RevenueCat."""
    return bool(str(_section("revenuecat").get("secret_api_key", "") or "").strip())


def serialize_pack(pack: CreditPack, currency: str | None = None) -> dict[str, Any]:
    """JSON-safe catalog row; adds a TRY display price when asked and configured."""
    row: dict[str, Any] = {
        "id": pack.id,
        "label": pack.label,
        "credits": pack.credits,
        "price_usd": pack.price_usd,
        "charge_currency": CHARGE_CURRENCY,
        "store_product_id": pack.store_product_id,
        "web_checkout_available": web_rail_ready(pack),
        "store_purchase_available": store_rail_ready(),
    }
    if (currency or "").strip().upper() == DISPLAY_CURRENCY_TRY:
        rate = try_per_usd()
        row["display_price"] = (
            None
            if rate is None
            else {
                "currency": DISPLAY_CURRENCY_TRY,
                "amount": round(pack.price_usd * rate, 2),
                "rate": rate,
                "approximate": True,
            }
        )
    return row


# ---------------------------------------------------------------------------
# Web rail: Creem checkout
# ---------------------------------------------------------------------------


def create_web_checkout(pack: CreditPack, user_id: str, user_email: str) -> dict[str, Any]:
    """Open a hosted Creem checkout for ``pack``; credits land via the webhook."""
    if not web_rail_ready(pack):
        raise RailNotConfiguredError(
            "card checkout for credit packs is not configured on this server"
        )
    from app.services.billing import creem_client

    try:
        result = creem_client.create_checkout_session(
            {"id": user_id, "email": user_email or ""}, pack
        )
    except ValueError as exc:
        raise CreditPackError(f"invalid checkout request: {exc}", 400) from exc
    except Exception as exc:  # noqa: BLE001 - provider/transport failure
        logger.error(f"credit packs: Creem checkout failed pack={pack.id}: {exc}")
        raise ProviderUnavailableError("payment provider is unavailable") from exc

    checkout_url = str(result.get("checkout_url", "") or "").strip()
    if not checkout_url:
        raise ProviderUnavailableError("payment provider returned no checkout url")
    return {
        "provider": "creem",
        "pack_id": pack.id,
        "credits": pack.credits,
        "price_usd": pack.price_usd,
        "charge_currency": CHARGE_CURRENCY,
        "checkout_url": checkout_url,
        "reference": str(result.get("session_id", "") or ""),
    }


# ---------------------------------------------------------------------------
# Store rail: RevenueCat verification + idempotent grant
# ---------------------------------------------------------------------------


def _allow_sandbox() -> bool:
    raw = os.getenv("REVENUECAT_ALLOW_SANDBOX_PURCHASES", "")
    if raw.strip():
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    # App Review and TestFlight purchase in the sandbox; refusing them would
    # fail review. Operators can turn this off once the app is live.
    return bool(_section("revenuecat").get("allow_sandbox_purchases", True))


def _fetch_subscriber(
    app_user_id: str, request_get: Callable[..., Any] | None = None
) -> dict[str, Any]:
    section = _section("revenuecat")
    secret = str(section.get("secret_api_key", "") or "").strip()
    if not secret:
        raise RailNotConfiguredError("store purchase verification is not configured")
    base_url = str(section.get("api_base_url", _DEFAULT_RC_BASE_URL) or "").rstrip("/")
    if not base_url.startswith("https://"):
        raise RailNotConfiguredError("RevenueCat API URL must use HTTPS")
    try:
        timeout = float(section.get("timeout_seconds", _DEFAULT_RC_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        timeout = _DEFAULT_RC_TIMEOUT_SECONDS

    if request_get is None:
        if requests is None:
            raise RailNotConfiguredError(
                f"requests is required for RevenueCat ({_REQUESTS_IMPORT_ERROR})"
            )
        request_get = requests.get

    url = f"{base_url}/subscribers/{quote(app_user_id, safe='')}"
    try:
        response = request_get(
            url,
            headers={"Accept": "application/json", "Authorization": f"Bearer {secret}"},
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 - transport implementations vary
        raise ProviderUnavailableError("store verification is unavailable") from exc
    if int(getattr(response, "status_code", 0) or 0) not in {200, 201}:
        raise ProviderUnavailableError("store verification returned an error")
    try:
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        raise ProviderUnavailableError("store verification returned invalid JSON") from exc
    subscriber = payload.get("subscriber") if isinstance(payload, dict) else None
    if not isinstance(subscriber, dict):
        raise ProviderUnavailableError("store verification returned a malformed body")
    return subscriber


def find_store_transaction(
    subscriber: Mapping[str, Any], product_id: str, transaction_id: str
) -> dict[str, Any] | None:
    """Locate ``transaction_id`` among the subscriber's one-time purchases.

    RevenueCat lists consumables under ``non_subscriptions[<product_id>]``; each
    row carries RevenueCat's ``id`` and the store's ``store_transaction_id``. The
    SDK hands the client one of the two depending on platform, so both match.
    """
    purchases = subscriber.get("non_subscriptions")
    if not isinstance(purchases, dict):
        return None
    rows = purchases.get(product_id)
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        ids = {str(row.get("id") or ""), str(row.get("store_transaction_id") or "")}
        if transaction_id in ids:
            return row
    return None


def _store_reason(transaction_id: str) -> str:
    from app.services.billing.service import _fit_reason

    return _fit_reason(
        f"purchase:{STORE_PROVIDER}:{transaction_id}", STORE_PROVIDER, transaction_id
    )


def _redemption_owner(reason: str) -> str | None:
    """User id that already holds a ledger row for ``reason`` (any user)."""
    from sqlalchemy import select

    from app.models.db.base import get_session
    from app.models.db.models import CreditLedger

    with get_session() as session:
        row = session.execute(
            select(CreditLedger.user_id).where(CreditLedger.reason == reason).limit(1)
        ).first()
    return None if row is None else str(row[0] or "")


def redeem_store_purchase(
    *,
    user_id: str,
    product_id: str,
    transaction_id: str,
    expected_pack: CreditPack | None = None,
    request_get: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Verify a store transaction with RevenueCat and grant its pack once.

    Returns ``{"pack_id", "credits_granted", "already_redeemed", "balance"}``.
    ``credits_granted`` is the pack size on both the first redemption and an
    idempotent replay (``already_redeemed`` tells them apart).
    """
    user_id = (user_id or "").strip()
    transaction_id = (transaction_id or "").strip()
    if not user_id:
        raise CreditPackError("a signed-in user is required", 401)
    if not transaction_id or len(transaction_id) > _MAX_TRANSACTION_ID_LEN:
        raise CreditPackError("transaction_id is required", 422)

    pack = get_pack_by_store_product(product_id)
    if expected_pack is not None and expected_pack.id != pack.id:
        raise CreditPackError(
            f"store product {product_id!r} does not belong to pack {expected_pack.id!r}",
            400,
        )

    reason = _store_reason(transaction_id)
    owner = _redemption_owner(reason)
    if owner is not None and owner != user_id:
        raise TransactionConflictError("this purchase was redeemed by another account")

    from app.services.billing import service

    if owner == user_id:
        return {
            "pack_id": pack.id,
            "credits_granted": pack.credits,
            "already_redeemed": True,
            "balance": service._current_balance(user_id),
        }

    subscriber = _fetch_subscriber(user_id, request_get)
    row = find_store_transaction(subscriber, pack.store_product_id, transaction_id)
    if row is None:
        raise TransactionNotFoundError(
            "the store has not reported this purchase for your account yet"
        )
    if bool(row.get("is_sandbox")) and not _allow_sandbox():
        raise TransactionConflictError("sandbox purchases are not redeemable here")

    balance = service._idempotent_grant(
        idempotency_key=f"{_EVENT_KEY_PREFIX}:{STORE_PROVIDER}:{transaction_id}",
        user_id=user_id,
        credits=pack.credits,
        reason=reason,
        ttl_seconds=_EVENT_TTL_SECONDS,
    )
    service._rally_credits_purchased(user_id, STORE_PROVIDER, transaction_id, pack.credits, None)
    logger.info(
        f"credit packs: store redemption user={user_id} pack={pack.id} "
        f"store={row.get('store', '-')} sandbox={bool(row.get('is_sandbox'))}"
    )
    return {
        "pack_id": pack.id,
        "credits_granted": pack.credits,
        "already_redeemed": False,
        "balance": int(balance),
    }


__all__ = [
    "CHARGE_CURRENCY",
    "CreditPack",
    "CreditPackError",
    "PackNotFoundError",
    "ProviderUnavailableError",
    "RailNotConfiguredError",
    "TransactionConflictError",
    "TransactionNotFoundError",
    "create_web_checkout",
    "find_store_transaction",
    "get_pack",
    "get_pack_by_store_product",
    "list_packs",
    "redeem_store_purchase",
    "serialize_pack",
    "store_rail_ready",
    "try_per_usd",
    "web_rail_ready",
]
