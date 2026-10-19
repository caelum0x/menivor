"""Dodo Payments (merchant of record) transport + event normalization.

REST API (https://docs.dodopayments.com/api-reference): bearer-key auth,
``https://live.dodopayments.com`` (``DODO_ENVIRONMENT=live_mode``, default) or
``https://test.dodopayments.com`` (``test_mode``). Webhooks follow Standard
Webhooks (see :mod:`standard_webhooks`).

Nothing here writes to the DB or grants credit; :mod:`service` and
:mod:`creator_subscriptions` do that idempotently. Every request sends an
explicit User-Agent and raises :class:`DodoError` with a short, key-free detail.

Checkout metadata (all string values) threads the buyer through every event:

* ``kind``: ``pack`` | ``card_check`` | ``creator_plan``
* ``user_id``, ``plan_key``, ``credits``, ``interval``, ``workspace_id``
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import quote

from loguru import logger

from app.config import config

USER_AGENT: str = "menivor-api/1.0 (+https://menivor.com)"
LIVE_BASE: str = "https://live.dodopayments.com"
TEST_BASE: str = "https://test.dodopayments.com"
_TIMEOUT: tuple[int, int] = (5, 20)

KIND_PACK: str = "pack"
KIND_CARD_CHECK: str = "card_check"
KIND_CREATOR_PLAN: str = "creator_plan"
KIND_PREMIUM_PACK: str = "premium_pack"

PAYMENT_SUCCEEDED: str = "payment.succeeded"
REFUND_SUCCEEDED: str = "refund.succeeded"
SUBSCRIPTION_EVENTS: frozenset[str] = frozenset(
    {
        "subscription.active",
        "subscription.renewed",
        "subscription.updated",
        "subscription.plan_changed",
        "subscription.on_hold",
        "subscription.past_due",
        "subscription.failed",
        "subscription.cancelled",
        "subscription.expired",
    }
)
#: Events on which a paid period may be granted (money was actually taken).
GRANT_EVENTS: frozenset[str] = frozenset({"subscription.active", "subscription.renewed"})

_STATUS_MAP: dict[str, str] = {
    "active": "active",
    "on_hold": "past_due",
    "past_due": "past_due",
    "paused": "past_due",
    "pending": "pending",
    "cancelled": "canceled",
    "canceled": "canceled",
    "failed": "canceled",
    "expired": "canceled",
}


class DodoError(RuntimeError):
    """Dodo answered with a non-2xx status (or could not be reached)."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"Dodo Payments rejected the request (HTTP {status}): {detail}")
        self.status = status


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def _cfg() -> dict[str, Any]:
    section = getattr(config, "dodo", None) or {}
    try:
        return dict(section)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return {}


def _value(key: str) -> str:
    return str(_cfg().get(key, "") or "").strip()


def api_base() -> str:
    override = _value("base_url")
    if override:
        return override.rstrip("/")
    return TEST_BASE if _value("environment").lower() == "test_mode" else LIVE_BASE


def is_configured() -> bool:
    return bool(_value("api_key"))


def brand_id() -> str:
    return _value("brand_id")


def event_brand(event: Any) -> str:
    """The brand an event belongs to (``data.brand_id`` or top-level)."""
    data = _get(event, "data") or {}
    return str(_get(data, "brand_id", "") or _get(event, "brand_id", "") or "").strip()


def webhook_secret() -> str:
    return _value("webhook_secret")


def pack_product_id(key: str) -> str:
    return _value(f"{(key or '').strip().lower()}_product_id")


def card_check_product_id() -> str:
    return _value("card_check_product_id")


def plan_product_id(key: str, interval: str) -> str:
    return _value(f"plan_{(key or '').strip().lower()}_{(interval or '').strip().lower()}_product_id")


def plan_env_name(key: str, interval: str) -> str:
    return f"DODO_PRODUCT_ID_PLAN_{key.upper()}_{interval.upper()}"


def web_base_url() -> str:
    from app.services.billing import card_check

    return card_check.web_base_url()


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def _headers() -> dict[str, str]:
    key = _value("api_key")
    if not key:
        raise RuntimeError("Dodo Payments is not configured: set DODO_API_KEY.")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }


