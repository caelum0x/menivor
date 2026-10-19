"""Funnel read-out (MR1): one row per user who signed up since a date.

Columns: sign-up, card check, first render, first kept reel, first payment,
plan, and source (partner source, UTM source/medium/campaign, referrer).

Data comes from what already exists: ``users.created_at``, the ``16bfdc06``
``funnel_events`` rows (card check, first reel, paid; kept fresh by the daily
``sync_events``), the jobs table (a kept reel is a finished job that is not an
unpaid charge-on-keep variant), live creator plans, and the first-touch
``funnel_attribution`` row. Read-only apart from :func:`record_attribution`.

Unknown is spelled ``"unknown"``, never ``0``: a user with no attribution row
has source ``unknown``, and a step not reached is ``None`` (shown as "no").
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import select

from app.domains.funnel_readout.models import FunnelAttribution

#: MR1 starts at the public launch (2026-09-25).
DEFAULT_SINCE = datetime(2026, 9, 25, tzinfo=timezone.utc)
UNKNOWN = "unknown"
PARTNER_SOURCES = frozenset({"scribase", "rally"})
STEPS = ("signed_up", "card_check", "first_render", "first_kept", "first_payment")
_MAX = {"source": 40, "utm_source": 120, "utm_medium": 120, "utm_campaign": 120, "referrer": 300}


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    value = _utc(value)
    return value.isoformat() if value else None


def _clean(field: str, value: Any) -> str:
    text = str(value or "").strip()
    return "".join(ch for ch in text if ch.isprintable())[: _MAX[field]]


@dataclass(frozen=True)
class ReadoutRow:
    user_id: str
    email: str
    signed_up: str | None
    card_check: str | None
    first_render: str | None
    first_kept: str | None
    first_payment: str | None
    plan: str
    source: str
    utm_source: str
    utm_medium: str
    utm_campaign: str
    referrer: str


def record_attribution(
    session: Any,
    user_id: str,
    *,
    source: str = "",
    utm_source: str = "",
    utm_medium: str = "",
    utm_campaign: str = "",
    referrer: str = "",
) -> bool:
    """Record a user's first-touch source once. True when a row was written.

    A partner ``source`` must be ``scribase`` or ``rally``. An existing row is
    never overwritten (first touch wins). The caller's session commits.
    """
    if not user_id:
        return False
    partner = _clean("source", source).lower()
    if partner and partner not in PARTNER_SOURCES:
        raise ValueError(f"unknown partner source {partner!r}")
    if session.get(FunnelAttribution, str(user_id)) is not None:
        return False
    session.add(
        FunnelAttribution(
            user_id=str(user_id),
            source=partner,
            utm_source=_clean("utm_source", utm_source),
            utm_medium=_clean("utm_medium", utm_medium),
            utm_campaign=_clean("utm_campaign", utm_campaign),
            referrer=_clean("referrer", referrer),
        )
    )
    session.flush()
    return True


def _events(session: Any, user_ids: list[str]) -> dict[tuple[str, str], datetime]:
    from app.models.db.funnel import FunnelEvent

    if not user_ids:
        return {}
    rows = session.execute(
        select(FunnelEvent.user_id, FunnelEvent.step, FunnelEvent.occurred_at).where(
            FunnelEvent.user_id.in_(user_ids)
        )
    ).all()
    return {(str(u), str(s)): at for u, s, at in rows}


def _first_kept(session: Any, user_ids: list[str]) -> dict[str, datetime]:
    from app.domains.reels.keep import is_pending
    from app.models.const import TASK_STATE_COMPLETE
    from app.models.db.models import Job

    if not user_ids:
        return {}
    rows = session.execute(
        select(Job.user_id, Job.updated_at, Job.params).where(
            Job.user_id.in_(user_ids), Job.state == TASK_STATE_COMPLETE
        )
    ).all()
    first: dict[str, datetime] = {}
    for user_id, at, params in rows:
        uid, at = str(user_id), _utc(at)
        if at is None or is_pending(params):
            continue
        if uid not in first or at < first[uid]:
            first[uid] = at
    return first


def _plans(session: Any, user_ids: list[str]) -> dict[str, str]:
    from app.models.db.creator_subscription import CreatorSubscription
    from app.services.billing.creator_subscriptions import is_live

    if not user_ids:
        return {}
    rows = session.execute(
        select(CreatorSubscription).where(CreatorSubscription.user_id.in_(user_ids))
    ).scalars()
    return {str(r.user_id): str(r.plan_key) for r in rows if is_live(r)}


def _plan_label(user_id: str, live_plans: dict[str, str], paid_at: datetime | None) -> str:
    if user_id in live_plans:
        return live_plans[user_id]
    return "pack" if paid_at else "free"


def readout(session: Any, since: datetime = DEFAULT_SINCE) -> list[ReadoutRow]:
    """Every user who signed up at or after ``since``, oldest first."""
    from app.models.db.models import User

    since_utc = _utc(since) or DEFAULT_SINCE
    users = [
        (str(uid), str(email or ""), _utc(created))
        for uid, email, created in session.execute(
            select(User.id, User.email, User.created_at).order_by(User.created_at)
        ).all()
    ]
    from app.services.funnel.internal import is_internal_email

    users = [
        u for u in users
        if u[2] is not None and u[2] >= since_utc and not is_internal_email(u[1])
    ]
    ids = [u[0] for u in users]
    events = _events(session, ids)
    kept = _first_kept(session, ids)
    plans = _plans(session, ids)
    attribution = {
        str(a.user_id): a
        for a in session.execute(
            select(FunnelAttribution).where(FunnelAttribution.user_id.in_(ids))
        ).scalars()
    } if ids else {}
    out: list[ReadoutRow] = []
    for uid, email, created in users:
        paid = events.get((uid, "paid"))
        attr = attribution.get(uid)
        out.append(
            ReadoutRow(
                user_id=uid,
                email=email,
                signed_up=_iso(created),
                card_check=_iso(events.get((uid, "card_check"))),
                first_render=_iso(events.get((uid, "first_reel"))),
                first_kept=_iso(kept.get(uid)),
                first_payment=_iso(paid),
                plan=_plan_label(uid, plans, paid),
                source=(attr.source if attr and attr.source else UNKNOWN),
                utm_source=(attr.utm_source if attr and attr.utm_source else UNKNOWN),
                utm_medium=(attr.utm_medium if attr and attr.utm_medium else UNKNOWN),
                utm_campaign=(attr.utm_campaign if attr and attr.utm_campaign else UNKNOWN),
                referrer=(attr.referrer if attr and attr.referrer else UNKNOWN),
            )
        )
    return out


def totals(rows: Iterable[ReadoutRow]) -> dict[str, Any]:
    """Step reach, plan mix and source mix. Buckets with no data say ``unknown``."""
    rows = list(rows)
    reach = {
        "signed_up": sum(1 for r in rows if r.signed_up),
        "card_check": sum(1 for r in rows if r.card_check),
        "first_render": sum(1 for r in rows if r.first_render),
        "first_kept": sum(1 for r in rows if r.first_kept),
        "first_payment": sum(1 for r in rows if r.first_payment),
    }
    by_source: dict[str, int] = {}
    by_campaign: dict[str, int] = {}
    by_plan: dict[str, int] = {}
    for r in rows:
        label = r.source if r.source != UNKNOWN else (r.utm_source if r.utm_source != UNKNOWN else UNKNOWN)
        by_source[label] = by_source.get(label, 0) + 1
        by_campaign[r.utm_campaign] = by_campaign.get(r.utm_campaign, 0) + 1
        by_plan[r.plan] = by_plan.get(r.plan, 0) + 1
    return {"users": len(rows), "reach": reach, "by_source": by_source,
            "by_campaign": by_campaign, "by_plan": by_plan}


def readout_payload(session: Any, since: datetime = DEFAULT_SINCE) -> dict[str, Any]:
    """The JSON the admin page, the CLI and the scoreboard (XR-D2) read."""
    rows = readout(session, since)
    return {
        "since": _iso(since),
        "generated_at": _iso(datetime.now(timezone.utc)),
        "totals": totals(rows),
        "rows": [asdict(r) for r in rows],
    }
