"""Allocator use cases: propose, decide, apply, report.

A proposal is one row per user per day in ``ad_allocation_proposals`` plus a
mirrored ``approval_items`` row (source ``ad_budget``) so it shows up in the
shared approvals feed. Applying an approved proposal:

* re-budgets each paid network's *active* campaigns (in the proposal's
  currency) proportionally to their current daily budgets, then runs the
  existing per-creative optimizer, which pushes the ad-set budgets to the
  platform (Thompson split across creatives, platform minimums respected);
* records manual networks (organic boosts) as "apply by hand", since Menivor
  has no API to move that money.

Business failures raise :class:`AllocatorError` (an :class:`AdsError`, so the
paid-ads HTTP adapter maps it the same way).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select

from app.domains.ads import config as ads_config
from app.domains.ads import optimizer, store
from app.domains.ads.allocation_models import (
    STATUS_APPLIED,
    STATUS_APPROVED,
    STATUS_FAILED,
    STATUS_PROPOSED,
    STATUS_REJECTED,
    AdAllocationProposal,
)
from app.domains.ads.allocator import config as alloc_config
from app.domains.ads.allocator import engine
from app.domains.ads.allocator.stats import Collected, ManualNetwork, collect, manual_from_records
from app.domains.ads.bandit import seed_from_string
from app.domains.ads.platforms import minor_factor
from app.domains.ads.service import MAX_DAILY_BUDGET_MINOR, AdsError
from app.domains.approvals import models as approvals

MICROS = 1_000_000
MAX_TOTAL_DAILY_MINOR = 50_000_000  # sanity ceiling for one account's daily total
HISTORY_LIMIT = 30
LABELS = {"meta": "Meta", "tiktok": "TikTok", "organic_boost": "Organic boosts", "google": "Google", "linkedin": "LinkedIn"}


class AllocatorError(AdsError):
    pass


def to_micros(minor: int, currency: str) -> int:
    return int(minor) * (MICROS // minor_factor(currency))


def to_minor(micros: int, currency: str) -> int:
    return int(micros) // (MICROS // minor_factor(currency))


def _today(now: datetime | None) -> date:
    return (now or datetime.now(timezone.utc)).date()


# --------------------------------------------------------------------- views
def proposal_view(p: AdAllocationProposal) -> dict:
    stats = p.network_stats or {}
    meta = stats.get("_meta") if isinstance(stats.get("_meta"), dict) else {}
    networks = [n for n in (p.proposed_split or {})]
    total_minor = to_minor(p.total_daily_budget_micros, p.currency)
    proposed_minor = engine.split_budget(total_minor, dict(p.proposed_split or {}))
    current_minor = engine.split_budget(total_minor, dict(p.current_split or {}))
    rows = []
    for n in networks:
        rec = stats.get(n) or {}
        rows.append({
            "network": n, "label": LABELS.get(n, n), "source": rec.get("source", "measured"),
            "current_share": (p.current_split or {}).get(n, 0.0), "proposed_share": (p.proposed_split or {}).get(n, 0.0),
            "current_daily_minor": current_minor.get(n, 0), "proposed_daily_minor": proposed_minor.get(n, 0),
            "p_best": (meta.get("p_best") or {}).get(n), "warning": (meta.get("warnings") or {}).get(n, ""),
            "spend_minor": rec.get("spend_minor", 0), "results": rec.get("results", 0),
            "cost_per_result_minor": rec.get("cost_per_result_minor"),
        })
    return {
        "id": p.id, "run_date": p.run_date.isoformat(), "currency": p.currency, "metric": meta.get("metric", "clicks"),
        "total_daily_minor": total_minor, "max_delta": p.max_delta, "method": p.method, "reason": p.reason,
        "status": p.status, "approval_item_id": p.approval_item_id, "error": p.error or None,
        "applied_at": p.applied_at.isoformat() if p.applied_at else None,
        "apply_result": meta.get("apply_result") or None, "networks": rows,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


# ------------------------------------------------------------------ propose
def _stats_record(c: Collected, plan: engine.SplitPlan, extra: dict | None = None) -> dict:
    out: dict[str, Any] = {}
    for s in c.networks:
        cpr = engine.cost_per_result_minor(s)
        out[s.network] = {**s.to_record(), "cost_per_result_minor": cpr,
                          "cost_per_result_micros": None if cpr is None else int(to_micros(1, c.currency) * cpr)}
    out["_meta"] = {"metric": c.metric, "p_best": plan.p_best, "warnings": plan.warnings, "excluded": c.excluded,
                    "campaigns": c.campaigns, **(extra or {})}
    return out


def _approval_payload(p: AdAllocationProposal) -> dict:
    view = proposal_view(p)
    return {
        "kind": "ad_budget_split", "proposal_id": p.id, "currency": p.currency,
        "total_daily_minor": view["total_daily_minor"], "max_delta": p.max_delta,
        "networks": [{k: r[k] for k in ("network", "current_share", "proposed_share", "current_daily_minor",
                                         "proposed_daily_minor", "warning")} for r in view["networks"]],
    }


def _summary(p: AdAllocationProposal) -> str:
    parts = []
    for n, share in (p.proposed_split or {}).items():
        cur = (p.current_split or {}).get(n, 0.0)
        parts.append(f"{LABELS.get(n, n)} {cur:.0%} -> {share:.0%}")
    return "; ".join(parts) + f". {p.reason}"


def _sync_approval(session: Any, p: AdAllocationProposal) -> approvals.ApprovalItem:
    item = session.execute(select(approvals.ApprovalItem).where(
        approvals.ApprovalItem.user_id == p.user_id,
        approvals.ApprovalItem.source == approvals.SOURCE_AD_BUDGET,
        approvals.ApprovalItem.external_ref == p.id,
    )).scalar_one_or_none()
    if item is None:
        item = approvals.ApprovalItem(user_id=p.user_id, workspace_id=p.workspace_id,
                                      source=approvals.SOURCE_AD_BUDGET, external_ref=p.id)
        session.add(item)
    item.title = f"Ad budget split for {p.run_date.isoformat()}"[:300]
    item.summary = _summary(p)
    item.risk = approvals.RISK_HIGH
    item.payload = _approval_payload(p)
    item.edited_payload = None
    item.status = approvals.STATUS_PENDING
    item.decided_by, item.decided_via, item.decided_at, item.decision_note = None, "", None, ""
    item.result, item.error = {}, ""
    session.flush()
    return item


def propose(
    session: Any,
    user_id: str,
    *,
    total_daily_minor: int | None = None,
    manual: list[ManualNetwork] | None = None,
    now: datetime | None = None,
    auto_apply: bool = True,
) -> dict:
    """Build (or rebuild) today's proposal and queue it for approval."""
    now = now or datetime.now(timezone.utc)
    run_date = _today(now)
    existing = session.execute(select(AdAllocationProposal).where(
        AdAllocationProposal.user_id == user_id, AdAllocationProposal.run_date == run_date,
    )).scalar_one_or_none()
    if existing is not None and existing.status in (STATUS_APPROVED, STATUS_APPLIED):
        raise AllocatorError(409, "Today's budget split was already approved. A new proposal runs tomorrow.")
    if manual is None:
        manual = _latest_manual(session, user_id)
    collected = collect(session, user_id, manual)
    if not collected.networks:
        raise AllocatorError(409, "No paid campaigns or manual network results yet. Launch a campaign or add "
                                  "results for a network first.")
    current_total = sum(s.current_daily_minor for s in collected.networks)
    total = current_total if total_daily_minor is None else int(total_daily_minor)
    if total <= 0:
        raise AllocatorError(422, "Set a total daily budget: no campaign is currently active to take it from.")
    if total > MAX_TOTAL_DAILY_MINOR:
        raise AllocatorError(422, "The total daily budget is above the allowed limit.")

    cfg = alloc_config.load()
    plan = engine.plan_split(collected.networks, seed=seed_from_string(f"{user_id}:{run_date.isoformat()}"),
                             max_step=cfg.max_step, min_share=cfg.min_share, min_results=cfg.min_results)
    p = existing or AdAllocationProposal(user_id=user_id, run_date=run_date)
    if existing is None:
        session.add(p)
    p.window_days = 0  # lifetime totals as of each campaign's last sync
    p.currency = collected.currency
    p.total_daily_budget_micros = to_micros(total, collected.currency)
    p.network_stats = _stats_record(collected, plan)
    p.current_split = plan.current
    p.proposed_split = plan.proposed
    p.max_delta = plan.max_delta
    p.method = plan.method
    p.reason = plan.reason[:2000]
    p.status = STATUS_PROPOSED
    p.applied_at = None
    p.error = ""
    session.flush()
    item = _sync_approval(session, p)
    p.approval_item_id = item.id
    session.flush()

    if auto_apply and _auto_ok(cfg, p, collected):
        _decide(session, p, item, approve=True, via="auto", actor="menivor-allocator",
                note=f"Auto-applied: largest move {p.max_delta:.0%} is within the {cfg.auto_apply_delta:.0%} limit.",
                now=now)
    return proposal_view(p)


