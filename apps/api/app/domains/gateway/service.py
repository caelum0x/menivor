"""Gateway service — persistent provisioning keys + spend-gated charging.

Bridges the pure cores (``gateway.provisioning``) to the DB rows
(``models.db.gateway``): mint a key (returns the secret once), resolve a key by
its secret hash, and authorize+record a charge — applying the reseller markup and
gating against the key's midnight-UTC daily cap using the current window's
recorded usage. The base wallet debit is the caller's job; this owns the resale
metering + cap enforcement.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func

from app.domains.gateway.provisioning import (
    MarkupPolicy,
    ProvisioningKey as KeyDTO,
    apply_markup,
    check_spend,
    window_start,
)
from app.models.db.gateway import GatewayUsage, ProvisioningKey


class GatewayServiceError(ValueError):
    """An invalid gateway operation (unknown/disabled key, cap exceeded)."""


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _row_to_dto(row: ProvisioningKey) -> KeyDTO:
    return KeyDTO(
        key_id=row.id,
        owner_id=row.owner_id,
        daily_cap_micros=row.daily_cap_micros,
        label=row.label,
        disabled=(str(row.disabled) == "1"),
    )


@dataclass(frozen=True)
class ChargeResult:
    """The outcome of authorizing a charge against a provisioning key."""

    allowed: bool
    customer_price_micros: int
    remaining_micros: int
    usage_id: str = ""
    reason: str = ""


def create_key(
    session: Any, *, owner_id: str, daily_cap_micros: int = 0, label: str = "",
    markup_bps: int = 0, min_fee_micros: int = 0,
) -> tuple[ProvisioningKey, str]:
    """Mint a provisioning key; returns ``(row, plaintext_secret)`` — secret shown once."""
    secret = f"rf_pk_{secrets.token_urlsafe(32)}"
    row = ProvisioningKey(
        owner_id=owner_id, key_hash=hash_secret(secret), label=label,
        daily_cap_micros=max(0, int(daily_cap_micros)),
        markup_bps=max(0, int(markup_bps)), min_fee_micros=max(0, int(min_fee_micros)),
    )
    session.add(row)
    session.flush()
    return row, secret


def resolve_key(session: Any, secret: str) -> ProvisioningKey | None:
    """Resolve a plaintext secret to its key row (by hash), or None."""
    return (
        session.query(ProvisioningKey)
        .filter(ProvisioningKey.key_hash == hash_secret(secret))
        .one_or_none()
    )


def set_key_disabled(session: Any, *, key_id: str, owner_id: str, disabled: bool) -> ProvisioningKey:
    """Disable/enable a provisioning key (owner-scoped). A disabled key denies all
    charges (see ``check_spend``) — effectively a revoke without deleting history."""
    row = session.get(ProvisioningKey, key_id)
    if row is None or str(row.owner_id) != str(owner_id):
        raise GatewayServiceError(f"unknown key {key_id!r}")
    row.disabled = "1" if disabled else "0"
    session.flush()
    return row


def spent_today(session: Any, key_id: str, *, now: datetime) -> int:
    """Sum of charges against ``key_id`` since the current midnight-UTC window."""
    start = window_start(now)
    total = (
        session.query(func.coalesce(func.sum(GatewayUsage.charge_micros), 0))
        .filter(GatewayUsage.key_id == key_id, GatewayUsage.created_at >= start)
        .scalar()
    )
    return int(total or 0)


def authorize_and_record(
    session: Any, key: ProvisioningKey, base_cost_micros: int, *, now: datetime,
    model_key: str = "", correlation_id: str = "",
) -> ChargeResult:
    """Apply the key's markup, gate against the daily cap, and record the usage.

    Returns ``allowed=False`` (no usage recorded) when the key is disabled or the
    marked-up price would exceed the remaining daily allowance; otherwise records a
    :class:`GatewayUsage` row and returns the customer price + remaining headroom.
    """
    dto = _row_to_dto(key)
    policy = MarkupPolicy(markup_bps=key.markup_bps, min_fee_micros=key.min_fee_micros)
    customer_price = apply_markup(base_cost_micros, policy)

    already = spent_today(session, key.id, now=now)
    decision = check_spend(dto, customer_price, spent_today_micros=already)
    if not decision.allow:
        return ChargeResult(False, customer_price, decision.remaining_micros, reason=decision.reason)

    usage = GatewayUsage(
        key_id=key.id, charge_micros=customer_price, base_cost_micros=max(0, int(base_cost_micros)),
        model_key=model_key, correlation_id=correlation_id, created_at=now,
    )
    session.add(usage)
    session.flush()
    return ChargeResult(True, customer_price, decision.remaining_micros, usage_id=usage.id, reason="ok")
