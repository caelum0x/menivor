"""Pure pacing math: per-account daily caps, minimum gaps, posting hours, slot planning.

No I/O. The queue feeds it the account's limits and the times of posts that
already count against them; it answers "may this post go now?" and "when is the
next allowed slot?". All datetimes are timezone-aware UTC.

Rule: within any rolling 24 hours an account gets at most ``daily_cap`` posts,
and two posts on the same account are at least ``gap`` apart. Posts may be
restricted to local ``hours`` (0-23) in the account's time zone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DAY = timedelta(hours=24)
# Planning never looks further than this ahead for one slot (guards bad input).
_MAX_SEARCH = timedelta(days=60)


@dataclass(frozen=True)
class Limits:
    daily_cap: int
    gap: timedelta
    hours: tuple[int, ...] = ()
    tz: str = "UTC"


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    next_at: datetime
    reason: str = ""


@dataclass(frozen=True)
class AccountPlan:
    """An account the planner may assign posts to, with its existing post times."""

    account_id: str
    limits: Limits
    taken: tuple[datetime, ...] = field(default_factory=tuple)


def effective_limits(*, daily_cap: int, gap_minutes: int, platform_cap: int, default_cap: int,
                     default_gap: int, gap_floor: int, hours: list | tuple = (), tz: str = "UTC") -> Limits:
    """Clamp owner settings into the platform-safe range (0 = use the default)."""
    cap = daily_cap if daily_cap and daily_cap > 0 else default_cap
    cap = max(1, min(int(cap), int(platform_cap)))
    gap = gap_minutes if gap_minutes and gap_minutes > 0 else default_gap
    gap = max(int(gap_floor), int(gap))
    clean_hours = tuple(sorted({int(h) for h in hours if isinstance(h, int) and 0 <= h <= 23}))
    return Limits(daily_cap=cap, gap=timedelta(minutes=gap), hours=clean_hours, tz=_tz_name(tz))


def _tz_name(tz: str) -> str:
    try:
        ZoneInfo(str(tz or "UTC"))
        return str(tz or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return "UTC"


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _in_hours(at: datetime, limits: Limits) -> bool:
    if not limits.hours:
        return True
    return at.astimezone(ZoneInfo(limits.tz)).hour in limits.hours


def _next_hour_start(at: datetime, limits: Limits) -> datetime:
    """The first instant at/after ``at`` that falls in an allowed local hour."""
    if _in_hours(at, limits):
        return at
    local = at.astimezone(ZoneInfo(limits.tz))
    probe = local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    for _ in range(24 * 3):
        if probe.hour in limits.hours:
            return probe.astimezone(timezone.utc)
        probe += timedelta(hours=1)
    return at  # unreachable for a non-empty valid hours set


def _gap_ok(at: datetime, times: list[datetime], limits: Limits) -> bool:
    return all(abs((t - at).total_seconds()) >= limits.gap.total_seconds() for t in times)


def _cap_ok(at: datetime, times: list[datetime], limits: Limits) -> bool:
    """Every rolling 24 h window that contains ``at`` keeps at most ``daily_cap`` posts.

    The busiest window containing ``at`` starts at one of the posts, so checking
    the windows anchored at each post in ``(at - 24h, at]`` is exhaustive.
    """
    merged = sorted([*times, at])
    for anchor in merged:
        if at - DAY < anchor <= at:
            count = sum(1 for t in merged if anchor <= t < anchor + DAY)
            if count > limits.daily_cap:
                return False
    return True


def _reasons(at: datetime, times: list[datetime], limits: Limits) -> list[str]:
    reasons = []
    if not _gap_ok(at, times, limits):
        reasons.append("spacing")
    if not _cap_ok(at, times, limits):
        reasons.append("daily_cap")
    if not _in_hours(at, limits):
        reasons.append("posting_hours")
    return reasons


def check(at: datetime, taken: list[datetime] | tuple[datetime, ...], limits: Limits) -> Verdict:
    """May a post go out at ``at`` given the account's counted post times ``taken``?

    When not, ``next_at`` is the earliest time it could go and ``reason`` says why.
    """
    at = _aware(at)
    times = sorted(_aware(t) for t in taken)
    reasons = _reasons(at, times, limits)
    if not reasons:
        return Verdict(True, at)
    return Verdict(False, next_slot(at, times, limits), ",".join(reasons))


def next_slot(start: datetime, taken: list[datetime] | tuple[datetime, ...], limits: Limits) -> datetime:
    """Earliest time at/after ``start`` that satisfies every limit.

    A blocked stretch can only end where a gap ends (``t + gap``), where a post
    ages out of the 24 h window (``t + 24h``) or where an allowed hour begins, so
    those are the only candidates worth testing, in order.
    """
    start = _aware(start)
    times = sorted(_aware(t) for t in taken)
    events = {start}
    for t in times:
        for edge in (t + limits.gap, t + DAY):
            if edge > start:
                events.add(edge)
    for candidate in sorted(events):
        at = _next_hour_start(candidate, limits)
        if not _reasons(at, times, limits):
            return at
        if at - start > _MAX_SEARCH:
            break
    # Past every existing post plus a full day nothing can conflict.
    tail = (times[-1] if times else start) + max(DAY, limits.gap)
    return _next_hour_start(max(tail, start), limits)


def plan(job_ids: list[str], accounts: list[AccountPlan], start: datetime, *, mode: str = "spread"
         ) -> list[tuple[str, str, datetime]]:
    """Assign videos to accounts and times.

    ``spread``: each video goes to exactly one account; each video is given to the
    account whose next free slot is earliest (ties broken by the order the
    accounts were chosen), which balances load and respects every account's cap.
    ``every``: each video goes to every account, each at its own next free slot.

    Returns ``[(job_id, account_id, at)]`` in planned order.
    """
    if not job_ids or not accounts:
        return []
    start = _aware(start)
    taken: dict[str, list[datetime]] = {a.account_id: sorted(_aware(t) for t in a.taken) for a in accounts}
    out: list[tuple[str, str, datetime]] = []
    for job_id in job_ids:
        if mode == "every":
            targets = accounts
        else:
            slots = [(next_slot(start, taken[a.account_id], a.limits), idx, a) for idx, a in enumerate(accounts)]
            slots.sort(key=lambda item: (item[0], item[1]))
            targets = [slots[0][2]]
        for acct in targets:
            at = next_slot(start, taken[acct.account_id], acct.limits)
            taken[acct.account_id] = sorted([*taken[acct.account_id], at])
            out.append((job_id, acct.account_id, at))
    return out


def backoff(attempts: int) -> timedelta:
    """Retry delay after ``attempts`` failed tries: 5, 15, 45, 135 minutes (capped at 6 h)."""
    minutes = 5 * (3 ** max(0, attempts - 1))
    return timedelta(minutes=min(minutes, 360))
