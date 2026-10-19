"""Pure funnel report: steps, conversion, biggest drop-off, email copy.

Every number comes from ``funnel_events`` counts; nothing here estimates,
rounds up or fills gaps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape

STEPS: tuple[tuple[str, str], ...] = (
    ("signup", "Signed up"),
    ("card_check", "Card check passed"),
    ("first_link", "First link pasted"),
    ("first_reel", "First reel rendered"),
    ("paid", "Pack or plan bought"),
)
STEP_KEYS: frozenset[str] = frozenset(key for key, _ in STEPS)


@dataclass(frozen=True)
class FunnelRow:
    key: str
    label: str
    total: int
    week: int
    from_previous: float | None


@dataclass(frozen=True)
class DropOff:
    from_label: str
    to_label: str
    rate: float
    lost: int


@dataclass(frozen=True)
class FunnelReport:
    rows: tuple[FunnelRow, ...]
    drop_off: DropOff | None


def _count(value: object) -> int:
    try:
        n = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def build_report(totals: dict[str, int], week: dict[str, int]) -> FunnelReport:
    rows: list[FunnelRow] = []
    for i, (key, label) in enumerate(STEPS):
        total = _count(totals.get(key))
        prev = _count(totals.get(STEPS[i - 1][0])) if i > 0 else 0
        rows.append(
            FunnelRow(
                key=key,
                label=label,
                total=total,
                week=_count(week.get(key)),
                from_previous=None if i == 0 or prev == 0 else total / prev,
            )
        )
    return FunnelReport(rows=tuple(rows), drop_off=biggest_drop_off(rows))


def biggest_drop_off(rows: list[FunnelRow] | tuple[FunnelRow, ...]) -> DropOff | None:
    worst: DropOff | None = None
    for i in range(1, len(rows)):
        rate = rows[i].from_previous
        if rate is None or rate >= 1:
            continue
        if worst is None or rate < worst.rate:
            worst = DropOff(rows[i - 1].label, rows[i].label, rate, rows[i - 1].total - rows[i].total)
    return worst


def format_percent(rate: float | None) -> str:
    if rate is None:
        return "-"
    pct = rate * 100
    if pct >= 10 or pct == 0:
        return f"{round(pct)}%"
    return f"{pct:.1f}%"


def week_start_utc(now: datetime) -> datetime:
    now = now.astimezone(timezone.utc)
    monday = now - timedelta(days=now.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)


def is_report_due(now: datetime) -> bool:
    now = now.astimezone(timezone.utc)
    return now.weekday() == 0 and now.hour >= 7


def subject(report: FunnelReport) -> str:
    signups = report.rows[0].week if report.rows else 0
    drop = (
        f", biggest drop: {report.drop_off.to_label} ({format_percent(report.drop_off.rate)})"
        if report.drop_off
        else ""
    )
    return f"Menivor funnel: {signups} new signup{'' if signups == 1 else 's'} this week{drop}"


def _drop_line(report: FunnelReport) -> str:
    d = report.drop_off
    if d is None:
        return "Biggest drop-off: none yet (not enough people in the funnel)."
    return (
        f"Biggest drop-off: {d.from_label} -> {d.to_label}: "
        f"{format_percent(d.rate)} continue, {d.lost} stopped."
    )


def text_body(report: FunnelReport, week_start: datetime) -> str:
    lines = [
        f"Menivor activation funnel, week of {week_start.date().isoformat()}",
        "",
        "Step | All time | Last 7 days | From previous step",
        *(f"{r.label} | {r.total} | {r.week} | {format_percent(r.from_previous)}" for r in report.rows),
        "",
        _drop_line(report),
    ]
    return "\n".join(lines)


def html_body(report: FunnelReport, week_start: datetime) -> str:
    cell = "padding:8px 12px;border-bottom:1px solid #e8e6df;font:14px -apple-system,Segoe UI,sans-serif;"
    rows = "".join(
        f"<tr><td style='{cell}color:#71717a'>{escape(r.label)}</td>"
        f"<td style='{cell}text-align:right'>{r.total}</td>"
        f"<td style='{cell}text-align:right'>{r.week}</td>"
        f"<td style='{cell}text-align:right'>{format_percent(r.from_previous)}</td></tr>"
        for r in report.rows
    )
    head = "".join(
        f"<th style='{cell}text-align:{align};color:#71717a;font-weight:600'>{label}</th>"
        for label, align in (("Step", "left"), ("All time", "right"), ("Last 7 days", "right"), ("From previous", "right"))
    )
    return (
        "<div style='max-width:600px;margin:0 auto;padding:24px;background:#fafaf7'>"
        "<div style='background:#fff;border:1px solid #e8e6df;border-radius:16px;padding:24px'>"
        f"<h1 style='margin:0 0 12px;font:600 20px -apple-system,Segoe UI,sans-serif;color:#111114'>"
        f"Menivor funnel, week of {week_start.date().isoformat()}</h1>"
        f"<p style='margin:0 0 16px;font:15px/1.6 -apple-system,Segoe UI,sans-serif;color:#3f3f46'>{escape(_drop_line(report))}</p>"
        f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0' style='border-collapse:collapse'>"
        f"<tr>{head}</tr>{rows}</table>"
        "<p style='margin:16px 0 0;font:12px -apple-system,Segoe UI,sans-serif;color:#71717a'>"
        "Weekly owner report. Counts come from Menivor's own database.</p>"
        "</div></div>"
    )
