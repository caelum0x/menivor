"""P11 affiliate commission + P8 audio ducking envelope."""

from __future__ import annotations

import pytest

from app.domains.affiliate.commission import (
    AffiliateError,
    Referral,
    compute_commission,
    rate_bps,
)
from app.services.audio.ducking import build_duck_envelope


# --------------------------------------------------------------------------- #
# Affiliate commission
# --------------------------------------------------------------------------- #
def test_standard_tier_20pct():
    r = Referral("ref", "ree")
    c = compute_commission(r, 100_000)
    assert c.rate_bps == 2000 and c.payable_micros == 20_000 and not c.capped


def test_tiers():
    assert rate_bps("pro") == 3000 and rate_bps("partner") == 4000
    assert rate_bps("unknown") == 2000


def test_lifetime_cap_clamps():
    r = Referral("ref", "ree", tier="pro", lifetime_cap_micros=25_000, earned_micros=20_000)
    c = compute_commission(r, 100_000)  # gross 30_000 but only 5_000 headroom
    assert c.payable_micros == 5_000 and c.capped


def test_self_referral_rejected():
    with pytest.raises(AffiliateError):
        compute_commission(Referral("x", "x"), 100_000)


def test_integer_floor_no_fractional_micro():
    # 30% of 999 = 299.7 -> floors to 299.
    r = Referral("a", "b", tier="pro")
    assert compute_commission(r, 999).payable_micros == 299


# --------------------------------------------------------------------------- #
# Audio ducking envelope
# --------------------------------------------------------------------------- #
def test_no_speech_is_full_level():
    env = build_duck_envelope([], 10.0)
    assert all(p.gain_db == 0.0 for p in env)


def test_ducks_under_speech():
    env = build_duck_envelope([(3.0, 5.0)], 10.0)
    # There is a ducked (-14) region around the speech span.
    ducked = [p for p in env if p.gain_db < 0]
    assert ducked and min(p.gain_db for p in ducked) == pytest.approx(-14.0)
    # Envelope starts and ends at full level.
    assert env[0].gain_db == 0.0 and env[-1].gain_db == 0.0
    # Monotonic time.
    assert [p.t for p in env] == sorted(p.t for p in env)


def test_rapid_spans_merged():
    # Two spans 0.1s apart merge into one duck (no pumping).
    env = build_duck_envelope([(2.0, 2.5), (2.6, 3.0)], 6.0)
    # Count distinct "ramp back to full after duck" transitions == 1 merged region.
    full_after_duck = 0
    prev_ducked = False
    for p in env:
        if prev_ducked and p.gain_db == 0.0:
            full_after_duck += 1
        prev_ducked = p.gain_db < 0
    assert full_after_duck == 1