def request(method: str, path: str, *, body: Any = None, params: dict | None = None) -> dict:
    try:
        import requests
    except Exception as exc:  # pragma: no cover - requests is a hard dep
        raise RuntimeError(f"'requests' is required for billing: {exc}") from exc
    url = f"{api_base()}{path}"
    try:
        response = requests.request(
            method, url, headers=_headers(), json=body, params=params, timeout=_TIMEOUT
        )
    except Exception as exc:  # noqa: BLE001 - normalize transport errors
        raise DodoError(0, f"{method} {path} failed: {type(exc).__name__}") from exc
    status = int(getattr(response, "status_code", 0) or 0)
    if status < 200 or status >= 300:
        raise DodoError(status, str(getattr(response, "text", "") or "")[:300])
    if not getattr(response, "content", b""):
        return {}
    try:
        data = response.json()
    except Exception:  # noqa: BLE001 - body optional for mutations
        return {}
    return data if isinstance(data, dict) else {"items": data}


# --------------------------------------------------------------------------- #
# Checkout / payments / subscriptions / portal / refunds
# --------------------------------------------------------------------------- #
def _string_metadata(metadata: Mapping[str, Any]) -> dict[str, str]:
    return {str(k): str(v) for k, v in metadata.items() if v is not None and str(v) != ""}


def create_checkout(
    *,
    product_id: str,
    metadata: Mapping[str, Any],
    return_url: str,
    customer_email: str = "",
) -> dict[str, str]:
    """Open a hosted checkout session; returns ``{checkout_url, session_id}``."""
    if not product_id:
        raise RuntimeError("Dodo product id is not configured for this checkout.")
    body: dict[str, Any] = {
        "product_cart": [{"product_id": product_id, "quantity": 1}],
        "return_url": return_url,
        "metadata": _string_metadata(metadata),
    }
    if customer_email:
        body["customer"] = {"email": customer_email}
    data = request("POST", "/checkouts", body=body)
    session_id = str(data.get("session_id", "") or "").strip()
    url = str(data.get("checkout_url", "") or "").strip()
    if not session_id or not url:
        raise RuntimeError("Dodo returned a checkout without a session id / url.")
    logger.info(
        f"dodo: checkout {session_id} kind={metadata.get('kind')} user={metadata.get('user_id')}"
    )
    return {"checkout_url": url, "session_id": session_id}


def return_url(path: str, **query: str) -> str:
    """``<web>/<path>?checkout=return&provider=dodo&...`` (Dodo appends its ids)."""
    parts = ["checkout=return", "provider=dodo"]
    parts += [f"{k}={quote(str(v), safe='')}" for k, v in query.items() if v]
    return f"{web_base_url()}{path}?{'&'.join(parts)}"


def get_payment(payment_id: str) -> dict:
    ref = (payment_id or "").strip()
    if not ref:
        raise ValueError("payment id is required")
    return request("GET", f"/payments/{quote(ref, safe='')}")


def get_subscription(subscription_id: str) -> dict:
    ref = (subscription_id or "").strip()
    if not ref:
        raise ValueError("subscription id is required")
    return request("GET", f"/subscriptions/{quote(ref, safe='')}")


def cancel_subscription(subscription_id: str) -> str:
    """Turn renewal off at period end. Returns ``"scheduled"``."""
    ref = (subscription_id or "").strip()
    if not ref:
        raise ValueError("subscription has no Dodo id to cancel")
    request(
        "PATCH",
        f"/subscriptions/{quote(ref, safe='')}",
        body={"cancel_at_next_billing_date": True},
    )
    return "scheduled"


def change_plan(subscription_id: str, product_id: str, *, upgrade: bool) -> None:
    """Upgrades are prorated and charged now; downgrades apply without a charge."""
    ref = (subscription_id or "").strip()
    if not ref or not product_id:
        raise ValueError("subscription id and product id are required")
    request(
        "POST",
        f"/subscriptions/{quote(ref, safe='')}/change-plan",
        body={
            "product_id": product_id,
            "quantity": 1,
            "proration_billing_mode": "prorated_immediately" if upgrade else "do_not_bill",
        },
    )


def portal_link(customer_id: str) -> str:
    ref = (customer_id or "").strip()
    if not ref:
        raise ValueError("no Dodo customer id on file")
    data = request(
        "POST",
        f"/customers/{quote(ref, safe='')}/customer-portal/session",
        params={"return_url": f"{web_base_url()}/billing"},
    )
    url = str(data.get("link", "") or "").strip()
    if not url:
        raise RuntimeError("Dodo returned no customer portal link.")
    return url


