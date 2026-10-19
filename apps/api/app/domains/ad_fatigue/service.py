"""Fatigue report over ``integration_ad_metrics`` and the "make variations" action.

Visibility is exactly the Integrations rule (workspace scope, Brand space). "Make
variations" never generates anything: it proposes a pending Brand Agent batch
action (3 fresh variations of the tired creative) that waits for approval.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import select

from app.domains.ad_fatigue import fatigue
from app.domains.integrations import metrics
from app.domains.integrations.errors import IntegrationError
from app.domains.integrations.models import IntegrationAdMetric
from app.domains.integrations.scope import Scope
from app.domains.integrations.service import get_account, visible_accounts

DEFAULT_DAYS = 14
VARIATIONS = 3
_STATUS_ORDER = {"fatigued": 0, "watch": 1, "fresh": 2, "not_enough_data": 3}


def _minor(value: int | None, currency: str) -> float:
    from app.domains.ads.platforms import from_minor

    return float(from_minor(int(value or 0), currency))


def report(session: Any, scope: Scope, *, ad_account_id: str | None = None, days: int = DEFAULT_DAYS,
           today: date | None = None) -> dict[str, Any]:
    since, until = metrics.window(max(7, min(int(days or DEFAULT_DAYS), 60)), today)
    accounts = [get_account(session, scope, ad_account_id)] if ad_account_id else visible_accounts(session, scope)
    by_id = {a.id: a for a in accounts}
    rows = session.execute(select(IntegrationAdMetric).where(
        IntegrationAdMetric.ad_account_id.in_(list(by_id) or [""]),
        IntegrationAdMetric.day >= since.isoformat(), IntegrationAdMetric.day <= until.isoformat())).scalars().all()
    groups: dict[tuple[str, str], list[IntegrationAdMetric]] = defaultdict(list)
    for r in rows:
        groups[(r.ad_account_id, r.entity_id)].append(r)
    creatives = []
    for (account_id, entity_id), group in groups.items():
        account = by_id[account_id]
        result = fatigue.analyze(fatigue.Day(
            day=r.day, impressions=int(r.impressions or 0), clicks=int(r.clicks or 0),
            spend=_minor(r.spend_minor, r.currency or account.currency), conversions=r.conversions,
            reach=getattr(r, "reach", None)) for r in group)
        name = next((r.entity_name for r in sorted(group, key=lambda r: r.day, reverse=True) if r.entity_name), "")
        creatives.append({"ad_account_id": account_id, "ad_account_name": account.name, "provider": account.provider,
                          "entity_id": entity_id, "entity_name": name or entity_id, "currency": account.currency,
                          "spend": round(sum(_minor(r.spend_minor, account.currency) for r in group), 2), **result})
    creatives.sort(key=lambda c: (_STATUS_ORDER[c["status"]], -(c["score"] or 0), -c["spend"]))
    counts = {s: sum(1 for c in creatives if c["status"] == s) for s in _STATUS_ORDER}
    return {"since": since.isoformat(), "until": until.isoformat(), "creatives": creatives, "counts": counts,
            "accounts": [{"id": a.id, "name": a.name, "provider": a.provider} for a in accounts],
            "thresholds": {"fatigued": fatigue.FATIGUED, "watch": fatigue.WATCH, "min_days": fatigue.MIN_DAYS,
                           "min_impressions": fatigue.MIN_IMPRESSIONS}}


def make_variations(session: Any, scope: Scope, *, ad_account_id: str, entity_id: str, space_id: str | None = None,
                    media: str = "video", today: date | None = None) -> dict[str, Any]:
    """Propose (never run) a batch of fresh variations for one creative."""
    from app.domains.brand_agent import gate, spaces

    found = report(session, scope, ad_account_id=ad_account_id, today=today)
    creative = next((c for c in found["creatives"] if c["entity_id"] == entity_id), None)
    if creative is None:
        raise IntegrationError(404, "That ad has no metrics in this window.")
    space = spaces.resolve(session, scope.user_id, space_id)
    why = "; ".join(creative["reasons"]) or "fresh angles before it tires"
    kind = "video" if media == "video" else "image"
    action = gate.propose(
        session, scope.user_id, space.id, None, kind=gate.KIND_ROUTINE_BATCH,
        title=f"{VARIATIONS} new variations of \"{creative['entity_name']}\""[:300],
        payload={"count": VARIATIONS, "skill": "ad_variations", "media": kind,
                 "prompt": f"New variations of the ad \"{creative['entity_name']}\": keep the offer, change the hook, "
                           f"first frame and visuals. Why: {why}",
                 "source": {"ad_account_id": ad_account_id, "entity_id": entity_id, "score": creative["score"],
                            "status": creative["status"]}})
    return {"action": action, "creative": {k: creative[k] for k in ("entity_id", "entity_name", "score", "status")}}


__all__ = ["DEFAULT_DAYS", "make_variations", "report"]
