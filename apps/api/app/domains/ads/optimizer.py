"""Sync + winner loop for paid campaigns.

* :func:`sync` advances creatives whose video the platform is still processing
  into live ads, then pulls lifetime spend / impressions / clicks / leads per ad
  and the campaign's effective status.
* :func:`optimize` re-splits the campaign's daily budget with Thompson sampling
  (:mod:`app.domains.ads.bandit`) over each live creative's CTR — or lead rate
  when the campaign optimizes for leads and the platform reports lead events —
  then applies the new ad-set budgets and pauses pruned creatives.

Auto-optimize runs from :func:`sync` at most once per ``AUTO_OPTIMIZE_EVERY``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.domains.ads import bandit, config, store
from app.domains.ads.platforms import AdCreativeInput, AdsApiError
from app.domains.ads.service import AdsError, _api, context

AUTO_OPTIMIZE_EVERY = timedelta(hours=24)
LEAD_MIN_CLICKS = 100


def _advance(client: Any, token: str, acct: Any, camp: dict, item: dict) -> dict:
    """Move one creative from ``processing`` to ``live`` once its video is ready."""
    if item.get("phase") != store.PHASE_PROCESSING or not item.get("video_id"):
        return item
    state = client.video_state(token, acct, item["video_id"])
    if state.failed:
        return {**item, "phase": store.PHASE_FAILED, "error": state.detail or "video processing failed"}
    if not state.ready:
        return item
    made = client.create_ad(token, acct, item["ad_group_id"], AdCreativeInput(
        name=f"{camp['name']} / {item.get('video_id', '')[-6:]}", video_id=item["video_id"],
        thumbnail_url=item.get("poster_url") or state.thumbnail_url, primary_text=item.get("primary_text", ""),
        headline=item.get("headline", ""), landing_url=camp["landing_url"], cta=camp.get("cta", "SHOP_NOW"),
    ))
    return {**item, **made, "phase": store.PHASE_LIVE, "error": ""}


def _due(camp: dict, now: datetime) -> bool:
    last = camp.get("optimized_at")
    if not last:
        return True
    try:
        stamp = datetime.fromisoformat(str(last))
    except ValueError:
        return True
    return now - stamp >= AUTO_OPTIMIZE_EVERY


def sync(session: Any, user_id: str, key: str, *, now: datetime | None = None) -> list[tuple[Any, dict]]:
    rows, camp, client, (token, acct) = context(session, user_id, key)
    now = now or datetime.now(timezone.utc)
    updated: list[tuple[Any, dict]] = []
    problems = []
    for variant, item in rows:
        try:
            fresh = _advance(client, token, acct, camp, item)
        except AdsApiError as exc:
            if exc.status_code == 401:
                raise _api(exc) from exc
            fresh = {**item, "error": exc.message}
            problems.append(exc.message)
        updated.append((variant, fresh))
    status = camp.get("status")
    try:
        stats = {s.ad_id: s for s in client.campaign_stats(token, acct, camp["external_id"])}
        platform_status = client.campaign_status(token, acct, camp["external_id"])
    except AdsApiError as exc:
        raise _api(exc) from exc
    for i, (variant, item) in enumerate(updated):
        hit = stats.get(item.get("ad_id") or "")
        if hit is not None:
            item = {**item, "stats": {"spend_minor": hit.spend_minor, "impressions": hit.impressions,
                                      "clicks": hit.clicks, "leads": hit.leads}}
        store.write(variant, key, {**item, "campaign": camp})
        updated[i] = (variant, item)
    if status != store.STATUS_ARCHIVED and platform_status:
        status = store.STATUS_ACTIVE if platform_status in ("active", "enable") else store.STATUS_PAUSED
    rows = store.update_campaign(updated, key, synced_at=now.isoformat(), status=status,
                                 error="; ".join(problems)[:500] if problems else "", platform_status=platform_status)
    session.flush()
    if camp.get("auto_optimize", True) and status == store.STATUS_ACTIVE and _due(camp, now):
        live = [r for r in rows if r[1].get("phase") == store.PHASE_LIVE]
        if len(live) > 1:
            rows = optimize(session, user_id, key, now=now)
    return rows


def arms_for(rows: list[tuple[Any, dict]], optimize_for: str) -> tuple[list[bandit.Arm], str]:
    """Evidence per live creative; falls back to CTR when no lead events exist."""
    live = [(v, i) for v, i in rows if i.get("phase") == store.PHASE_LIVE]
    stats = {v.id: i.get("stats") or {} for v, i in live}
    has_leads = any(s.get("leads") is not None for s in stats.values())
    metric = "leads" if optimize_for == "leads" and has_leads else "ctr"
    arms = []
    for vid, s in stats.items():
        if metric == "leads":
            arms.append(bandit.Arm(vid, trials=int(s.get("clicks") or 0), successes=int(s.get("leads") or 0)))
        else:
            arms.append(bandit.Arm(vid, trials=int(s.get("impressions") or 0), successes=int(s.get("clicks") or 0)))
    return arms, metric


def plan(rows: list[tuple[Any, dict]], camp: dict, key: str, now: datetime) -> tuple[bandit.Allocation, str]:
    """The allocation an optimize pass would apply now (pure given the rows)."""
    arms, metric = arms_for(rows, camp.get("optimize_for", "ctr"))
    if not arms:
        raise AdsError(409, "No ad is live yet, so there is nothing to optimize.")
    cfg = config.platform_config(camp["platform"])
    min_trials = bandit.DEFAULT_MIN_TRIALS if metric == "ctr" else LEAD_MIN_CLICKS
    alloc = bandit.allocate(arms, int(camp["daily_budget_minor"]), cfg.min_daily_budget_minor,
                            seed=bandit.seed_from_string(f"{key}:{now.date().isoformat()}"), min_trials=min_trials)
    return alloc, metric


def preview(session: Any, user_id: str, key: str, *, now: datetime | None = None) -> dict:
    rows, camp, _client, _auth = context(session, user_id, key)
    alloc, metric = plan(rows, camp, key, now or datetime.now(timezone.utc))
    return {**alloc.to_record(), "metric": metric, "applied": False}


def optimize(session: Any, user_id: str, key: str, *, now: datetime | None = None) -> list[tuple[Any, dict]]:
    rows, camp, client, (token, acct) = context(session, user_id, key)
    if camp.get("status") == store.STATUS_ARCHIVED:
        raise AdsError(409, "Archived campaigns are not optimized.")
    now = now or datetime.now(timezone.utc)
    alloc, metric = plan(rows, camp, key, now)
    by_id = {a.arm_id: a for a in alloc.arms}
    out = []
    for variant, item in rows:
        arm = by_id.get(variant.id)
        if arm is None:
            out.append((variant, item))
            continue
        try:
            if arm.active and arm.budget_minor != int(item.get("budget_minor") or 0):
                client.set_ad_group_budget(token, acct, item["ad_group_id"], arm.budget_minor)
            if arm.active != bool(item.get("active", True)):
                client.set_ad_group_status(token, acct, item["ad_group_id"], arm.active)
        except AdsApiError as exc:
            raise _api(exc) from exc
        fresh = {**item, "budget_minor": arm.budget_minor if arm.active else 0, "active": arm.active,
                 "p_best": round(arm.p_best, 4), "alloc_reason": arm.reason}
        out.append((variant, fresh))
    record = {**alloc.to_record(), "metric": metric, "applied": True, "at": now.isoformat()}
    for variant, item in out:
        store.write(variant, key, {**item, "campaign": camp})
    rows = store.update_campaign(out, key, optimized_at=now.isoformat(), allocation=record)
    session.flush()
    return rows


__all__ = ["arms_for", "optimize", "plan", "preview", "sync"]
