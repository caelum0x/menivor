"""Mint entitlement webhooks for channel sales (MV13; contract 5.5).

Mint delivers ``{"type": "entitlement.granted" | "entitlement.revoked",
"data": {id, seller, kind, reason, buyer_ref, sku, provider,
provider_event_id, occurred_at_ms, expires_at_ms}}`` Standard Webhooks signed
with Menivor's endpoint secret (``MINT_SELLER_WEBHOOK_SECRET``, ``whsec_``).

**Invariant (Dodo items 20 and 30): Menivor never receives or forwards viewer
funds.** The event carries no amount and this module writes no ledger, wallet,
credit or payout row: only entitlements and the event id. A payload that
claims funds were routed through us (``funds_holder`` other than the seller's
own processor) is refused and logged.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from app.services.billing import standard_webhooks

from . import entitlements

SECRET_ENV = "MINT_SELLER_WEBHOOK_SECRET"
EVENT_TYPES = ("entitlement.granted", "entitlement.revoked")
#: Fields that would mean money passed through Menivor; never accepted.
FUNDS_FIELDS = ("amount", "amount_cents", "payout", "balance", "funds_holder", "transfer")


class WebhookRefused(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def secret(env: Mapping[str, str] | None = None) -> str:
    return ((env if env is not None else os.environ).get(SECRET_ENV) or "").strip()


def verify(payload: bytes, headers: Mapping[str, Any], *, env: Mapping[str, str] | None = None,
           now: int | None = None) -> dict:
    key = secret(env)
    if not key:
        raise WebhookRefused(503, "webhook secret is not configured")
    try:
        return standard_webhooks.verify(payload, headers, key, now=now)
    except standard_webhooks.SignatureError as exc:
        raise WebhookRefused(401, "bad signature") from exc


def handle(session: Session, body: Mapping[str, Any]) -> dict[str, str]:
    event_type = str(body.get("type") or "")
    data = body.get("data")
    if event_type not in EVENT_TYPES or not isinstance(data, Mapping):
        return {"outcome": "ignored:type"}
    carried = [f for f in FUNDS_FIELDS if f in data]
    if carried:
        logger.error(f"mint webhook {data.get('id')}: refused, carries fund fields {carried}")
        raise WebhookRefused(422, "entitlement events never carry funds")
    outcome = entitlements.apply_event(session, event_type, data)
    if outcome.startswith("refused:"):
        raise WebhookRefused(422, "a subscription grant must carry its period end (expires_at_ms)")
    return {"outcome": outcome}


__all__ = ["EVENT_TYPES", "FUNDS_FIELDS", "SECRET_ENV", "WebhookRefused", "handle", "verify"]
