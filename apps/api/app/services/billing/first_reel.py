"""Free first reel: one reel credit before the $1 card check.

The funnel's biggest drop was sign-up -> card check: a new web account had to
pay $1 before it saw a single reel. With ``MENIVOR_FREE_FIRST_REEL=1`` a new
account gets exactly one reel credit (ledger reason ``free_first_reel``) the
first time the web asks for its unlock status, renders one reel, and meets the
$1 card check right after that first result.

Guards:

* never for an account that is already unlocked (signup grant or any payment);
* never while payments are paused (the free monthly reels cover that mode);
* one per person: the normalized sign-in email is recorded with the same
  abuse markers as the signup grant (``grant_markers``), so a second account
  on the same mailbox gets nothing, and an account with no real email (a
  synthetic device identity) gets nothing;
* idempotent per user (Redis key + durable ledger reason).

The card check is unchanged: it still credits the $1 and grants the full
signup reels, so the first reel is on top of the published offer.
"""

from __future__ import annotations

import os
from typing import Any

from loguru import logger

FIRST_REEL_REASON: str = "free_first_reel"
FIRST_REEL_CREDITS: int = 1
_FLAG_ENV: str = "MENIVOR_FREE_FIRST_REEL"
_KEY_PREFIX: str = "billing:free_first_reel"
_TRUTHY: frozenset[str] = frozenset({"1", "true", "yes", "on"})


def enabled() -> bool:
    """True when the flag is on (env read per call: a restart flips it)."""
    return str(os.getenv(_FLAG_ENV, "") or "").strip().lower() in _TRUTHY


def has_grant(session: Any, user_id: str) -> bool:
    from sqlalchemy import select

    from app.models.db.models import CreditLedger

    stmt = (
        select(CreditLedger.id)
        .where(CreditLedger.user_id == user_id, CreditLedger.reason == FIRST_REEL_REASON)
        .limit(1)
    )
    return session.execute(stmt).first() is not None


def _eligible(session: Any, user_id: str) -> bool:
    """Not unlocked, not granted yet, and a real email no one else used."""
    from app.models.db.models import User
    from app.services.abuse import grant_markers
    from app.services.billing import card_check

    if card_check.is_unlocked(session, user_id) or has_grant(session, user_id):
        return False
    user = session.get(User, user_id)
    signals = grant_markers.email_signals(getattr(user, "email", "") if user is not None else "")
    if not any(signals.values()):
        return False
    if not grant_markers.grant_allowed(session, user_id, signals):
        return False
    grant_markers.record_grant(session, user_id, signals)
    return True


def maybe_grant(user_id: str) -> bool:
    """Grant the free first reel if this account qualifies.

    Returns True when the account holds the first-reel grant afterwards
    (granted now or before), False when it does not qualify.
    """
    from app.models.db.base import get_session
    from app.services.billing import payments_mode, service

    uid = str(user_id or "").strip()
    if not uid or not enabled() or payments_mode.payments_paused():
        return False
    with get_session() as session:
        if has_grant(session, uid):
            return True
        if not _eligible(session, uid):
            return False
    service._idempotent_grant(
        idempotency_key=f"{_KEY_PREFIX}:{uid}",
        user_id=uid,
        credits=FIRST_REEL_CREDITS,
        reason=FIRST_REEL_REASON,
        ttl_seconds=None,
    )
    logger.info(f"billing: free first reel granted to user={uid}")
    return True


def ready(session: Any, user_id: str, *, unlocked: bool, credits: int) -> bool:
    """The account may create now on its free first reel (still unspent)."""
    return bool(not unlocked and credits > 0 and has_grant(session, user_id))


__all__ = [
    "FIRST_REEL_CREDITS",
    "FIRST_REEL_REASON",
    "enabled",
    "has_grant",
    "maybe_grant",
    "ready",
]