def _auto_ok(cfg: alloc_config.AllocatorConfig, p: AdAllocationProposal, c: Collected) -> bool:
    if cfg.auto_apply_delta <= 0 or p.max_delta <= 0 or p.max_delta > cfg.auto_apply_delta:
        return False
    if any(s.source == "manual" for s in c.networks):
        return False  # a human must move organic money anyway
    return all(ads_config.platform_config(n).enabled for n in c.campaigns)


def _latest_manual(session: Any, user_id: str) -> list[ManualNetwork]:
    last = session.execute(select(AdAllocationProposal).where(AdAllocationProposal.user_id == user_id)
                           .order_by(AdAllocationProposal.run_date.desc()).limit(1)).scalar_one_or_none()
    return manual_from_records(last.network_stats) if last is not None else []


# ------------------------------------------------------------------- decide
def get_owned(session: Any, user_id: str, proposal_id: str) -> AdAllocationProposal:
    p = session.execute(select(AdAllocationProposal).where(
        AdAllocationProposal.id == proposal_id, AdAllocationProposal.user_id == user_id,
    )).scalar_one_or_none()
    if p is None:
        raise AllocatorError(404, "Budget proposal not found.")
    return p


def _item_for(session: Any, p: AdAllocationProposal) -> approvals.ApprovalItem | None:
    if not p.approval_item_id:
        return None
    return session.get(approvals.ApprovalItem, p.approval_item_id)


