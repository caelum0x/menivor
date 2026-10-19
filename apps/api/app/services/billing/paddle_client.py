"""Paddle Billing (merchant of record) — scaffold for packs + the card check.

Inactive unless ``MENIVOR_PAYMENTS_PROVIDER=paddle``. NOTE: Paddle's AUP bars
products that generate realistic human faces/avatars (see
docs/PAYMENTS-PROVIDERS.md), so this is a fallback, not the plan.

* Checkout: ``POST /transactions`` with ``items=[{price_id, quantity}]`` and
  ``custom_data`` (our metadata); the response's ``checkout.url`` is the hosted
  (default payment link) checkout.
* Webhook: ``Paddle-Signature: ts=<unix>;h1=<hex>`` where
  ``h1 = HMAC-SHA256(secret, "<ts>:<raw body>")``; ``transaction.completed``
  fulfils a pack (credited under ``purchase:paddle:<transaction_id>``).
* Monthly plans are not wired for Paddle (Dodo carries them).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Mapping

from loguru import logger

from app.config import config

USER_AGENT: str = "menivor-api/1.0 (+https://menivor.com)"
LIVE_BASE: str = "https://api.paddle.com"
SANDBOX_BASE: str = "https://sandbox-api.paddle.com"
SIGNATURE_HEADER: str = "paddle-signature"
TOLERANCE_SECONDS: int = 5 * 60
_TIMEOUT: tuple[int, int] = (5, 20)
PROVIDER: str = "paddle"


class PaddleError(RuntimeError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"Paddle rejected the request (HTTP {status}): {detail}")
        self.status = status


def _cfg() -> dict[str, Any]:
    section = getattr(config, "paddle", None) or {}
    try:
        return dict(section)
    except (TypeError, ValueError):  # pragma: no cover
        return {}


def _value(key: str) -> str:
    return str(_cfg().get(key, "") or "").strip()


def api_base() -> str:
    if _value("base_url"):
        return _value("base_url").rstrip("/")
    return SANDBOX_BASE if _value("environment").lower() == "sandbox" else LIVE_BASE


def price_id(key: str) -> str:
    return _value(f"{(key or '').strip().lower()}_price_id")


def _request(method: str, path: str, *, body: Any = None) -> dict:
    import requests

    key = _value("api_key")
    if not key:
        raise RuntimeError("Paddle is not configured: set PADDLE_API_KEY.")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    try:
        response = requests.request(
            method, f"{api_base()}{path}", headers=headers, json=body, timeout=_TIMEOUT
        )
    except Exception as exc:  # noqa: BLE001
        raise PaddleError(0, f"{method} {path} failed: {type(exc).__name__}") from exc
    status = int(getattr(response, "status_code", 0) or 0)
    if status < 200 or status >= 300:
        raise PaddleError(status, str(getattr(response, "text", "") or "")[:300])
    try:
        data = response.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def create_checkout(*, price: str, custom_data: Mapping[str, Any], email: str = "") -> dict[str, str]:
    if not price:
        raise ValueError("Paddle price id is not configured for this checkout.")
    body: dict[str, Any] = {
        "items": [{"price_id": price, "quantity": 1}],
        "custom_data": {k: str(v) for k, v in custom_data.items() if v not in (None, "")},
        "collection_mode": "automatic",
    }
    data = (_request("POST", "/transactions", body=body) or {}).get("data") or {}
    txn = str(data.get("id", "") or "")
    url = str((data.get("checkout") or {}).get("url", "") or "")
    if not txn or not url:
        raise RuntimeError("Paddle returned a transaction without an id / checkout url.")
    logger.info(f"paddle: transaction {txn} opened kind={custom_data.get('kind')}")
    return {"checkout_url": url, "session_id": txn}


def create_pack_checkout(user: Mapping[str, Any], plan: Any, *, workspace_id: str | None) -> dict:
    return create_checkout(
        price=price_id(plan.key) or getattr(plan, "paddle_price_id", ""),
        custom_data={
            "kind": "pack",
            "user_id": user["id"],
            "plan_key": plan.key,
            "credits": int(plan.credits),
            "workspace_id": workspace_id or "",
        },
        email=str(user.get("email", "") or ""),
    )


def sign(secret: str, timestamp: str, payload: bytes) -> str:
    content = f"{timestamp}:".encode("utf-8") + bytes(payload)
    return hmac.new(secret.encode("utf-8"), content, hashlib.sha256).hexdigest()


def verify_and_parse_webhook(payload: bytes, signature: str, *, now: int | None = None) -> dict:
    secret = _value("webhook_secret")
    if not secret:
        raise RuntimeError("Paddle webhook secret is not configured: set PADDLE_WEBHOOK_SECRET.")
    parts = dict(
        item.split("=", 1) for item in (signature or "").split(";") if "=" in item
    )
    ts, h1 = parts.get("ts", ""), parts.get("h1", "")
    if not ts or not h1:
        raise ValueError("Paddle-Signature header is missing ts/h1")
    try:
        stamp = int(ts)
    except ValueError as exc:
        raise ValueError("Paddle-Signature ts is not an integer") from exc
    current = int(time.time()) if now is None else now
    if abs(current - stamp) > TOLERANCE_SECONDS:
        raise ValueError("Paddle webhook timestamp is outside the allowed tolerance")
    if not hmac.compare_digest(sign(secret, ts, bytes(payload)), h1):
        raise ValueError("Paddle webhook signature does not match")
    body = json.loads(bytes(payload).decode("utf-8"))
    if not isinstance(body, dict):
        raise ValueError("Paddle webhook body is not an object")
    return body


def extract_completed_purchase(event: Mapping[str, Any]) -> dict[str, Any] | None:
    if str(event.get("event_type", "") or "") != "transaction.completed":
        return None
    data = event.get("data") or {}
    custom = data.get("custom_data") or {}
    if data.get("subscription_id"):
        return None
    user_id = str(custom.get("user_id", "") or "").strip()
    txn = str(data.get("id", "") or "").strip()
    if not user_id or not txn:
        return None
    return {
        "transaction_id": txn,
        "user_id": user_id,
        "kind": str(custom.get("kind", "") or ""),
        "plan_key": str(custom.get("plan_key", "") or ""),
        "workspace_id": str(custom.get("workspace_id", "") or "").strip() or None,
        "event_id": str(event.get("event_id", "") or txn),
    }


def handle_webhook(payload: bytes, signature: str) -> int | None:
    """Verify + fulfil a Paddle pack / card-check purchase. Returns the balance."""
    from app.services.billing import card_check, service
    from app.services.billing.plans import get_plan

    purchase = extract_completed_purchase(verify_and_parse_webhook(payload, signature))
    if purchase is None:
        return None
    if purchase["kind"] == card_check.CARD_CHECK_KEY:
        return card_check.fulfill(
            user_id=purchase["user_id"],
            checkout_id=purchase["transaction_id"],
            external_event_id=purchase["event_id"],
            provider=PROVIDER,
        )
    plan = get_plan(purchase["plan_key"])
    if plan is None or not plan.is_purchasable:
        logger.warning(f"paddle: transaction {purchase['transaction_id']} is not a pack")
        return None
    return service.fulfill_purchase(
        provider=PROVIDER,
        external_event_id=purchase["event_id"],
        user_id=purchase["user_id"],
        credits=int(plan.credits),
        reason_ref=purchase["transaction_id"],
        workspace_id=purchase["workspace_id"],
    )


__all__ = [
    "PaddleError",
    "api_base",
    "create_checkout",
    "create_pack_checkout",
    "extract_completed_purchase",
    "handle_webhook",
    "price_id",
    "sign",
    "verify_and_parse_webhook",
]
