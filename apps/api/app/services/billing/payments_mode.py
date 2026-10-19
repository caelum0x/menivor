"""Which payment provider takes new customer money, and the paused mode.

``MENIVOR_PAYMENTS_PROVIDER`` selects the single merchant of record used for
NEW checkouts (the $1 card check, credit packs and monthly plans):

* ``creem``  (default, legacy)   * ``dodo``  (Dodo Payments)
* ``paddle`` (Paddle Billing)     * ``none``  (payments paused)

``MENIVOR_PAYMENTS_PAUSED=1`` forces ``none`` whatever the provider says.

While paused:

* no checkout of any kind can be opened (packs, plans, card check);
* the card check is not required: every account gets ``FREE_MONTHLY_REELS``
  free reels per calendar month (idempotent ledger reason
  ``free_monthly:<YYYY-MM>``), so sign-up goes straight to the first render;
* existing paid credits stay usable (nothing is debited or expired here);
* provider webhooks and signed-redirect confirmations keep working, so
  in-flight payments and refunds still settle (see ``launch.policy``).

Env is read on every call, so a container restart after editing the env file
is enough to flip the mode (no code change).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

CREEM: str = "creem"
DODO: str = "dodo"
PADDLE: str = "paddle"
NONE: str = "none"
PROVIDERS: tuple[str, ...] = (CREEM, DODO, PADDLE, NONE)

_DEFAULT_PROVIDER: str = CREEM
_DEFAULT_FREE_MONTHLY_REELS: int = 3
_MAX_FREE_MONTHLY_REELS: int = 50
FREE_MONTHLY_REASON_PREFIX: str = "free_monthly"
_FREE_MONTHLY_KEY_PREFIX: str = "billing:free_monthly"
# Redis lock outlives a month; the durable ledger reason is the real guard.
_FREE_MONTHLY_TTL_SECONDS: int = 40 * 24 * 60 * 60

_TRUTHY: frozenset[str] = frozenset({"1", "true", "yes", "on"})


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in _TRUTHY


def active_provider() -> str:
    """The provider for new checkouts, or ``"none"`` when payments are paused.

    Unknown values fail closed to ``none`` (never silently route money to a
    provider nobody selected).
    """
    if _truthy(os.getenv("MENIVOR_PAYMENTS_PAUSED")):
        return NONE
    raw = os.getenv("MENIVOR_PAYMENTS_PROVIDER", _DEFAULT_PROVIDER)
    normalized = str(raw or "").strip().lower() or _DEFAULT_PROVIDER
    return normalized if normalized in PROVIDERS else NONE


def payments_paused() -> bool:
    return active_provider() == NONE


def free_monthly_reels() -> int:
    """Free reels per account per month while paused (``MENIVOR_FREE_MONTHLY_REELS``)."""
    raw = os.getenv("MENIVOR_FREE_MONTHLY_REELS", "")
    try:
        value = int(str(raw).strip()) if str(raw).strip() else _DEFAULT_FREE_MONTHLY_REELS
    except ValueError:
        value = _DEFAULT_FREE_MONTHLY_REELS
    return max(0, min(value, _MAX_FREE_MONTHLY_REELS))


def month_key(now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m")


def free_monthly_reason(now: datetime | None = None) -> str:
    return f"{FREE_MONTHLY_REASON_PREFIX}:{month_key(now)}"


def grant_free_monthly(user_id: str, now: datetime | None = None) -> int:
    """Grant this month's free reels once. Returns the balance afterwards.

    A no-op (returns the current balance) when the allowance is 0.
    """
    from app.services.billing import service

    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("grant_free_monthly requires a user id")
    reels = free_monthly_reels()
    if reels <= 0:
        return service._current_balance(uid)
    reason = free_monthly_reason(now)
    return service._idempotent_grant(
        idempotency_key=f"{_FREE_MONTHLY_KEY_PREFIX}:{uid}:{month_key(now)}",
        user_id=uid,
        credits=reels,
        reason=reason,
        ttl_seconds=_FREE_MONTHLY_TTL_SECONDS,
    )


def status() -> dict:
    """Public, secret-free view for clients (launch status / pricing page)."""
    provider = active_provider()
    return {
        "paused": provider == NONE,
        "provider": provider,
        "free_monthly_reels": free_monthly_reels() if provider == NONE else 0,
    }


__all__ = [
    "CREEM",
    "DODO",
    "FREE_MONTHLY_REASON_PREFIX",
    "NONE",
    "PADDLE",
    "PROVIDERS",
    "active_provider",
    "free_monthly_reason",
    "free_monthly_reels",
    "grant_free_monthly",
    "month_key",
    "payments_paused",
    "status",
]
