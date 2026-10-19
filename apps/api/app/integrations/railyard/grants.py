"""Scribase add-on grants honoured by Menivor (contract 5.4).

A partner token may carry ``grant = addon-monthly-reel`` (aud ``menivor``, cap
``launch-video``) and ``grant_period = YYYY-MM``. The Scribase portfolio
add-on includes one launch reel per org per month
(``MENIVOR_ADDON_REEL_GRANT``, default 1, from ``plans.json``). Redeeming it:

* is idempotent per org, month and Menivor user (the same user never gets
  a second reel from the same grant);
* credits the user one reel in Menivor's own ledger (the render then follows
  the normal create path) and queues the grant debit for Rago with
  ``transaction_id = menivor:grant:<org>:<period>:<n>`` against the org;
* refuses a draw beyond the month's grant with a plain message and the
  pricing page as the upgrade path. The user can still make the reel at the
  normal price.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.db.base import Base

from . import contract, meters

GRANT_MONTHLY_REEL = "addon-monthly-reel"
AUDIENCE = "menivor"
CAPABILITY = "launch-video"
GRANT_ENV = "MENIVOR_ADDON_REEL_GRANT"
UPGRADE_URL = "/pricing"


class GrantInvalid(ValueError):
    """The token's grant is not one Menivor honours for this action or month."""


class GrantExhausted(Exception):
    status_code = 402

    def __init__(self, message: str, upgrade_url: str = UPGRADE_URL) -> None:
        super().__init__(message)
        self.message = message
        self.upgrade_url = upgrade_url


class GrantRedemption(Base):
    __tablename__ = "railyard_grant_redemptions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    org_id: Mapped[str] = mapped_column(String(80), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    n: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    grant: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("org_id", "period", "n", name="uq_grant_redemptions_slot"),
        UniqueConstraint("org_id", "period", "user_id", name="uq_grant_redemptions_user"),
    )


def monthly_reels() -> int:
    try:
        return max(0, int(os.environ.get(GRANT_ENV) or 1))
    except ValueError:
        return 1


def _period(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def redeem(session: Session, claims: Any, *, user_id: str, now: Optional[datetime] = None) -> Optional[dict]:
    """Redeem the token's grant for ``user_id``; ``None`` when the token has no grant."""
    from app.models.db.repositories import CreditRepository

    grant = str(getattr(claims, "grant", "") or "")
    if not grant:
        return None
    if grant != GRANT_MONTHLY_REEL or claims.audience != AUDIENCE or claims.capability != CAPABILITY:
        raise GrantInvalid(f"grant {grant!r} is not valid for a launch video")
    period = str(getattr(claims, "grant_period", "") or "")
    if period != _period(now):
        raise GrantInvalid("the grant is for another month")
    org = str(claims.org_id or "").strip()
    if not org:
        raise GrantInvalid("the grant names no org")
    mine = session.execute(select(GrantRedemption).where(
        GrantRedemption.org_id == org, GrantRedemption.period == period, GrantRedemption.user_id == str(user_id)
    )).scalar_one_or_none()
    if mine is not None:
        return {"reels": 1, "period": period, "duplicate": True, "n": mine.n}
    used = len(session.execute(select(GrantRedemption.id).where(
        GrantRedemption.org_id == org, GrantRedemption.period == period)).all())
    n = used + 1
    if n > monthly_reels():
        raise GrantExhausted("This month's included reel for your Scribase add-on is already used. "
                             "You can still make this reel at the normal price.")
    try:
        with session.begin_nested():
            session.add(GrantRedemption(org_id=org, period=period, n=n, user_id=str(user_id), grant=grant))
    except IntegrityError as exc:
        raise GrantExhausted("This month's included reel was just used. "
                             "You can still make this reel at the normal price.") from exc
    CreditRepository(session).grant(str(user_id), 1, f"scribase_addon_grant:{org}:{period}:{n}"[:80])
    meters.record(session, code=contract.REEL_RENDERED, source_id=f"grant-{org}-{period}-{n}",
                  customer=f"scribase-org:{org}", transaction=contract.grant_transaction_id(org, period, n),
                  properties={"grant": grant, "grant_period": period, "menivor_user": str(user_id)})
    session.flush()
    return {"reels": 1, "period": period, "duplicate": False, "n": n}
