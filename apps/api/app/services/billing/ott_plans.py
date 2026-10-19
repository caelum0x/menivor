"""OTT plans and caps (MV7, Wave P PM3.1).

Until the written Dodo reply on selling OTT plans (owner decision OD-MV2,
``OTT_PLANS_SELLABLE=1``), OTT is **included in the existing plans with
caps**: free, creator, pro and agency each get a monthly allowance of the four
OTT meters. The numbers below are targets (marked as such in the studio) until
measured usage replaces them.

Overage is **off** for everyone until the creator opts in (an append-only
``ConsentRecord`` of kind ``ott_overage`` at :data:`OVERAGE_TERMS_VERSION`).
Without the opt-in, reaching a cap stops new uploads, encodes and AI minutes
for the rest of the month (playback keeps working; nothing past the cap is
billed). With it, usage above the cap is billed through the Dodo meters.

Routes (404 until OTT_ENABLED and OTT_PLANS_LIVE):
* ``GET  /api/v1/ott/studio/plan``           caps, month-to-date usage, overage state
* ``POST /api/v1/ott/studio/plan/overage``   opt in or out of overage
"""

from __future__ import annotations

import calendar
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import Depends, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.controllers import base
from app.controllers.v1.base import new_router
from app.domains.ott import flags
from app.utils import utils

METERS: tuple[str, ...] = ("gb_stored", "minutes_delivered", "encode_minutes", "ai_minutes")
UNITS = {"gb_stored": "GB-hours", "minutes_delivered": "minutes", "encode_minutes": "minutes",
         "ai_minutes": "minutes"}
OVERAGE_KIND = "ott_overage"
OVERAGE_TERMS_VERSION = "ott-overage-2026-10"
SELLABLE_ENV = "OTT_PLANS_SELLABLE"
_LIVE = ("active", "trialing")
_ON = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class OttCaps:
    """Monthly allowance per meter (targets until measured)."""

    gb_stored: float
    minutes_delivered: float
    encode_minutes: float
    ai_minutes: float


PLAN_CAPS: dict[str, OttCaps] = {
    "free": OttCaps(gb_stored=2, minutes_delivered=1_000, encode_minutes=30, ai_minutes=0),
    "creator": OttCaps(gb_stored=25, minutes_delivered=20_000, encode_minutes=300, ai_minutes=60),
    "pro": OttCaps(gb_stored=100, minutes_delivered=100_000, encode_minutes=1_200, ai_minutes=300),
    "agency": OttCaps(gb_stored=500, minutes_delivered=500_000, encode_minutes=6_000, ai_minutes=1_500),
}


class OttPlanError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def sellable(env: Optional[Mapping[str, str]] = None) -> bool:
    return ((env if env is not None else os.environ).get(SELLABLE_ENV) or "").strip().lower() in _ON


def plan_key(session: Session, user_id: str) -> str:
    from app.models.db.creator_subscription import CreatorSubscription

    row = session.execute(select(CreatorSubscription).where(CreatorSubscription.user_id == user_id,
                                                            CreatorSubscription.status.in_(_LIVE))
                          ).scalars().first()
    key = str(getattr(row, "plan_key", "") or "free").lower()
    return key if key in PLAN_CAPS else "free"


def caps_for(session: Session, user_id: str) -> OttCaps:
    return PLAN_CAPS[plan_key(session, user_id)]


def month_bounds(moment: datetime) -> tuple[str, str, int]:
    """(first hour key, first hour key of next month, hours in the month) for ``moment``'s month."""
    days = calendar.monthrange(moment.year, moment.month)[1]
    start = f"{moment:%Y-%m}-01T00"
    nxt = datetime(moment.year + (moment.month == 12), moment.month % 12 + 1, 1, tzinfo=timezone.utc)
    return start, f"{nxt:%Y-%m}-01T00", days * 24


def allowance(caps: OttCaps, meter: str, moment: datetime) -> float:
    """The month's included quantity in the meter's unit (GB caps become GB-hours)."""
    value = float(getattr(caps, meter))
    return value * month_bounds(moment)[2] if meter == "gb_stored" else value


