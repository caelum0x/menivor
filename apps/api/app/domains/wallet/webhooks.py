"""Wallet payment webhooks — verify provider events and grant credit once.

The ONLY path that adds spendable wallet credit is a verified payment webhook
(PROVIDER_MARKETPLACE_PLAN.md §3), never a browser redirect. This module wraps
provider-specific signed-webhook verification, recovers ``payment_intent_id``
from the event metadata, and calls :meth:`WalletService.confirm_intent` (which is
idempotent — a duplicate delivery can never double-grant).

Verification is INJECTABLE (``verify_fn``) so the security-critical grant logic is
unit-testable without the real Creem secret; the router wires the real verifier.
"""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger
from sqlalchemy.orm import Session

from app.domains.wallet.service import WalletError, WalletService

# Creem event types that fulfil a completed one-time purchase. A tolerant
# "contains" check also accepts close variants across Creem field naming.
_COMPLETED_EVENTS = {
    "creem": {
        "checkout.completed",
        "checkout.session.completed",
        "payment.succeeded",
    },
    "stripe": {"checkout.session.completed"},
}


def _event_get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    getter = getattr(obj, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except TypeError:  # pragma: no cover - non-standard get
            pass
    return getattr(obj, key, default)


def _event_type(event: Any) -> str:
    return str(
        _event_get(event, "eventType", "")
        or _event_get(event, "event_type", "")
        or _event_get(event, "type", "")
        or ""
    ).strip()


def _event_object(event: Any) -> Any:
    """Resolve the resource object across Creem/Stripe-like envelopes."""
    obj = _event_get(event, "object", None)
    if obj:
        return obj
    data = _event_get(event, "data", None)
    if isinstance(data, dict):
        return _event_get(data, "object", data)
    return event


def _extract_intent_id(event: Any) -> str:
    """Recover the ReelForge payment_intent_id from event/object metadata."""
    obj = _event_object(event)
    for source in (obj, event):
        metadata = _event_get(source, "metadata", None)
        if isinstance(metadata, dict):
            intent_id = metadata.get("payment_intent_id") or metadata.get(
                "wallet_intent_id"
            )
            if intent_id:
                return str(intent_id)
    return ""


def _extract_mint_account_id(event: Any) -> str:
    """Recover the Mint account echoed in authenticated Creem metadata."""
    obj = _event_object(event)
    for source in (obj, event):
        metadata = _event_get(source, "metadata", None)
        if isinstance(metadata, dict):
            account_id = metadata.get("mint_account_id") or metadata.get("account_id")
            if account_id:
                return str(account_id).strip()
    return ""


def _metadata(event: Any) -> dict[str, Any]:
    obj = _event_object(event)
    for source in (obj, event):
        value = _event_get(source, "metadata", None)
        if isinstance(value, dict):
            return value
    return {}


def _is_completed(provider: str, event_type: str) -> bool:
    return event_type.strip().lower() in _COMPLETED_EVENTS.get(provider, set())


def _verify_event(
    provider: str,
    payload: bytes,
    headers: dict[str, str],
    verify_fn: Callable[[bytes, str], Any] | None,
) -> Any:
    if provider == "creem":
        if verify_fn is None:  # pragma: no cover - real verifier needs a secret
            from app.services.billing import creem_client

            verify_fn = creem_client.verify_and_parse_webhook
        return verify_fn(payload, headers.get("creem-signature", ""))
    if provider == "stripe":
        if verify_fn is None:  # pragma: no cover - real verifier needs a secret
            from app.services.billing import stripe_client

            verify_fn = stripe_client.verify_and_parse_webhook
        return verify_fn(payload, headers.get("stripe-signature", ""))
    raise ValueError(f"unsupported wallet payment provider: {provider}")


def _validate_event_binding(provider: str, intent: Any, event: Any) -> str:
    """Bind a verified event to the exact checkout intent it is allowed to fund."""
    if str(getattr(intent, "payment_provider", "") or "").lower() != provider:
        raise ValueError("wallet webhook provider does not match payment intent")

    obj = _event_object(event)
    provider_ref = str(_event_get(obj, "id", "") or "").strip()
    expected_ref = str(getattr(intent, "provider_ref", "") or "").strip()
    if not provider_ref:
        raise ValueError("wallet webhook has no provider checkout reference")
    if expected_ref and provider_ref != expected_ref:
        raise ValueError("wallet webhook checkout reference does not match intent")

    metadata = _metadata(event)
    kind = str(metadata.get("kind", "") or "").strip()
    if kind and kind != "wallet_topup":
        raise ValueError("wallet webhook is not a wallet top-up")

    expected_credit = int(getattr(intent, "credit_micros", 0) or 0)
    metadata_credit = str(metadata.get("credit_micros", "") or "").strip()
    if metadata_credit:
        try:
            credit = int(metadata_credit)
        except ValueError as exc:
            raise ValueError("wallet webhook credit amount is malformed") from exc
        if credit != expected_credit:
            raise ValueError("wallet webhook credit amount does not match intent")

    expected_total = int(getattr(intent, "total_charge_micros", 0) or 0)
    metadata_total = str(metadata.get("total_charge_micros", "") or "").strip()
    if metadata_total:
        try:
            total = int(metadata_total)
        except ValueError as exc:
            raise ValueError("wallet webhook charge amount is malformed") from exc
        if total != expected_total:
            raise ValueError("wallet webhook charge amount does not match intent")

    currency = str(
        _event_get(obj, "currency", "") or metadata.get("currency", "") or ""
    ).strip()
    if currency and currency.upper() != str(getattr(intent, "currency", "USD")).upper():
        raise ValueError("wallet webhook currency does not match intent")

    # Stripe reports the final Checkout amount in cents. Creem also commonly
    # exposes ``amount`` in minor units; validate either when present.
    provider_cents = _event_get(obj, "amount_total", None)
    if provider_cents is None:
        provider_cents = _event_get(obj, "amount", None)
    if provider_cents is not None:
        try:
            paid_micros = int(provider_cents) * 10_000
        except (TypeError, ValueError) as exc:
            raise ValueError("wallet webhook paid amount is malformed") from exc
        if paid_micros != expected_total:
            raise ValueError("wallet webhook paid amount does not match intent")
    return provider_ref


def process_wallet_webhook(
    session: Session,
    provider: str,
    payload: bytes,
    headers: dict[str, str],
    *,
    verify_fn: Callable[[bytes, str], Any] | None = None,
    mint_client: Any | None = None,
    correlation_id: str = "",
) -> dict:
    """Verify one supported provider event and grant its bound intent once."""
    provider = str(provider).strip().lower()
    normalized_headers = {str(k).lower(): str(v) for k, v in headers.items()}
    if provider == DODO:
        return _process_dodo_webhook(
            session, payload, normalized_headers, mint_client=mint_client,
            correlation_id=correlation_id,
        )
    event = _verify_event(provider, payload, normalized_headers, verify_fn)
    event_type = _event_type(event)
    if not _is_completed(provider, event_type):
        logger.info(
            f"wallet {provider} webhook ignored event: {event_type or '<none>'}"
        )
        return {"status": "ignored", "event_type": event_type, "provider": provider}

    intent_id = _extract_intent_id(event)
    if not intent_id:
        raise ValueError("wallet webhook event has no payment_intent_id metadata")

    service = WalletService(session)
    intent = service._repo.get_intent(intent_id)
    if intent is None:
        raise WalletError(404, "payment intent not found")
    provider_ref = _validate_event_binding(provider, intent, event)
    return _grant_intent(
        service, intent, provider, provider_ref, _extract_mint_account_id(event),
        mint_client=mint_client, correlation_id=correlation_id,
    )


def _grant_intent(
    service: WalletService,
    intent: Any,
    provider: str,
    provider_ref: str,
    event_account: str,
    *,
    mint_client: Any | None,
    correlation_id: str,
) -> dict:
    """Grant a verified, bound intent once (local ledger or the Mint rail)."""
    intent_meta = intent.meta if isinstance(intent.meta, dict) else {}
    settlement_rail = str(intent_meta.get("settlement_rail", "local") or "local")

    external_receipt: dict | None = None
    if settlement_rail == "mint":
        expected_account = str(intent_meta.get("mint_account_id", "") or "").strip()
        if not expected_account or event_account != expected_account:
            raise ValueError(
                "wallet webhook Mint account metadata does not match intent"
            )
        if mint_client is None:
            from app.domains.wallet.mint_client import mint_client_from_config

            mint_client = mint_client_from_config()
        if mint_client is None:
            raise WalletError(502, "mint client is not configured")
        try:
            external_receipt = mint_client.mint_deposit(
                expected_account,
                int(intent.credit_micros),
                f"{provider}:{provider_ref}",
                f"wallet:{intent.id}",
            )
        except Exception as exc:  # noqa: BLE001 - normalize the money boundary
            status = int(getattr(exc, "status_code", 502) or 502)
            message = str(getattr(exc, "message", "") or "mint deposit failed")
            raise WalletError(status, message) from exc

    view = service.confirm_intent(
        intent.id,
        provider_ref=provider_ref,
        correlation_id=correlation_id,
        credit_local=settlement_rail != "mint",
        external_receipt=external_receipt,
    )
    _rally_wallet_purchase(intent, provider)
    return {
        "status": "granted",
        "provider": provider,
        "payment_intent_id": intent.id,
        "intent": view,
    }


def _rally_wallet_purchase(intent: Any, provider: str) -> None:
    """Rally ``credits_purchased`` for a wallet top-up (no-op unless configured)."""
    user_id = str(getattr(intent, "user_id", "") or "").strip()
    if not user_id:
        return
    try:
        from app.integrations.rally import track_credits_purchased

        track_credits_purchased(
            user_id,
            provider=f"wallet_{provider}",
            reference=str(intent.id),
            credits=0,
            properties_extra={"credit_micros": int(getattr(intent, "credit_micros", 0) or 0)},
        )
    except Exception as exc:  # noqa: BLE001 - lifecycle events never fail a grant
        logger.debug(f"rally wallet purchase event skipped: {exc}")


def process_creem_wallet_webhook(
    session: Session,
    payload: bytes,
    signature: str,
    *,
    verify_fn: Callable[[bytes, str], Any] | None = None,
    mint_client: Any | None = None,
    correlation_id: str = "",
) -> dict:
    """Verify a Creem webhook and grant the matching intent's credit exactly once.

    Returns a small status dict. Raises ``ValueError`` on a bad signature /
    malformed body (caller returns 400) and :class:`WalletError` for an unknown
    intent (404). A non-purchase event is acknowledged as ``ignored`` so Creem
    stops retrying it.
    """
    return process_wallet_webhook(
        session,
        "creem",
        payload,
        {"creem-signature": signature},
        verify_fn=verify_fn,
        mint_client=mint_client,
        correlation_id=correlation_id,
    )


# --------------------------------------------------------------------------- #
# Dodo Payments (MN4). The shared Dodo webhook (dodo_billing.handle_webhook)
# verifies the signature and routes ``metadata.kind == wallet_topup`` here.
# --------------------------------------------------------------------------- #
DODO: str = "dodo"
DODO_WALLET_PRODUCT_ENV: str = "DODO_PRODUCT_ID_WALLET_TOPUP"
_DODO_REVERSAL_REASON: str = "dodo_reversal"


def dodo_wallet_product_id() -> str:
    """The Dodo pay-what-you-want product that carries wallet top-ups."""
    import os

    from app.config import config

    section = getattr(config, "dodo", None) or {}
    configured = str(dict(section).get("wallet_topup_product_id", "") or "").strip()
    return configured or (os.environ.get(DODO_WALLET_PRODUCT_ENV) or "").strip()


def dodo_wallet_available() -> bool:
    """True when a Dodo wallet top-up can be sold (key + product mapped)."""
    from app.services.billing import dodo_client

    return dodo_client.is_configured() and bool(dodo_wallet_product_id())


def create_dodo_wallet_checkout_session(intent: Any) -> dict[str, str]:
    """Hosted Dodo checkout charging exactly the intent's quoted total."""
    from app.services.billing import dodo_client

    product_id = dodo_wallet_product_id()
    if not product_id:
        raise RuntimeError(f"Dodo wallet top-up product is not configured: set {DODO_WALLET_PRODUCT_ENV}.")
    total_micros = int(getattr(intent, "total_charge_micros", 0) or 0)
    if total_micros <= 0 or total_micros % 10_000 != 0:
        raise ValueError("wallet total charge must be a positive whole number of cents")
    meta = intent.meta if isinstance(getattr(intent, "meta", None), dict) else {}
    metadata = {
        "kind": "wallet_topup",
        "payment_intent_id": str(intent.id),
        "user_id": str(getattr(intent, "user_id", "") or ""),
        "credit_micros": str(int(intent.credit_micros)),
        "total_charge_micros": str(total_micros),
        "currency": str(getattr(intent, "currency", "USD") or "USD"),
        "mint_account_id": str(meta.get("mint_account_id", "") or ""),
    }
    body = {
        "product_cart": [{"product_id": product_id, "quantity": 1, "amount": total_micros // 10_000}],
        "return_url": dodo_client.return_url("/wallet"),
        "metadata": {k: v for k, v in metadata.items() if v},
    }
    data = dodo_client.request("POST", "/checkouts", body=body)
    session_id = str(data.get("session_id", "") or "").strip()
    url = str(data.get("checkout_url", "") or "").strip()
    if not session_id or not url:
        raise RuntimeError("Dodo returned a wallet checkout without a session id / url.")
    return {"checkout_url": url, "session_id": session_id}


def _validate_dodo_binding(intent: Any, data: dict, view: dict) -> str:
    """Bind a verified Dodo payment to the one intent it may fund."""
    if str(getattr(intent, "payment_provider", "") or "").lower() != DODO:
        raise ValueError("wallet webhook provider does not match payment intent")
    if view["status"] != "succeeded":
        raise ValueError("wallet payment has not succeeded")
    product_id = dodo_wallet_product_id()
    if not product_id or product_id not in view["product_ids"]:
        raise ValueError("wallet payment is not the wallet top-up product")
    metadata = view["metadata"]
    for key in ("credit_micros", "total_charge_micros"):
        raw = str(metadata.get(key, "") or "").strip()
        if raw and raw != str(int(getattr(intent, key, 0) or 0)):
            raise ValueError(f"wallet webhook {key} does not match intent")
    currency = str(data.get("currency", "") or "").strip().upper()
    if currency and currency != str(getattr(intent, "currency", "USD")).upper():
        raise ValueError("wallet webhook currency does not match intent")
    expected = int(intent.total_charge_micros) // 10_000
    total = int(data.get("total_amount") or 0)
    tax = int(data.get("tax") or 0)
    if total not in (expected, expected + tax) or total <= 0:
        raise ValueError("wallet webhook paid amount does not match intent")
    return view["payment_id"]


def process_dodo_wallet_payment(
    session: Session, data: dict, *, correlation_id: str = "", mint_client: Any | None = None
) -> dict:
    """Grant a Dodo wallet top-up once (signature verified by the caller)."""
    from app.services.billing import dodo_client

    view = dodo_client.payment_view(data)
    intent_id = str(view["metadata"].get("payment_intent_id", "") or "")
    if not intent_id:
        raise ValueError("wallet payment has no payment_intent_id metadata")
    service = WalletService(session)
    intent = service._repo.get_intent(intent_id)
    if intent is None:
        raise WalletError(404, "payment intent not found")
    payment_id = _validate_dodo_binding(intent, data, view)
    account = str(view["metadata"].get("mint_account_id", "") or "").strip()
    return _grant_intent(
        service, intent, DODO, payment_id, account,
        mint_client=mint_client, correlation_id=correlation_id,
    )


def _process_dodo_webhook(
    session: Session, payload: bytes, headers: dict[str, str], *,
    mint_client: Any | None, correlation_id: str,
) -> dict:
    """``POST /wallet/webhooks/dodo``: verify (Standard Webhooks), then grant."""
    from app.services.billing import dodo_client

    event = dodo_client.verify_and_parse_webhook(payload, headers)
    event_type = dodo_client.event_type(event)
    data = dodo_client.event_data(event)
    kind = str((data.get("metadata") or {}).get("kind", "") or "")
    if event_type != dodo_client.PAYMENT_SUCCEEDED or kind != "wallet_topup":
        return {"status": "ignored", "event_type": event_type, "provider": DODO}
    return process_dodo_wallet_payment(
        session, data, correlation_id=correlation_id, mint_client=mint_client
    )


def reverse_dodo_payment(payment_id: str, *, cause: str = "refund") -> dict:
    """Refund or lost dispute of a Dodo top-up: remove its credit once.

    The wallet never goes below 0; any part already spent is returned as
    ``owed_micros`` (recorded on the entry) so the caller alerts the owner.
    """
    from sqlalchemy import select

    from app.models.db.base import get_session
    from app.models.db.marketplace import PaymentIntent, WalletLedgerEntry
    from app.domains.wallet.repository import ENTRY_ADJUSTMENT

    with get_session() as session:
        intent = session.execute(
            select(PaymentIntent).where(
                PaymentIntent.payment_provider == DODO, PaymentIntent.provider_ref == payment_id
            )
        ).scalars().first()
        if intent is None or intent.status != "confirmed":
            return {"debited": 0}
        service = WalletService(session)
        account = service._repo._lock_account(intent.account_id)
        done = session.execute(
            select(WalletLedgerEntry.id).where(
                WalletLedgerEntry.payment_intent_id == intent.id,
                WalletLedgerEntry.reason == _DODO_REVERSAL_REASON,
            )
        ).first()
        if done is not None:
            return {"debited": 0, "duplicate": 1}
        mint = str((intent.meta or {}).get("settlement_rail", "")) == "mint"
        credit = 0 if mint else int(intent.credit_micros)
        amount = max(0, min(credit, int(account.available_micros)))
        owed_micros = int(intent.credit_micros) - amount
        service._repo.append_entry(
            intent.account_id, entry_type=ENTRY_ADJUSTMENT, reason=_DODO_REVERSAL_REASON,
            available_delta=-amount, payment_intent_id=intent.id,
            meta={"cause": cause, "owed_micros": owed_micros, "mint": mint},
        )
    return {"debited": amount, "owed_micros": owed_micros, "mint": int(mint)}


__all__ = [
    "create_dodo_wallet_checkout_session",
    "dodo_wallet_available",
    "dodo_wallet_product_id",
    "process_creem_wallet_webhook",
    "process_dodo_wallet_payment",
    "process_wallet_webhook",
    "reverse_dodo_payment",
]
