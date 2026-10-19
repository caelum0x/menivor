"""P11 clipmarket — CPM payout math + viewbot fraud detection."""

from __future__ import annotations

from app.domains.clipmarket.payout import (
    Campaign,
    ViewSignals,
    compute_payout,
    fraud_score,
)


# --------------------------------------------------------------------------- #
# CPM payout
# --------------------------------------------------------------------------- #
def test_payout_cpm_integer_math():
    # $2.00 CPM = 2_000_000 micros / 1000 views. 50_000 views -> 100_000_000 micros.
    camp = Campaign("c1", cpm_micros=2_000_000, budget_micros=500_000_000)
    res = compute_payout(camp, 50_000)
    assert res.payable_micros == 100_000_000 and not res.capped


def test_payout_capped_by_budget():
    camp = Campaign("c1", cpm_micros=2_000_000, budget_micros=10_000_000, spent_micros=0)
    res = compute_payout(camp, 50_000)  # would be 100M but budget is 10M
    assert res.payable_micros == 10_000_000 and res.capped


def test_payout_respects_min_views():
    camp = Campaign("c1", cpm_micros=1_000_000, budget_micros=1_000_000_000, min_views=1000)
    assert compute_payout(camp, 500).payable_micros == 0


def test_payout_no_fractional_micros():
    # 1 view at $1 CPM = 1_000_000/1000 = 1000 micros exactly; 1 view stays integer.
    camp = Campaign("c1", cpm_micros=1_000_000, budget_micros=1_000_000_000)
    assert compute_payout(camp, 1).payable_micros == 1000
    # A non-divisible product floors (never mints a fractional micro).
    camp2 = Campaign("c2", cpm_micros=999_999, budget_micros=1_000_000_000)
    assert compute_payout(camp2, 1).payable_micros == 999  # 999_999//1000


# --------------------------------------------------------------------------- #
# Fraud detection
# --------------------------------------------------------------------------- #
def test_clean_views_not_held():
    clean = ViewSignals(views=10000, velocity_zscore=1.0, avg_watch_frac=0.55,
                        engagement_rate=0.05, geo_concentration=0.2, retention_cliff=0.2)
    v = fraud_score(clean)
    assert v.score < 0.4 and not v.hold_for_review


def test_viewbot_pattern_held_with_flags():
    bot = ViewSignals(views=100000, velocity_zscore=12.0, avg_watch_frac=0.02,
                      engagement_rate=0.0, geo_concentration=0.95, retention_cliff=0.95)
    v = fraud_score(bot)
    assert v.score >= 0.55 and v.hold_for_review
    assert {"velocity_spike", "low_watch_time", "geo_concentration", "retention_cliff"} <= set(v.flags)


def test_partial_signals_scale_score():
    mild = ViewSignals(views=5000, velocity_zscore=5.0, avg_watch_frac=0.3,
                       engagement_rate=0.015, geo_concentration=0.5, retention_cliff=0.5)
    v = fraud_score(mild)
    assert 0.0 <= v.score <= 1.0