def validate_split(split: dict[str, float], networks: list[str]) -> dict[str, float]:
    unknown = set(split) - set(networks)
    if unknown:
        raise AllocatorError(422, f"Unknown network(s) in the edited split: {', '.join(sorted(unknown))}.")
    if any(float(v) < 0 for v in split.values()):
        raise AllocatorError(422, "Shares cannot be negative.")
    total = sum(float(split.get(n, 0.0)) for n in networks)
    if not 0.99 <= total <= 1.01:
        raise AllocatorError(422, "Shares must add up to 100%.")
    return engine._round_split(engine.normalize(split, networks), networks)


def decide(session: Any, user_id: str, proposal_id: str, *, approve: bool, note: str = "",
           split: dict[str, float] | None = None, now: datetime | None = None) -> dict:
    p = get_owned(session, user_id, proposal_id)
    if p.status != STATUS_PROPOSED:
        raise AllocatorError(409, f"This proposal is already {p.status}.")
    item = _item_for(session, p)
    if item is not None and item.status != approvals.STATUS_PENDING:
        raise AllocatorError(409, f"The approval for this proposal is already {item.status}.")
    edited = False
    if approve and split:
        p.proposed_split = validate_split(split, list(p.proposed_split or {}))
        p.max_delta = round(max(abs(p.proposed_split[n] - (p.current_split or {}).get(n, 0.0))
                                for n in p.proposed_split), 4)
        edited = True
    _decide(session, p, item, approve=approve, via="report", actor=user_id, note=note, now=now, edited=edited)
    return proposal_view(p)


def execute_approval(session: Any, item: approvals.ApprovalItem, *, approve: bool = True, actor: str = "",
                     via: str = "approvals", note: str = "", now: datetime | None = None) -> dict:
    """Hook for the approvals feed: apply (or reject) the proposal behind ``item``.

    Honors ``item.edited_payload['split']`` when the reviewer edited shares.
    """
    p = get_owned(session, item.user_id, item.external_ref)
    if p.status != STATUS_PROPOSED:
        raise AllocatorError(409, f"This proposal is already {p.status}.")
    edited_split = (item.edited_payload or {}).get("split") if isinstance(item.edited_payload, dict) else None
    edited = False
    if approve and isinstance(edited_split, dict) and edited_split:
        p.proposed_split = validate_split({k: float(v) for k, v in edited_split.items()}, list(p.proposed_split or {}))
        edited = True
    _decide(session, p, item, approve=approve, via=via, actor=actor or item.user_id, note=note, now=now, edited=edited)
    return proposal_view(p)


