"""Owner emails: weekly funnel (Mondays from 07:00 UTC) and daily unit economics."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

from app.services import mailer
from app.services.funnel import report as funnel_report
from app.services.funnel import store

DEFAULT_REPORT_TO = "subasiarhan3@gmail.com"


def recipient() -> str:
    to = (os.environ.get("MENIVOR_FUNNEL_REPORT_TO") or "").strip()
    return to if "@" in to else DEFAULT_REPORT_TO


def run(now: datetime | None = None, force: bool = False) -> dict[str, Any]:
    """Sync the funnel; on Monday >= 07:00 UTC send the week's report once."""
    now = now or datetime.now(timezone.utc)
    sync = store.sync_events()
    if not force and not funnel_report.is_report_due(now):
        return {"status": "synced", **sync}

    week_start = funnel_report.week_start_utc(now)
    totals, week = store.load_counts(now - timedelta(days=7))
    rep = funnel_report.build_report(totals, week)
    key = week_start.date().isoformat()
    drop = rep.drop_off
    summary = {
        "totals": totals,
        "week": week,
        "drop_off": None if drop is None else {"from": drop.from_label, "to": drop.to_label, "rate": drop.rate},
    }
    if not store.claim_week(key, summary):
        return {"status": "already_sent", **sync}
    sent = mailer.send_email(
        to=recipient(),
        subject=funnel_report.subject(rep),
        text=funnel_report.text_body(rep, week_start),
        html=funnel_report.html_body(rep, week_start),
    )
    if not sent:
        store.release_week(key)
        logger.error("funnel: weekly owner email was not sent")
        return {"status": "send_failed", **sync}
    return {"status": "sent", **sync}


# --------------------------------------------------------------------------- #
# Daily unit-economics email (M1.5): yesterday's reels, what they cost us in
# providers, the credits that moved, and render speed (p50/p90).
# --------------------------------------------------------------------------- #
ECONOMICS_TTL_S = 36 * 60 * 60
#: Ledger reasons for credits a customer paid for (everything else positive is
#: a grant: signup, trial, admin, transfers).
_BOUGHT_TAGS = ("purchase", "topup", "dodo", "revenuecat", "checkout", "subscription", "pack")


def _credit_totals(session: Any, since: datetime, until: datetime) -> dict[str, int]:
    """Credits bought, spent on renders and refunded in the window (ledger reasons)."""
    from sqlalchemy import func, select

    from app.models.db.models import CreditLedger

    rows = session.execute(
        select(CreditLedger.reason, func.sum(CreditLedger.delta)).where(
            CreditLedger.created_at >= since, CreditLedger.created_at < until
        ).group_by(CreditLedger.reason)
    ).all()
    totals = {"bought": 0, "spent": 0, "refunded": 0, "granted": 0}
    for reason, delta in rows:
        name, amount = str(reason or ""), int(delta or 0)
        if amount < 0:
            totals["spent"] += -amount
        elif "refund" in name:
            totals["refunded"] += amount
        elif any(tag in name for tag in _BOUGHT_TAGS):
            totals["bought"] += amount
        else:
            totals["granted"] += amount
    return totals


def _fmt_s(seconds: float | None) -> str:
    if seconds is None:
        return "no data"
    return f"{seconds:.0f} s" if seconds < 120 else f"{seconds / 60.0:.1f} min"


def economics_text(day: str, summary: Any, credits: dict[str, int], spend_all_usd: float) -> str:
    """Plain-text body of the daily economics email."""
    finished = summary.reels_finished
    per_reel = f"${spend_all_usd / finished:.3f}" if finished else "no finished reels"
    rate = summary.failure_rate
    lines = [
        f"Menivor daily economics for {day} (UTC)",
        "",
        "Reels",
        f"  Finished: {finished}",
        f"  Failed: {summary.reels_failed}" + ("" if rate is None else f" ({rate:.0%})"),
        f"  Canary reels (not counted above): {summary.canary_reels}",
        "",
        "Cost",
        f"  Provider spend, all jobs: ${spend_all_usd:.2f}",
        f"  Provider spend per finished reel: {per_reel}",
        "",
        "Credits",
        f"  Bought: {credits['bought']}",
        f"  Spent on renders: {credits['spent']}",
        f"  Refunded: {credits['refunded']}",
        f"  Granted (signup, trial, admin): {credits['granted']}",
        "",
        "Speed",
        f"  Create to playable reel: p50 {_fmt_s(summary.time_to_reel.p50)}, "
        f"p90 {_fmt_s(summary.time_to_reel.p90)} ({summary.time_to_reel.count} reels)",
        f"  Wait for a render slot: p50 {_fmt_s(summary.render_queue_wait.p50)}, "
        f"p90 {_fmt_s(summary.render_queue_wait.p90)}",
    ]
    for stage, dist in summary.stage_seconds.items():
        if dist.count:
            lines.append(f"  {stage}: p50 {_fmt_s(dist.p50)}, p90 {_fmt_s(dist.p90)} ({dist.count})")
    lines += ["", "Credits are shown as credits, not money: prices differ by pack and plan."]
    return "\n".join(lines)


def run_daily_economics(now: datetime | None = None, force: bool = False) -> dict[str, Any]:
    """Send yesterday's economics email once per day (07:15 UTC beat)."""
    from app.domains.observability import render_metrics as rm
    from app.models.db.base import get_session

    now = now or datetime.now(timezone.utc)
    until = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since = until - timedelta(days=1)
    day = since.date().isoformat()
    store_ = rm._dedup_store()
    if not force and not store_.claim(f"econ:{day}", ECONOMICS_TTL_S):
        return {"status": "already_sent", "day": day}
    try:
        with get_session() as session:
            summary = rm.summary_for(session, since, until)
            spend = rm.provider_spend(session, since, until)
            credits = _credit_totals(session, since, until)
    except Exception as exc:  # noqa: BLE001 - never send a half report
        store_.release(f"econ:{day}")
        logger.error(f"economics: could not build the report: {exc}")
        return {"status": "error", "day": day}
    text = economics_text(day, summary, credits, spend)
    sent = mailer.send_email(
        to=recipient(), subject=f"Menivor economics {day}: {summary.reels_finished} reels, ${spend:.2f} providers", text=text
    )
    if not sent:
        store_.release(f"econ:{day}")
        logger.error("economics: daily owner email was not sent")
        return {"status": "send_failed", "day": day}
    return {"status": "sent", "day": day, "reels": summary.reels_finished, "spend_usd": spend}
