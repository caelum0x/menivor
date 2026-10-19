"""Unit tests for the pure publishing scheduling policy (``decide``).

Focus: the min-gap self-cannibalization guard must clear EVERY recent post, not
just the first conflicting one, and a min-gap deferral must still honor the
daily cap on its landing day.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domains.publishing import scheduling_policy

UTC = timezone.utc
NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC)


def _min_gap_s(platform: str) -> float:
    return scheduling_policy.platform_config(platform)["min_gap_h"] * 3600.0


def test_min_gap_deferral_clears_every_recent_post():
    # tiktok min_gap 3h; two recent posts (12:01 and 16:00). A candidate at 12:01
    # must land >= 3h from BOTH — snapping past only the first (-> 16:00) would
    # collide with the second (self-cannibalization).
    posts = [
        datetime(2026, 8, 19, 12, 1, tzinfo=UTC),
        datetime(2026, 8, 19, 16, 0, tzinfo=UTC),
    ]
    decision = scheduling_policy.decide(
        "tiktok",
        datetime(2026, 8, 19, 12, 1, tzinfo=UTC),
        now=NOW,
        recent_posts=posts,
    )
    assert decision.allow is False
    run_at = decision.run_at.astimezone(UTC)
    gap = _min_gap_s("tiktok")
    # Clears every existing post by the full min-gap.
    assert all(abs((run_at - p).total_seconds()) >= gap - 1 for p in posts)


def test_successive_deferrals_do_not_collapse_onto_same_slot():
    # Simulate scheduling three clips in one pass (accumulating history): each
    # decided slot must stay >= min-gap from all previously chosen slots.
    history: list[datetime] = []
    chosen: list[datetime] = []
    for _ in range(3):
        decision = scheduling_policy.decide(
            "tiktok",
            NOW + timedelta(minutes=1),
            now=NOW,
            recent_posts=list(history),
        )
        run_at = decision.run_at.astimezone(UTC)
        chosen.append(run_at)
        history.append(run_at)
    gap = _min_gap_s("tiktok")
    for i in range(len(chosen)):
        for j in range(i + 1, len(chosen)):
            assert abs((chosen[i] - chosen[j]).total_seconds()) >= gap - 1


def test_min_gap_deferral_respects_daily_cap_on_landing_day():
    # youtube cap 2, min_gap 6h. Two posts already today AND a near candidate:
    # the min-gap deferral must NOT land a 3rd post on a day already at cap.
    posts = [
        datetime(2026, 8, 19, 15, 0, tzinfo=UTC),
        datetime(2026, 8, 19, 20, 0, tzinfo=UTC),
    ]
    decision = scheduling_policy.decide(
        "youtube",
        datetime(2026, 8, 19, 20, 1, tzinfo=UTC),
        now=NOW,
        recent_posts=posts,
    )
    assert decision.allow is False
    assert decision.run_at.astimezone(UTC).date() > NOW.date()