def month_to_date(session: Session, user_id: str, moment: datetime,
                  *, before_hour: Optional[str] = None) -> dict[str, float]:
    from app.domains.ott_viewers.models import OttUsageHour

    start, end, _ = month_bounds(moment)
    stop = before_hour or end
    rows = session.execute(
        select(OttUsageHour.meter, func.coalesce(func.sum(OttUsageHour.quantity), 0.0))
        .where(OttUsageHour.user_id == user_id, OttUsageHour.hour >= start, OttUsageHour.hour < stop)
        .group_by(OttUsageHour.meter)
    ).all()
    totals = {meter: 0.0 for meter in METERS}
    totals.update({str(m): float(q or 0.0) for m, q in rows})
    return totals


def overage_opted_in(session: Session, user_id: str) -> bool:
    from app.models.db.repositories import ConsentRepository

    record = ConsentRepository(session).get_latest(user_id, OVERAGE_KIND)
    return bool(record is not None and record.granted and record.version == OVERAGE_TERMS_VERSION)


def set_overage(session: Session, user_id: str, opt_in: bool) -> bool:
    from app.models.db.repositories import ConsentRepository

    ConsentRepository(session).create(user_id, OVERAGE_KIND, bool(opt_in), OVERAGE_TERMS_VERSION)
    return overage_opted_in(session, user_id)


def over_cap(session: Session, user_id: str, meter: str, *, now: Optional[datetime] = None) -> bool:
    """True when ``meter`` reached its cap this month and the creator has not opted into overage."""
    if meter not in METERS:
        raise KeyError(meter)
    moment = now or datetime.now(timezone.utc)
    if overage_opted_in(session, user_id):
        return False
    used = month_to_date(session, user_id, moment)[meter]
    return used >= allowance(caps_for(session, user_id), meter, moment)


def require_under_cap(session: Session, user_id: str, meter: str, *, now: Optional[datetime] = None) -> None:
    if over_cap(session, user_id, meter, now=now):
        label = {"encode_minutes": "encoding", "ai_minutes": "AI minutes", "gb_stored": "storage",
                 "minutes_delivered": "streaming"}[meter]
        raise OttPlanError(402, "ott_cap", f"You have used this month's {label} on your plan. "
                                           "Turn on overage or upgrade to keep going.")


def plan_view(session: Session, user_id: str, *, now: Optional[datetime] = None) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    key = plan_key(session, user_id)
    caps = PLAN_CAPS[key]
    used = month_to_date(session, user_id, moment)
    meters = []
    for meter in METERS:
        included = allowance(caps, meter, moment)
        meters.append({"meter": meter, "unit": UNITS[meter], "used": round(used[meter], 2),
                       "included": round(included, 2), "cap_is_target": True,
                       "at_cap": used[meter] >= included})
    return {"plan": key, "month": f"{moment:%Y-%m}", "meters": meters, "caps": asdict(caps),
            "overage": {"opted_in": overage_opted_in(session, user_id), "terms_version": OVERAGE_TERMS_VERSION},
            "ott_plans_sellable": sellable()}


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
router = new_router()
_PLANS = [Depends(flags.require("plans"))]


class OverageBody(BaseModel):
    opt_in: bool


def _run(request: Request, fn):
    from app.controllers.v1.jobs import _require_db, _resolve_user, get_session

    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        return utils.get_response(200, fn(session, str(user.id)))


@router.get("/ott/studio/plan", dependencies=_PLANS, summary="My OTT caps, usage this month and overage")
def get_plan(request: Request):
    return _run(request, lambda s, uid: plan_view(s, uid))


@router.post("/ott/studio/plan/overage", dependencies=_PLANS, summary="Opt in or out of OTT overage")
def post_overage(request: Request, body: OverageBody):
    def _set(s, uid):
        set_overage(s, uid, body.opt_in)
        return plan_view(s, uid)

    return _run(request, _set)


__all__ = ["METERS", "OVERAGE_KIND", "OVERAGE_TERMS_VERSION", "OttCaps", "OttPlanError", "PLAN_CAPS", "allowance",
           "caps_for", "month_bounds", "month_to_date", "over_cap", "overage_opted_in", "plan_key", "plan_view",
           "require_under_cap", "router", "sellable", "set_overage"]
