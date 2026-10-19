"""iyzico checkout-form client for ReelForge credit purchases.

Turkish-market (TR local cards) payment provider adapter. This module is a
pure transport/parsing layer over the official ``iyzipay`` SDK: it builds a
CheckoutForm, initializes it, and later retrieves + verifies the payment
status. It NEVER touches the credit ledger — all credit writes (grant/debit)
and webhook idempotency (Redis SETNX on the provider token) are owned by the
billing service / webhook layer.

Secrets come exclusively from ``config.iyzico`` (``api_key``, ``secret_key``,
``base_url``) — nothing is hardcoded. The ``iyzipay`` import is guarded so this
file still parses (``py_compile``) when the SDK is not installed.

Provenance/idempotency contract:

* ``conversationId`` encodes ``rf:<user_id>:<plan_key>:<credits>`` so the
  webhook can recover who bought what from a stateless ``retrieve``.
* The webhook uses the ``token`` returned here for Redis SETNX idempotency and
  encodes the ledger reason as ``purchase:iyzico:<token>``.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from loguru import logger

from app.config import config
from app.services.billing.plans import Plan, get_plan

# Guard the third-party import so the module still parses without the SDK.
try:  # pragma: no cover - import guard
    import iyzipay
except Exception:  # noqa: BLE001 - any import failure disables the provider
    iyzipay = None  # type: ignore[assignment]


# iyzico defaults tuned for the Turkish market. base_url falls back to the
# sandbox host so a misconfigured prod key never silently hits live rails.
_DEFAULT_BASE_URL: str = "https://sandbox-api.iyzipay.com"
_DEFAULT_CURRENCY: str = "TRY"
_DEFAULT_LOCALE: str = "tr"

# Non-secret placeholders used only when the user record lacks the field.
# iyzico requires these buyer fields to be non-empty; real values should come
# from the user profile / KYC when available.
_DEFAULT_GSM: str = "+905350000000"
_DEFAULT_IDENTITY: str = "11111111111"
_DEFAULT_CITY: str = "Istanbul"
_DEFAULT_COUNTRY: str = "Turkey"
_DEFAULT_ADDRESS: str = "ReelForge digital delivery"
_DEFAULT_ZIP: str = "34000"
_DEFAULT_IP: str = "127.0.0.1"

# conversationId provenance envelope: rf:<user_id>:<plan_key>:<credits>.
_CONV_PREFIX: str = "rf"


# --------------------------------------------------------------------------- #
# Config access (all guarded — sections may not be wired yet in a fork)
# --------------------------------------------------------------------------- #
def _iyzico_section() -> Mapping[str, Any]:
    """Return the ``config.iyzico`` section as a mapping (empty if absent)."""
    section = getattr(config, "iyzico", None)
    return section if isinstance(section, Mapping) else {}


def _iyzico_options() -> dict[str, str]:
    """Build the ``{api_key, secret_key, base_url}`` options for the SDK.

    Raises:
        RuntimeError: when the required secrets are not configured.
    """
    section = _iyzico_section()
    api_key = str(section.get("api_key", "") or "")
    secret_key = str(section.get("secret_key", "") or "")
    base_url = str(section.get("base_url", "") or "") or _DEFAULT_BASE_URL
    if not api_key or not secret_key:
        raise RuntimeError(
            "iyzico is not configured: set iyzico.api_key and iyzico.secret_key"
        )
    return {"api_key": api_key, "secret_key": secret_key, "base_url": base_url}


def _currency() -> str:
    """Resolve the checkout currency (defaults to TRY for the TR market)."""
    return str(_iyzico_section().get("currency", "") or _DEFAULT_CURRENCY)


def _callback_url() -> str:
    """Return the configured post-payment callback URL.

    Raises:
        RuntimeError: when ``iyzico.callback_url`` is not configured — iyzico
        rejects the CheckoutForm init without it.
    """
    callback = str(_iyzico_section().get("callback_url", "") or "")
    if not callback:
        raise RuntimeError("iyzico is not configured: set iyzico.callback_url")
    return callback


# --------------------------------------------------------------------------- #
# Small value helpers
# --------------------------------------------------------------------------- #
def _attr(obj: Any, *names: str, default: Any = "") -> Any:
    """Read the first present attribute/key from an object or mapping.

    Supports both ORM models (attribute access) and plain dicts so callers can
    pass a ``User`` row or a serialized user without branching.
    """
    for name in names:
        if isinstance(obj, Mapping):
            value = obj.get(name)
        else:
            value = getattr(obj, name, None)
        if value is not None and value != "":
            return value
    return default


def _split_name(full_name: str, email: str) -> tuple[str, str]:
    """Split a display name into (name, surname) with sensible fallbacks."""
    full = str(full_name or "").strip()
    if not full:
        full = str(email or "").split("@", 1)[0].strip() or "ReelForge"
    parts = full.split()
    if len(parts) == 1:
        return parts[0], parts[0]
    return " ".join(parts[:-1]), parts[-1]


def _resolve_plan(plan: Any) -> Plan:
    """Coerce a Plan / plan-key string / mapping / object into a :class:`Plan`.

    Raises:
        ValueError: when the plan cannot be resolved from the locked catalog.
    """
    if isinstance(plan, Plan):
        return plan
    if isinstance(plan, str):
        key: Any = plan
    elif isinstance(plan, Mapping):
        key = plan.get("key") or plan.get("plan_key")
    else:
        key = getattr(plan, "key", None) or getattr(plan, "plan_key", None)
    resolved = get_plan(str(key)) if key else None
    if resolved is None:
        raise ValueError(f"unknown billing plan: {key!r}")
    return resolved


def _read_json(raw: Any) -> dict[str, Any]:
    """Decode an iyzipay SDK response into a plain dict.

    The SDK returns an ``http.client.HTTPResponse``-like object exposing
    ``read()``; older/newer versions may hand back raw bytes/str. All shapes are
    tolerated and malformed bodies decode to ``{}`` (never raise).
    """
    if raw is None:
        return {}
    content: Any
    if isinstance(raw, (bytes, bytearray)):
        content = bytes(raw).decode("utf-8", errors="replace")
    elif isinstance(raw, str):
        content = raw
    elif hasattr(raw, "read"):
        body = raw.read()
        content = body.decode("utf-8", errors="replace") if isinstance(
            body, (bytes, bytearray)
        ) else str(body)
    else:
        content = str(raw)
    try:
        parsed = json.loads(content)
    except (TypeError, ValueError):
        logger.error("iyzico: could not parse response body as JSON")
        return {}
    return parsed if isinstance(parsed, dict) else {}


# --------------------------------------------------------------------------- #
# Provenance encoding (stateless recovery of buyer + plan from conversationId)
# --------------------------------------------------------------------------- #
def _encode_conversation_id(user_id: str, plan_key: str, credits: int) -> str:
    """Encode buyer + plan provenance into a single conversationId string."""
    return f"{_CONV_PREFIX}:{user_id}:{plan_key}:{int(credits)}"


def _decode_conversation_id(conversation_id: str) -> tuple[str, str, int]:
    """Recover ``(user_id, plan_key, credits)`` from a conversationId.

    Returns empty/zero fields when the id is missing or not a ReelForge
    envelope (so a foreign conversationId simply yields ``paid`` with no
    provenance rather than raising).
    """
    parts = str(conversation_id or "").split(":")
    if len(parts) == 4 and parts[0] == _CONV_PREFIX:
        user_id, plan_key = parts[1], parts[2]
        try:
            credits = int(parts[3])
        except (TypeError, ValueError):
            credits = 0
        return user_id, plan_key, credits
    return "", "", 0


# --------------------------------------------------------------------------- #
# Request builders
# --------------------------------------------------------------------------- #
def _build_buyer(user: Any, user_id: str, email: str) -> dict[str, Any]:
    """Build the iyzico ``buyer`` block from a user record (TR-friendly)."""
    name, surname = _split_name(_attr(user, "display_name", "name"), email)
    return {
        "id": user_id,
        "name": name,
        "surname": surname,
        "gsmNumber": str(_attr(user, "gsm_number", "phone", default=_DEFAULT_GSM)),
        "email": email or f"{user_id}@reelforge.local",
        "identityNumber": str(
            _attr(user, "identity_number", default=_DEFAULT_IDENTITY)
        ),
        "registrationAddress": _DEFAULT_ADDRESS,
        "ip": str(_attr(user, "ip", default=_DEFAULT_IP)),
        "city": str(_attr(user, "city", default=_DEFAULT_CITY)),
        "country": _DEFAULT_COUNTRY,
        "zipCode": str(_attr(user, "zip_code", default=_DEFAULT_ZIP)),
    }


def _build_address(contact_name: str) -> dict[str, str]:
    """Build a generic billing/shipping address for a digital (virtual) good."""
    return {
        "contactName": contact_name or "ReelForge Customer",
        "city": _DEFAULT_CITY,
        "country": _DEFAULT_COUNTRY,
        "address": _DEFAULT_ADDRESS,
        "zipCode": _DEFAULT_ZIP,
    }


def _build_basket_item(plan: Plan, price: str) -> dict[str, str]:
    """Build the single VIRTUAL basket item for a credit pack."""
    return {
        "id": f"credits-{plan.key}",
        "name": f"ReelForge {plan.display_name} ({plan.credits} credits)",
        "category1": "Digital Credits",
        "itemType": "VIRTUAL",
        "price": price,
    }


def _build_checkout_request(
    user: Any, plan: Plan, conversation_id: str
) -> dict[str, Any]:
    """Assemble the full CheckoutFormInitialize request payload."""
    user_id = str(_attr(user, "id", "user_id"))
    email = str(_attr(user, "email"))
    price = str(plan.iyzico_amount)
    contact_name = " ".join(_split_name(_attr(user, "display_name", "name"), email))
    return {
        "locale": _DEFAULT_LOCALE,
        "conversationId": conversation_id,
        "price": price,
        "paidPrice": price,
        "currency": _currency(),
        "basketId": f"reelforge-{plan.key}",
        "paymentGroup": "PRODUCT",
        "callbackUrl": _callback_url(),
        "enabledInstallments": ["1", "2", "3", "6", "9"],
        "buyer": _build_buyer(user, user_id, email),
        "shippingAddress": _build_address(contact_name),
        "billingAddress": _build_address(contact_name),
        "basketItems": [_build_basket_item(plan, price)],
    }


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def create_checkout_form(user: Any, plan: Any) -> dict[str, Any]:
    """Initialize an iyzico CheckoutForm for a credit-pack purchase.

    Args:
        user: The buyer — a ``User`` ORM row or a mapping exposing at least
            ``id`` and ``email``.
        plan: A :class:`Plan`, a plan-key string ("starter"/"pro"), or a
            mapping/object carrying a ``key``.

    Returns:
        ``{"token", "checkout_url", "checkout_form_content", "token_expire_time",
        "conversation_id", "plan_key", "credits"}`` — ``checkout_url`` is the
        hosted payment page and ``checkout_form_content`` is the embeddable HTML
        snippet; use whichever the frontend prefers.

    Raises:
        RuntimeError: SDK missing, secrets/callback unconfigured, or iyzico
            returned a non-success status.
        ValueError: unknown or non-purchasable plan, or missing user id.
    """
    if iyzipay is None:
        raise RuntimeError("iyzipay SDK is not installed")

    resolved = _resolve_plan(plan)
    if not resolved.is_purchasable:
        raise ValueError(f"plan '{resolved.key}' is not purchasable")

    user_id = str(_attr(user, "id", "user_id"))
    if not user_id:
        raise ValueError("user id is required to create a checkout form")

    options = _iyzico_options()
    conversation_id = _encode_conversation_id(
        user_id, resolved.key, resolved.credits
    )
    request = _build_checkout_request(user, resolved, conversation_id)

    try:
        raw = iyzipay.CheckoutFormInitialize().create(request, options)
    except Exception as exc:  # noqa: BLE001 - normalize SDK/transport errors
        logger.error(f"iyzico checkout init failed: {exc}")
        raise RuntimeError(f"iyzico checkout init failed: {exc}") from exc

    result = _read_json(raw)
    if str(result.get("status", "")).lower() != "success":
        message = str(
            result.get("errorMessage") or "iyzico checkout initialization failed"
        )
        logger.error(f"iyzico checkout init rejected: {message}")
        raise RuntimeError(f"iyzico: {message}")

    return {
        "token": str(result.get("token", "") or ""),
        "checkout_url": str(result.get("paymentPageUrl", "") or ""),
        "checkout_form_content": str(result.get("checkoutFormContent", "") or ""),
        "token_expire_time": result.get("tokenExpireTime"),
        "conversation_id": conversation_id,
        "plan_key": resolved.key,
        "credits": resolved.credits,
    }


def retrieve_and_verify(token: str) -> dict[str, Any]:
    """Retrieve a CheckoutForm result by token and verify it was paid.

    This is safe to call from the webhook/callback path: it never raises on
    provider/transport errors — it logs and returns ``paid=False`` so the
    caller can still respond 200 fast. The caller owns idempotency (Redis
    SETNX on ``token``) and all credit writes.

    Args:
        token: The CheckoutForm token from ``create_checkout_form`` / callback.

    Returns:
        ``{"user_id", "credits", "plan_key", "conversation_id", "paid": bool}``.
        Provenance fields are recovered from the echoed ``conversationId``; they
        are empty/zero when the payment is not a ReelForge purchase.
    """
    result: dict[str, Any] = {
        "user_id": "",
        "credits": 0,
        "plan_key": "",
        "conversation_id": "",
        "paid": False,
    }

    if not token:
        logger.error("iyzico retrieve called without a token")
        return result
    if iyzipay is None:
        logger.error("iyzipay SDK is not installed")
        return result

    try:
        options = _iyzico_options()
    except RuntimeError as exc:
        logger.error(str(exc))
        return result

    request = {
        "locale": _DEFAULT_LOCALE,
        "conversationId": "",
        "token": str(token),
    }

    try:
        raw = iyzipay.CheckoutForm().retrieve(request, options)
    except Exception as exc:  # noqa: BLE001 - webhook must stay non-raising
        logger.error(f"iyzico retrieve failed: {exc}")
        return result

    data = _read_json(raw)
    conversation_id = str(data.get("conversationId", "") or "")
    user_id, plan_key, credits = _decode_conversation_id(conversation_id)

    # iyzico: top-level status == "success" AND paymentStatus == "SUCCESS".
    paid = (
        str(data.get("status", "")).lower() == "success"
        and str(data.get("paymentStatus", "")).upper() == "SUCCESS"
    )
    if not paid:
        logger.warning(
            "iyzico payment not confirmed for token "
            f"(status={data.get('status')!r}, "
            f"paymentStatus={data.get('paymentStatus')!r})"
        )

    result.update(
        user_id=user_id,
        credits=credits,
        plan_key=plan_key,
        conversation_id=conversation_id,
        paid=paid,
    )
    return result


__all__ = ["create_checkout_form", "retrieve_and_verify"]