def _decide(session: Any, p: AdAllocationProposal, item: approvals.ApprovalItem | None, *, approve: bool, via: str,
            actor: str, note: str, now: datetime | None, edited: bool = False) -> None:
    now = now or datetime.now(timezone.utc)
    if item is not None:
        item.decided_by, item.decided_via, item.decided_at = actor[:64], via[:16], now
        item.decision_note = (note or "")[:2000]
    if not approve:
        p.status = STATUS_REJECTED
        if item is not None:
            item.status = approvals.STATUS_REJECTED
        session.flush()
        return
    p.status = STATUS_APPROVED
    if item is not None:
        item.status = approvals.STATUS_EDITED if edited else approvals.STATUS_APPROVED
        if edited:
            item.edited_payload = {"split": dict(p.proposed_split)}
    session.flush()
    result = apply(session, p, now=now)
    if item is not None:
        item.result = result
        item.status = approvals.STATUS_FAILED if p.status == STATUS_FAILED else approvals.STATUS_EXECUTED
        item.error = p.error or ""
    session.flush()


def apply_approved(session: Any, user_id: str, proposal_id: str, *, now: datetime | None = None) -> dict:
    """Apply a proposal approved elsewhere (the approvals feed marks it ``approved`` and stops there)."""
    p = get_owned(session, user_id, proposal_id)
    if p.status != STATUS_APPROVED:
        raise AllocatorError(409, f"Only approved proposals can be applied; this one is {p.status}.")
    apply(session, p, now=now)
    item = _item_for(session, p)
    if item is not None and not item.result:
        item.result = dict((p.network_stats or {}).get("_meta", {}).get("apply_result") or {})
        item.error = p.error or ""
        session.flush()
    return proposal_view(p)


def approved_waiting(session: Any, limit: int = 200) -> list[tuple[str, str]]:
    """(user_id, proposal_id) of proposals approved but not yet applied, oldest first."""
    stmt = (select(AdAllocationProposal.user_id, AdAllocationProposal.id)
            .where(AdAllocationProposal.status == STATUS_APPROVED)
            .order_by(AdAllocationProposal.updated_at).limit(limit))
    return [(str(u), str(i)) for u, i in session.execute(stmt).all()]


# -------------------------------------------------------------------- apply
def _campaign_budgets(new_total: int, current: dict[str, int]) -> dict[str, int]:
    keys = list(current)
    weights = {k: float(max(0, v)) for k, v in current.items()}
    split = engine.normalize(weights, keys)
    return engine.split_budget(new_total, split)


def _apply_network(session: Any, user_id: str, network: str, keys: list[str], new_total: int,
                   now: datetime) -> dict:
    if not keys:
        return {"network": network, "ok": False, "detail": "No active campaign in this currency to receive budget."}
    cfg = ads_config.platform_config(network)
    rows_by_key = {k: store.campaign_rows(session, user_id, k) for k in keys}
    current = {k: int((rows[0][1].get("campaign") or {}).get("daily_budget_minor") or 0)
               for k, rows in rows_by_key.items() if rows}
    targets = _campaign_budgets(new_total, current)
    done, problems = [], []
    for key, budget in targets.items():
        old = current[key]
        if budget < cfg.min_daily_budget_minor:
            problems.append(f"{key}: {budget} is below the platform minimum {cfg.min_daily_budget_minor}; kept {old}")
            continue
        budget = min(budget, MAX_DAILY_BUDGET_MINOR)
        if budget == old:
            done.append({"key": key, "from": old, "to": budget})
            continue
        store.update_campaign(rows_by_key[key], key, daily_budget_minor=budget)
        session.flush()
        try:
            optimizer.optimize(session, user_id, key, now=now)
        except AdsError as exc:
            store.update_campaign(store.campaign_rows(session, user_id, key), key, daily_budget_minor=old)
            session.flush()
            problems.append(f"{key}: {exc.message}")
            continue
        done.append({"key": key, "from": old, "to": budget})
    return {"network": network, "ok": not problems, "campaigns": done, "detail": "; ".join(problems)}


