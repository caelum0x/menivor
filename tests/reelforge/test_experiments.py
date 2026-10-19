"""P7 A/B experiments — retention-weighted 1-body/N-hooks winner selection."""

from __future__ import annotations

from app.domains.publishing.experiments import (
    VariantMetrics,
    score_variant,
    select_winner,
)


def _v(vid, hook, views=1000, comp=0.5, watch=0.5, rewatch=0.1, eng=0.05):
    return VariantMetrics(vid, hook, views=views, completion_rate=comp,
                          avg_watch_frac=watch, rewatch_rate=rewatch, engagement_rate=eng)


def test_retention_dominates_score():
    high_retention = _v("a", "hookA", comp=0.9, watch=0.8)
    high_views_low_retention = _v("b", "hookB", views=100000, comp=0.2, watch=0.2)
    assert score_variant(high_retention) > score_variant(high_views_low_retention)


def test_clear_winner_selected():
    variants = [
        _v("a", "hookA", comp=0.8, watch=0.7, rewatch=0.2),
        _v("b", "hookB", comp=0.4, watch=0.3, rewatch=0.05),
    ]
    res = select_winner(variants)
    assert res.conclusive and res.winner_id == "a" and res.winner_hook_ref == "hookA"


def test_inconclusive_when_underpowered():
    variants = [_v("a", "hookA", views=50), _v("b", "hookB", views=500)]
    res = select_winner(variants)
    assert not res.conclusive and "insufficient sample" in res.reason


def test_inconclusive_on_near_tie():
    variants = [
        _v("a", "hookA", comp=0.61, watch=0.6),
        _v("b", "hookB", comp=0.60, watch=0.6),
    ]
    res = select_winner(variants)
    assert not res.conclusive and "inconclusive" in res.reason


def test_single_variant_inconclusive():
    res = select_winner([_v("a", "hookA")])
    assert not res.conclusive
