"""Pure publishing scheduling policy — backoff, daily-cap, anti-cannibalization.

The self-hosted scheduler must decide WHEN a queued reel may actually post. This
module is the pure decision core (the DB scheduler calls it): given a platform,
the creator's recent post history, and a proposed time, it answers "post now?" and
"if not, when?" enforcing:

* **daily cap** — at most N posts per platform per UTC day,
* **min-gap** — no two posts within a window (self-cannibalization guard),
* **best-time windows** — prefer platform-specific high-engagement hours,
* **failure backoff** — exponential backoff after consecutive publish failures.

No DB / clock here — ``now`` and the history are passed in, so every rule is
deterministically testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Per-platform defaults (UTC hour windows are a sane starting heuristic; the
# analytics loop later personalizes these from real retention data).
_DEFAULTS = {
    "tiktok": {"daily_cap": 4, "min_gap_h": 3.0, "best_hours": (13, 16, 19, 22)},
    "instagram": {"daily_cap": 3, "min_gap_h": 4.0, "best_hours": (11, 14, 19, 21)},
    "youtube": {"daily_cap": 2, "min_gap_h": 6.0, "best_hours": (15, 18, 20)},
    "x": {"daily_cap": 8, "min_gap_h": 1.0, "best_hours": (9, 12, 17, 21)},
}
_FALLBACK = {"daily_cap": 3, "min_gap_h": 4.0, "best_hours": (12, 18, 21)}

_MAX_BACKOFF_H = 12.0


@dataclass(frozen=True)
class ScheduleDecision:
    """The scheduler's verdict for a candidate post."""

    allow: bool
    run_at: datetime          # when to post (== candidate if allowed now)
    reason: str = ""


def platform_config(platform: str) -> dict:
    return _DEFAULTS.get(str(platform or "").strip().lower(), _FALLBACK)


def backoff_delay_h(consecutive_failures: int) -> float:
    """Exponential backoff (hours) after N consecutive publish failures, capped."""
    if consecutive_failures <= 0:
        return 0.0
    return min(_MAX_BACKOFF_H, 0.5 * (2 ** (consecutive_failures - 1)))


def _same_utc_day(a: datetime, b: datetime) -> bool:
    return a.astimezone(timezone.utc).date() == b.astimezone(timezone.utc).date()


def _next_best_time(after: datetime, best_hours: tuple[int, ...]) -> datetime:
    """The next UTC datetime at or after ``after`` landing on a best hour."""
    after = after.astimezone(timezone.utc)
    for add_day in range(0, 3):
        day = (after + timedelta(days=add_day)).replace(minute=0, second=0, microsecond=0)
        for hour in sorted(best_hours):
            candidate = day.replace(hour=hour)
            if candidate >= after:
                return candidate
    return after


def decide(
    platform: str,
    candidate_at: datetime,
    *,
    now: datetime,
    recent_posts: list[datetime],
    consecutive_failures: int = 0,
    config: dict | None = None,
) -> ScheduleDecision:
    """Decide whether ``candidate_at`` may post, or compute the next legal slot.

    ``recent_posts`` are prior successful post times for this creator+platform.
    Order of checks: backoff → not-in-the-past → daily-cap → min-gap → best-time.
    """
    cfg = config or platform_config(platform)
    now = now.astimezone(timezone.utc)
    candidate = candidate_at.astimezone(timezone.utc)
    posts = sorted(p.astimezone(timezone.utc) for p in recent_posts)

    # 1) Failure backoff pushes the earliest allowable time forward.
    earliest = now + timedelta(hours=backoff_delay_h(consecutive_failures))
    if candidate < earliest:
        return ScheduleDecision(
            allow=False, run_at=earliest,
            reason=f"backoff after {consecutive_failures} failure(s)",
        )

    # 2) Daily cap (per UTC day).
    todays = [p for p in posts if _same_utc_day(p, candidate)]
    if len(todays) >= cfg["daily_cap"]:
        nxt = _next_best_time(candidate + timedelta(days=1), tuple(cfg["best_hours"]))
        return ScheduleDecision(allow=False, run_at=nxt, reason=f"daily cap {cfg['daily_cap']} reached")

    # 3) Min-gap (self-cannibalization guard).
    gap = timedelta(hours=cfg["min_gap_h"])
    gap_s = gap.total_seconds()
    if any(abs((candidate - p).total_seconds()) < gap_s for p in posts):
        best_hours = tuple(cfg["best_hours"])
        # Advance until the chosen slot clears EVERY recent post by the full gap —
        # snapping past only the FIRST conflict lets successive deferred clips
        # collapse onto the same slot (self-cannibalization). Bounded: each step
        # moves strictly forward past a conflicting post, so it terminates.
        nxt = candidate
        for _ in range(len(posts) + 1):
            conflict = next(
                (p for p in posts if abs((nxt - p).total_seconds()) < gap_s), None
            )
            if conflict is None:
                break
            nxt = _next_best_time(conflict + gap, best_hours)
        # A min-gap deferral must still honor the daily cap on its landing day;
        # otherwise a deferred clip could silently exceed that day's cap.
        for _ in range(len(posts) + 1):
            if len([p for p in posts if _same_utc_day(p, nxt)]) < cfg["daily_cap"]:
                break
            nxt = _next_best_time(nxt + timedelta(days=1), best_hours)
        return ScheduleDecision(allow=False, run_at=nxt, reason=f"min-gap {cfg['min_gap_h']}h to a recent post")

    return ScheduleDecision(allow=True, run_at=candidate, reason="ok")
