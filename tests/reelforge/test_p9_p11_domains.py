"""P9-P11 domain cores — trends scoring, gateway provisioning/markup, clipfarm fan-out."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domains.gateway import provisioning as gw
from app.domains.series.fanout import FanoutMatrix, pace_by_account, plan_fanout, spec_hash
from app.domains.trends.scoring import TrendSignal, rank_trends, score_trend


# --------------------------------------------------------------------------- #
# Trends scoring
# --------------------------------------------------------------------------- #
def test_rising_fresh_trend_is_high_opportunity():
    rising = TrendSignal("t1", "sound", counts=(100, 300, 900, 2000))
    s = score_trend(rising)
    assert s.phase in ("rising", "emerging") and s.opportunity > 0.15 and s.recommend


def test_peaked_trend_low_opportunity():
    peaked = TrendSignal("t2", "sound", counts=(90000, 95000, 99000, 99500), )
    s = score_trend(peaked, saturation_ceiling=100000)
    assert s.saturation >= 0.6 and s.opportunity < 0.15 and not s.recommend


def test_short_series_is_inconclusive():
    s = score_trend(TrendSignal("t3", "hashtag", counts=(10, 20)))
    assert s.opportunity == 0.0 and not s.recommend


def test_rank_puts_recommended_first():
    signals = [
        TrendSignal("hot", "sound", counts=(100, 400, 1200, 3000)),
        TrendSignal("cold", "sound", counts=(99000, 99100, 99050, 99000)),
    ]
    ranked = rank_trends(signals, limit=5)
    assert ranked[0].trend_id == "hot"


# --------------------------------------------------------------------------- #
# Gateway provisioning + markup
# --------------------------------------------------------------------------- #
def _key(cap):
    return gw.ProvisioningKey(key_id="k1", owner_id="u1", daily_cap_micros=cap)


def test_spend_within_cap_allowed():
    d = gw.check_spend(_key(1_000_000), 200_000, spent_today_micros=300_000)
    assert d.allow and d.remaining_micros == 500_000


def test_spend_over_cap_denied():
    d = gw.check_spend(_key(1_000_000), 800_000, spent_today_micros=300_000)
    assert not d.allow and "daily cap exceeded" in d.reason


def test_unlimited_key_and_disabled_key():
    assert gw.check_spend(_key(0), 5_000_000, spent_today_micros=0).allow
    disabled = gw.ProvisioningKey("k", "u", 1_000_000, disabled=True)
    assert not gw.check_spend(disabled, 1, spent_today_micros=0).allow


def test_window_start_is_utc_midnight():
    ws = gw.window_start(datetime(2026, 8, 18, 15, 30, tzinfo=timezone.utc))
    assert ws.hour == 0 and ws.minute == 0 and ws.date().day == 18


def test_markup_integer_math():
    policy = gw.MarkupPolicy(markup_bps=2000, min_fee_micros=1000)  # +20% + 1000
    # 100_000 base -> +20_000 markup + 1_000 fee = 121_000
    assert gw.apply_markup(100_000, policy) == 121_000
    assert gw.margin_micros(100_000, policy) == 21_000


def test_markup_zero_policy_is_passthrough():
    assert gw.apply_markup(50_000, gw.MarkupPolicy()) == 50_000


def test_negative_markup_rejected():
    with pytest.raises(gw.GatewayError):
        gw.MarkupPolicy(markup_bps=-1)


# --------------------------------------------------------------------------- #
# Clipfarm fan-out
# --------------------------------------------------------------------------- #
def test_fanout_full_cartesian_product():
    m = FanoutMatrix(
        bodies=("b1", "b2"), hooks=("h1", "h2"), templates=("t1",),
        aspects=("9:16",), accounts=("acc1",),
    )
    plan = plan_fanout(m)
    assert plan.total_combinations == 4 and len(plan.specs) == 4
    assert plan.skipped_duplicates == 0


def test_fanout_dedupes_against_seen():
    m = FanoutMatrix(bodies=("b1",), hooks=("h1", "h2"))
    first = plan_fanout(m)
    seen = {s.spec_hash for s in first.specs}
    # Re-running with the same seen set skips everything.
    again = plan_fanout(m, seen_hashes=seen)
    assert again.skipped_duplicates == 2 and again.specs == []


def test_spec_hash_stable_and_account_scoped():
    h1 = spec_hash("b", "h", "t", "9:16", "acc1")
    h2 = spec_hash("b", "h", "t", "9:16", "acc1")
    h3 = spec_hash("b", "h", "t", "9:16", "acc2")
    assert h1 == h2 and h1 != h3  # same creative, different account = distinct


def test_pace_caps_per_account():
    m = FanoutMatrix(bodies=("b1", "b2", "b3"), accounts=("acc1",))
    specs = plan_fanout(m).specs
    paced = pace_by_account(specs, max_per_account=2)
    assert len(paced) == 2
    assert pace_by_account(specs, max_per_account=0) == specs  # no cap
