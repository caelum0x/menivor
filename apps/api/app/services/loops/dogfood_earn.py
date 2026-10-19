"""MH9 growth loop: the dogfood Earn campaign gate (Wave P PM3.0, owner decision OD4).

Menivor runs its own clipmarket campaign (people post clips about Menivor and
are paid per view, fraud-cleared submissions only, by the existing
``domains/clipmarket`` escrow) **only after 10 paying users**, and then with a
monthly cap of $100. Until both hold, and until the owner switches
``MENIVOR_DOGFOOD_EARN=1``, :func:`start` refuses with the reason.

"Paying user" here means a distinct user with a live paid plan
(``creator_subscriptions`` status ``active`` or ``trialing``). Credit-pack-only
buyers are not counted, so the gate errs on the side of staying off.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

PAYING_USERS_NEEDED = 10
MONTHLY_CAP_USD = 100
FLAG = "MENIVOR_DOGFOOD_EARN"
CAMPAIGN_TITLE_PREFIX = "Menivor dogfood"
_LIVE = ("active", "trialing")
_ON = {"1", "true", "yes", "on"}


class EarnRefused(Exception):
    pass


def paying_users(session: Session) -> int:
    from app.models.db.creator_subscription import CreatorSubscription

    return int(session.execute(
        select(func.count(func.distinct(CreatorSubscription.user_id)))
        .where(CreatorSubscription.status.in_(_LIVE))
    ).scalar_one() or 0)


def _month_title(moment: datetime) -> str:
    return f"{CAMPAIGN_TITLE_PREFIX} {moment:%Y-%m}"


def _spent_this_month_micros(session: Session, brand_id: str, moment: datetime) -> int:
    from app.models.db.clipmarket import ClipCampaign

    return int(session.execute(
        select(func.coalesce(func.sum(ClipCampaign.budget_micros), 0))
        .where(ClipCampaign.brand_id == brand_id, ClipCampaign.title == _month_title(moment))
    ).scalar_one() or 0)


def status(session: Session, env: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
    env = env if env is not None else os.environ
    paying = paying_users(session)
    return {
        "paying_users": paying,
        "paying_users_needed": PAYING_USERS_NEEDED,
        "eligible": paying >= PAYING_USERS_NEEDED,
        "switched_on": (env.get(FLAG) or "").strip().lower() in _ON,
        "monthly_cap_usd": MONTHLY_CAP_USD,
    }


def start(session: Session, *, brand_id: str, budget_usd: int, cpm_usd: float,
          env: Optional[Mapping[str, str]] = None, now: Optional[datetime] = None) -> Any:
    """Open this month's dogfood campaign; refuses before 10 paying users or above the cap."""
    from app.domains.clipmarket import service as clipmarket

    gate = status(session, env)
    if not gate["eligible"]:
        raise EarnRefused(f"the Earn campaign waits for {PAYING_USERS_NEEDED} paying users "
                          f"({gate['paying_users']} today)")
    if not gate["switched_on"]:
        raise EarnRefused(f"{FLAG} is off")
    moment = now or datetime.now(timezone.utc)
    budget_micros = int(budget_usd) * 1_000_000
    spent = _spent_this_month_micros(session, brand_id, moment)
    if budget_micros <= 0 or spent + budget_micros > MONTHLY_CAP_USD * 1_000_000:
        raise EarnRefused(f"the monthly cap is ${MONTHLY_CAP_USD}; ${spent / 1_000_000:.0f} is already committed")
    return clipmarket.create_campaign(session, brand_id=brand_id, cpm_micros=int(round(cpm_usd * 1_000_000)),
                                      budget_micros=budget_micros, title=_month_title(moment))


__all__ = ["EarnRefused", "MONTHLY_CAP_USD", "PAYING_USERS_NEEDED", "paying_users", "start", "status"]