def apply(session: Any, p: AdAllocationProposal, *, now: datetime | None = None) -> dict:
    """Move money per the approved split. Returns a per-network result record."""
    now = now or datetime.now(timezone.utc)
    stats = dict(p.network_stats or {})
    meta = dict(stats.get("_meta") or {})
    campaigns = meta.get("campaigns") or {}
    total_minor = to_minor(p.total_daily_budget_micros, p.currency)
    budgets = engine.split_budget(total_minor, dict(p.proposed_split or {}))
    results = []
    for network, budget in budgets.items():
        source = (stats.get(network) or {}).get("source", "measured")
        if source == "manual" or network not in ads_config.PLATFORMS:
            results.append({"network": network, "ok": True, "manual": True, "daily_minor": budget,
                            "detail": "No API for this network. Move this budget by hand."})
            continue
        try:
            outcome = _apply_network(session, p.user_id, network, list(campaigns.get(network) or []), budget, now)
        except AdsError as exc:
            outcome = {"network": network, "ok": False, "detail": exc.message}
        results.append({**outcome, "daily_minor": budget})
    paid = [r for r in results if not r.get("manual")]
    failed = [r for r in paid if not r["ok"]]
    p.status = STATUS_FAILED if paid and len(failed) == len(paid) else STATUS_APPLIED
    p.error = "; ".join(f"{r['network']}: {r['detail']}" for r in failed)[:2000]
    p.applied_at = now if p.status == STATUS_APPLIED else None
    record = {"networks": results, "at": now.isoformat()}
    p.network_stats = {**stats, "_meta": {**meta, "apply_result": record}}
    session.flush()
    return record


# ------------------------------------------------------------------- report
def report(session: Any, user_id: str) -> dict:
    """Which network pays off: cost per result per network with sample-size warnings."""
    cfg = alloc_config.load()
    manual = _latest_manual(session, user_id)
    c = collect(session, user_id, manual)
    rows = []
    for s in c.networks:
        rows.append({
            "network": s.network, "label": LABELS.get(s.network, s.network), "source": s.source,
            "spend_minor": s.spend_minor, "results": s.results, "impressions": s.impressions, "clicks": s.clicks,
            "leads": s.leads, "campaigns": s.campaigns, "current_daily_minor": s.current_daily_minor,
            "cost_per_result_minor": engine.cost_per_result_minor(s),
            "ctr": round(s.clicks / s.impressions, 6) if s.impressions > 0 and s.source != "manual" else None,
            "warning": engine.sample_warning(s, cfg.min_results),
        })
    ranked = sorted([r for r in rows if r["cost_per_result_minor"] is not None],
                    key=lambda r: r["cost_per_result_minor"])
    history = session.execute(select(AdAllocationProposal).where(AdAllocationProposal.user_id == user_id)
                              .order_by(AdAllocationProposal.run_date.desc()).limit(HISTORY_LIMIT)).scalars().all()
    return {
        "currency": c.currency, "metric": c.metric, "networks": rows, "excluded": c.excluded,
        "cheapest": ranked[0]["network"] if ranked else None,
        "settings": {"max_step": cfg.max_step, "min_share": cfg.min_share, "min_results": cfg.min_results,
                     "auto_apply_delta": cfg.auto_apply_delta},
        "gate": ads_config.status(),
        "latest": proposal_view(history[0]) if history else None,
        "history": [{"id": h.id, "run_date": h.run_date.isoformat(), "status": h.status, "max_delta": h.max_delta,
                     "reason": h.reason, "proposed_split": h.proposed_split, "current_split": h.current_split}
                    for h in history],
    }


def list_proposals(session: Any, user_id: str, limit: int = HISTORY_LIMIT) -> list[dict]:
    rows = session.execute(select(AdAllocationProposal).where(AdAllocationProposal.user_id == user_id)
                           .order_by(AdAllocationProposal.run_date.desc()).limit(limit)).scalars().all()
    return [proposal_view(p) for p in rows]


def daily_users(session: Any, since: date) -> list[str]:
    """Users who opted in by creating a proposal on or after ``since``."""
    stmt = select(AdAllocationProposal.user_id).where(AdAllocationProposal.run_date >= since).distinct()
    return [str(u) for u in session.execute(stmt).scalars().all()]


__all__ = ["AllocatorError", "apply", "apply_approved", "approved_waiting", "daily_users", "decide", "execute_approval", "get_owned", "list_proposals",
           "proposal_view", "propose", "report", "to_micros", "to_minor", "validate_split"]
