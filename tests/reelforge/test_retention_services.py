"""P7 retention services — hook predictor, seamless loop, beat-cut, scheduler."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domains.publishing import scheduling_policy as sched
from app.services.loops import (
    HookSignals,
    find_loop_point,
    predict_hook,
    preview_beat_fits,
    snap_cuts_to_beats,
)


# --------------------------------------------------------------------------- #
# Hook predictor — 70% gate
# --------------------------------------------------------------------------- #
def test_strong_hook_passes_gate():
    strong = HookSignals(motion=1, text=1, audio_onset=1, early_cut=1, speech=1, face_or_subject=1, hook_end_s=2.0)
    res = predict_hook(strong)
    assert res.score >= 0.9 and res.passes_gate and res.grade == "viral"


def test_weak_hook_fails_gate_with_reasons():
    weak = HookSignals(motion=0.1, text=0.0, audio_onset=0.2, early_cut=0.0, speech=0.2, face_or_subject=0.1)
    res = predict_hook(weak)
    assert not res.passes_gate and res.grade in ("weak", "poor")
    assert res.reasons  # actionable suggestions surfaced


def test_hook_overrun_penalized():
    base = dict(motion=0.8, text=0.8, audio_onset=0.8, early_cut=0.8, speech=0.8, face_or_subject=0.8)
    tight = predict_hook(HookSignals(**base, hook_end_s=2.5))
    late = predict_hook(HookSignals(**base, hook_end_s=6.0))
    assert late.score < tight.score
    assert any("tighten" in r for r in late.reasons)


def test_subscores_sum_to_score_before_overrun():
    s = HookSignals(motion=0.5, text=0.5, audio_onset=0.5, early_cut=0.5, speech=0.5, face_or_subject=0.5, hook_end_s=2.0)
    res = predict_hook(s)
    assert res.score == pytest.approx(sum(res.subscores.values()), abs=1e-6)


# --------------------------------------------------------------------------- #
# Seamless loop finder
# --------------------------------------------------------------------------- #
def test_find_loop_prefers_low_seam_near_target():
    fps = 30.0
    # 6s of frames; a near-perfect seam at ~5s (frame 150), noisy elsewhere.
    disc = [0.5] * 181
    disc[150] = 0.01
    res = find_loop_point(disc, fps=fps, target_s=5.0, min_s=1.0, max_s=6.0)
    assert res.end_frame == 150
    assert res.end_s == pytest.approx(5.0, abs=0.05)
    assert res.accepted and res.discontinuity <= 0.08


def test_loop_rejected_when_seam_too_large():
    disc = [0.4] * 100
    res = find_loop_point(disc, fps=30.0, target_s=3.0, max_discontinuity=0.08)
    assert not res.accepted and "seamless" in res.reason


def test_loop_finder_validates_inputs():
    with pytest.raises(ValueError):
        find_loop_point([], fps=30.0)
    with pytest.raises(ValueError):
        find_loop_point([0.1, 0.2], fps=0)


# --------------------------------------------------------------------------- #
# Beat-cut snapping
# --------------------------------------------------------------------------- #
def test_snap_cuts_lands_on_beat_minus_nudge():
    beats = [0.0, 0.5, 1.0, 1.5, 2.0]
    cuts = [0.52, 1.06]  # slightly after beats 0.5 and 1.0
    snapped = snap_cuts_to_beats(cuts, beats, fps=30.0, nudge_frames=2)
    assert snapped[0].beat_s == 0.5
    # nudged earlier by 2 frames (~0.0667s) from the beat.
    assert snapped[0].nudged_s == pytest.approx(0.5 - 2 / 30.0, abs=1e-3)
    assert snapped[1].beat_s == 1.0


def test_snap_is_monotonic_and_skips_far_beats():
    beats = [0.0, 5.0]
    cuts = [1.0]  # no beat within max_snap_s -> stays put
    snapped = snap_cuts_to_beats(cuts, beats, fps=30.0, max_snap_s=0.4)
    assert snapped[0].beat_s == 1.0 and snapped[0].nudge_frames == 0


def test_preview_beat_fits_ranks_options():
    beats = [0.0, 1.0, 2.0]
    cuts = [1.02, 2.01]
    fits = preview_beat_fits(cuts, beats, fps=30.0, options=(2, 3, 4))
    assert set(fits) == {2, 3, 4}
    assert all(v >= 0 for v in fits.values())


# --------------------------------------------------------------------------- #
# Scheduling policy
# --------------------------------------------------------------------------- #
def _utc(y=2026, mo=8, d=18, h=12):
    return datetime(y, mo, d, h, 0, 0, tzinfo=timezone.utc)


def test_schedule_allows_clean_slot():
    d = sched.decide("tiktok", _utc(h=13), now=_utc(h=12), recent_posts=[])
    assert d.allow and d.run_at == _utc(h=13)


def test_schedule_daily_cap_pushes_to_next_day():
    posts = [_utc(h=8), _utc(h=11), _utc(h=14), _utc(h=17)]  # 4 == tiktok cap
    d = sched.decide("tiktok", _utc(h=20), now=_utc(h=7), recent_posts=posts)
    assert not d.allow and d.run_at.date() > _utc().date() and "daily cap" in d.reason


def test_schedule_min_gap_guard():
    posts = [_utc(h=12)]
    d = sched.decide("tiktok", _utc(h=13), now=_utc(h=7), recent_posts=posts)  # 1h < 3h gap
    assert not d.allow and "min-gap" in d.reason
    assert d.run_at >= _utc(h=15)  # pushed to >= last+gap, on a best hour


def test_schedule_failure_backoff():
    d = sched.decide("tiktok", _utc(h=12, d=18), now=_utc(h=12, d=18), recent_posts=[], consecutive_failures=3)
    # 3 failures -> 0.5 * 2^2 = 2h backoff.
    assert not d.allow and d.run_at >= _utc(h=14, d=18) and "backoff" in d.reason


def test_backoff_curve_and_cap():
    assert sched.backoff_delay_h(0) == 0.0
    assert sched.backoff_delay_h(1) == 0.5
    assert sched.backoff_delay_h(2) == 1.0
    assert sched.backoff_delay_h(20) == 12.0  # capped
