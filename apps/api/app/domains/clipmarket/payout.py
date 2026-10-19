"""Clipping marketplace — CPM payout math + viewbot fraud detection.

Brands post campaigns with a CPM (cost per 1,000 verified views) and a budget;
clippers submit clips and earn on API-verified views after a hold. Two pure cores:

* :func:`compute_payout` — integer-microdollar payout from verified views at a
  CPM, clamped to the campaign's remaining budget (never floats; matches the
  wallet money model).
* :func:`fraud_score` — a viewbot-likelihood score from view-quality signals
  (velocity spike, watch-time, engagement ratio, geo concentration, retention
  cliff). Above a threshold the submission is held for manual review rather than
  auto-paid.

Deterministic; the ledger + view-verification live in the domain service.
"""

from __future__ import annotations

from dataclasses import dataclass

_MICROS_PER_USD = 1_000_000


@dataclass(frozen=True)
class Campaign:
    """A brand campaign paying a CPM up to a budget."""

    campaign_id: str
    cpm_micros: int              # micro-USD paid per 1,000 verified views
    budget_micros: int
    spent_micros: int = 0
    min_views: int = 0           # ignore submissions under this many views

    @property
    def remaining_micros(self) -> int:
        return max(0, self.budget_micros - self.spent_micros)


@dataclass(frozen=True)
class PayoutResult:
    """A computed payout for a verified submission."""

    payable_micros: int
    verified_views: int
    capped: bool                 # payout was clamped by remaining budget
    reason: str = ""


def compute_payout(campaign: Campaign, verified_views: int) -> PayoutResult:
    """Payout = verified_views/1000 × cpm, clamped to the campaign budget.

    Integer math (floor division on the ×CPM product) so a fractional micro is
    never minted. Views under ``min_views`` pay zero.
    """
    views = max(0, int(verified_views))
    if views < campaign.min_views:
        return PayoutResult(0, views, False, f"under min_views {campaign.min_views}")
    gross = (views * campaign.cpm_micros) // 1000
    payable = min(gross, campaign.remaining_micros)
    return PayoutResult(
        payable_micros=payable,
        verified_views=views,
        capped=payable < gross,
        reason="budget-capped" if payable < gross else "ok",
    )


@dataclass(frozen=True)
class ViewSignals:
    """Quality signals for a submission's views (each already normalized 0..1
    except where noted)."""

    views: int
    velocity_zscore: float       # spike vs. the clip's baseline (std devs)
    avg_watch_frac: float        # mean fraction watched (bots watch ~0)
    engagement_rate: float       # (likes+comments+shares)/views
    geo_concentration: float     # share of views from a single region/IP block
    retention_cliff: float       # drop at t=0..1s (bots bounce instantly)


@dataclass(frozen=True)
class FraudVerdict:
    """Fraud likelihood + whether to hold for review."""

    score: float                 # 0 (clean) .. 1 (likely viewbot)
    hold_for_review: bool
    flags: tuple[str, ...] = ()


def fraud_score(sig: ViewSignals, *, hold_threshold: float = 0.55) -> FraudVerdict:
    """Score viewbot likelihood from view-quality signals.

    High-confidence bot fingerprints: an implausible velocity spike, near-zero
    watch time, engagement far below the norm, extreme geo/IP concentration, and
    an instant retention cliff. The weighted score gates auto-payout.
    """
    flags: list[str] = []
    contributions = 0.0

    # Velocity spike (z-score > 6 is very suspicious).
    v = _ramp(sig.velocity_zscore, lo=4.0, hi=10.0)
    if v > 0.3:
        flags.append("velocity_spike")
    contributions += 0.25 * v

    # Watch time — bots barely watch.
    low_watch = 1.0 - _clamp(sig.avg_watch_frac / 0.35)  # <35% avg = suspicious
    if low_watch > 0.5:
        flags.append("low_watch_time")
    contributions += 0.25 * low_watch

    # Engagement floor.
    low_eng = 1.0 - _clamp(sig.engagement_rate / 0.02)
    if low_eng > 0.6:
        flags.append("low_engagement")
    contributions += 0.15 * low_eng

    # Geo/IP concentration.
    geo = _clamp(sig.geo_concentration)
    if geo > 0.7:
        flags.append("geo_concentration")
    contributions += 0.20 * _ramp(geo, lo=0.6, hi=0.95)

    # Instant retention cliff.
    cliff = _clamp(sig.retention_cliff)
    if cliff > 0.8:
        flags.append("retention_cliff")
    contributions += 0.15 * _ramp(cliff, lo=0.7, hi=0.95)

    score = round(min(1.0, contributions), 4)
    return FraudVerdict(score=score, hold_for_review=score >= hold_threshold, flags=tuple(flags))


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _ramp(v: float, *, lo: float, hi: float) -> float:
    """Linear 0→1 ramp between lo and hi (clamped)."""
    if hi <= lo:
        return 1.0 if v >= hi else 0.0
    return _clamp((float(v) - lo) / (hi - lo))