def create_refund(payment_id: str, reason: str = "") -> dict:
    """Full refund of ``payment_id`` (credits are clawed back on refund.succeeded)."""
    ref = (payment_id or "").strip()
    if not ref:
        raise ValueError("payment id is required")
    body: dict[str, Any] = {"payment_id": ref}
    if reason:
        body["reason"] = reason[:200]
    return request("POST", "/refunds", body=body)


# --------------------------------------------------------------------------- #
# Webhooks
# --------------------------------------------------------------------------- #
def verify_and_parse_webhook(payload: bytes, headers: Mapping[str, Any]) -> dict:
    from app.services.billing import standard_webhooks

    secret = webhook_secret()
    if not secret:
        raise RuntimeError("Dodo webhook secret is not configured: set DODO_WEBHOOK_SECRET.")
    return standard_webhooks.verify(payload, headers, secret)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default) if obj is not None else default


def event_type(event: Any) -> str:
    return str(_get(event, "type", "") or "").strip()


def event_data(event: Any) -> dict:
    data = _get(event, "data") or {}
    return data if isinstance(data, dict) else {}


def event_id(event: Any) -> str:
    return str(_get(event, "_webhook_id", "") or "").strip()


def _customer(obj: Any) -> dict:
    customer = _get(obj, "customer") or {}
    return customer if isinstance(customer, dict) else {"customer_id": str(customer)}


def payment_view(obj: Any) -> dict[str, Any]:
    """Normalize a Dodo payment (webhook ``data`` or GET /payments/{id})."""
    customer = _customer(obj)
    cart = _get(obj, "product_cart") or []
    product_ids = [
        str(_get(item, "product_id", "") or "") for item in cart if isinstance(item, dict)
    ]
    metadata = _get(obj, "metadata") or {}
    return {
        "payment_id": str(_get(obj, "payment_id", "") or "").strip(),
        "status": str(_get(obj, "status", "") or "").strip().lower(),
        "customer_id": str(customer.get("customer_id", "") or "").strip(),
        "email": str(customer.get("email", "") or "").strip(),
        "subscription_id": str(_get(obj, "subscription_id", "") or "").strip(),
        "metadata": metadata if isinstance(metadata, dict) else {},
        "product_ids": [p for p in product_ids if p],
    }


def _to_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def subscription_view(obj: Any, *, event: str = "") -> dict[str, Any]:
    """Normalize a Dodo subscription into the personal-plan update shape."""
    raw_status = str(_get(obj, "status", "") or "").strip().lower()
    if event in {"subscription.cancelled", "subscription.expired", "subscription.failed"}:
        status = "canceled"
    elif event in {"subscription.on_hold", "subscription.past_due"}:
        status = "past_due"
    else:
        status = _STATUS_MAP.get(raw_status, "active" if not raw_status else "pending")
    metadata = _get(obj, "metadata") or {}
    return {
        "provider_ref": str(_get(obj, "subscription_id", "") or "").strip(),
        "customer_ref": str(_customer(obj).get("customer_id", "") or "").strip(),
        "product_ref": str(_get(obj, "product_id", "") or "").strip(),
        "metadata": metadata if isinstance(metadata, dict) else {},
        "status": status,
        "cancel_at_period_end": bool(_get(obj, "cancel_at_next_billing_date", False)),
        "period_end": _to_datetime(_get(obj, "next_billing_date")),
        "expire_now": event == "subscription.expired",
    }


__all__ = [
    "DodoError",
    "GRANT_EVENTS",
    "KIND_CARD_CHECK",
    "KIND_CREATOR_PLAN",
    "KIND_PACK",
    "KIND_PREMIUM_PACK",
    "PAYMENT_SUCCEEDED",
    "REFUND_SUCCEEDED",
    "SUBSCRIPTION_EVENTS",
    "USER_AGENT",
    "api_base",
    "cancel_subscription",
    "card_check_product_id",
    "change_plan",
    "create_checkout",
    "create_refund",
    "brand_id",
    "event_brand",
    "event_data",
    "event_id",
    "event_type",
    "get_payment",
    "get_subscription",
    "is_configured",
    "pack_product_id",
    "payment_view",
    "plan_env_name",
    "plan_product_id",
    "portal_link",
    "request",
    "return_url",
    "subscription_view",
    "verify_and_parse_webhook",
    "webhook_secret",
]
