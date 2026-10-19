"""MG3: per-SKU credit cost for reels (``app.domains.reels.pricing``).

* Premium voice, premium music and AI-video (presenter) cost at least 3x the
  provider price.
* The price is available before render (``POST /jobs/quote``) and matches
  what create debits.
* An unpriced SKU answers 402 ``sku_unpriced`` and never charges a credit.
"""

from __future__ import annotations

import pytest

from app.core.launch import formats
from app.domains.reels import premium, pricing
from app.models.db.repositories import JobRepository
from app.services.billing import premium_credits as pc
from app.telemetry import cost
from tests.reelforge.test_premium_credits import (  # noqa: F401 - fixtures
    _HEADERS,
    _balances,
    _params,
    _pro,
    _user,
    api,
    db,
)


# --------------------------------------------------------------------------- #
# Table
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("seconds", "credits"),
    [(1, 1), (30, 1), (60, 1), (61, 2), (120, 2), (121, 3), (600, 10)],
)
def test_standard_credits_by_length(seconds, credits):
    assert pricing.standard_credits(seconds) == credits


def test_standard_line_names_short_and_long_form():
    assert pricing.standard_line(_params(target_duration_s=45)).sku == pricing.SKU_REEL
    assert pricing.standard_line(_params(target_duration_s=90)).sku == pricing.SKU_LONG_FORM


def test_premium_voice_credit_value_comes_from_the_pack():
    pack = pc.get_pack("premium_voice_25")
    assert pricing.premium_voice_credit_usd() == pytest.approx(pack.price_usd / pack.credits)


@pytest.mark.parametrize("seconds", [5, 15, 30, 45, 60, 90, 180])
def test_premium_voice_is_at_least_three_times_provider_cost(seconds):
    line = pricing.premium_voice_line(_params(target_duration_s=seconds))
    value = line.credits * pricing.premium_voice_credit_usd()
    assert line.provider_usd == pytest.approx(cost.estimate_tts_cost(seconds * 30))
    assert value >= pricing.MIN_MARKUP * line.provider_usd - 1e-9
    assert line.kind == pricing.KIND_PREMIUM_VOICE


@pytest.mark.parametrize("seconds", [15, 60, 61, 180])
def test_premium_music_is_at_least_three_times_provider_cost(seconds):
    line = pricing.premium_music_line(_params(target_duration_s=seconds))
    value = line.credits * pricing.premium_voice_credit_usd()
    assert value >= pricing.MIN_MARKUP * line.provider_usd - 1e-9
    assert line.source.startswith("https://elevenlabs.io/pricing")


def test_music_price_override(monkeypatch):
    monkeypatch.setenv("MENIVOR_MUSIC_USD_PER_MIN", "0.15")
    assert pricing.music_usd_per_min() == 0.15
    monkeypatch.setenv("MENIVOR_MUSIC_USD_PER_MIN", "nonsense")
    assert pricing.music_usd_per_min() == pricing.DEFAULT_MUSIC_USD_PER_MIN


@pytest.mark.parametrize("provider", ["heygen", "d-id", "musetalk"])
def test_presenter_is_three_times_provider_cost_in_cents(provider):
    line = pricing.presenter_line(
        _params(layout="avatar_bottom_screen_top", avatar_provider=provider)
    )
    assert line.kind == pricing.KIND_AI_VIDEO
    # 1 AI-video credit = 1 cent.
    assert line.credits / 100 >= pricing.MIN_MARKUP * line.provider_usd - 1e-9


def test_unknown_presenter_provider_is_unpriced_not_default_priced():
    params = _params(layout="avatar_bottom_screen_top", avatar_provider="brand-new-avatar")
    with pytest.raises(pricing.SkuUnpriced) as exc:
        pricing.credit_cost(params, premium_voice=False, premium_music=False)
    assert exc.value.as_dict()["code"] == "sku_unpriced"
    assert exc.value.status_code == 402


def test_quote_splits_credit_kinds_and_scales_by_variants():
    quote = pricing.credit_cost(
        _params(target_duration_s=90), premium_voice=True, premium_music=False
    )
    assert quote.standard_credits == 2
    assert quote.premium_voice_credits >= 1
    assert quote.ai_video_credits == 0
    data = quote.as_dict(3)
    assert data["total"]["standard"] == 6
    assert data["total"]["premium_voice"] == 3 * quote.premium_voice_credits
    assert {line["sku"] for line in data["lines"]} == {"long_form", "premium_voice"}


# --------------------------------------------------------------------------- #
# HTTP: price before render, 402 on unpriced
# --------------------------------------------------------------------------- #
def test_quote_endpoint_prices_before_render_and_creates_nothing(db, api, monkeypatch):  # noqa: F811 - shared fixtures
    monkeypatch.setattr(formats, "elevenlabs_configured", lambda: True)
    client, pipeline = api
    uid = _user(db, credits=5, voice=1)
    body = {
        "variants": 2,
        "params": {"video_subject": "cats", "layout": "captions_only", "voice_name": "elevenlabs:abc"},
    }
    res = client.post("/api/v1/jobs/quote", json=body, headers=_HEADERS)
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["per_variant"]["standard"] == 1
    assert data["total"]["premium_voice"] == 2 * data["per_variant"]["premium_voice"]
    assert data["balances"] == {"standard": 5, "premium_voice": 1, "ai_video": 0}
    assert data["affordable"] is True
    assert data["premium_downgraded"] is True
    assert pipeline.start_calls == []
    assert _balances(db, uid) == (5, 1, 0)
    with db() as s:
        assert JobRepository(s).list_for_user(uid) == []


def test_quote_matches_what_create_debits(db, api, monkeypatch):  # noqa: F811 - shared fixtures
    monkeypatch.setattr(formats, "elevenlabs_configured", lambda: True)
    client, _pipeline = api
    uid = _user(db, credits=5, voice=10)
    body = {"params": {"video_subject": "cats", "layout": "captions_only", "voice_name": "elevenlabs:abc"}}
    quoted = client.post("/api/v1/jobs/quote", json=body, headers=_HEADERS).json()["data"]
    res = client.post("/api/v1/jobs", json=body, headers=_HEADERS)
    assert res.status_code == 200, res.text
    assert _balances(db, uid)[1] == 10 - quoted["total"]["premium_voice"]


def test_unpriced_presenter_is_402_on_quote_and_create_and_charges_nothing(db, api):  # noqa: F811 - shared fixtures
    client, pipeline = api
    uid = _user(db, credits=5, ai=10_000)
    _pro(db, uid)
    body = {"params": {"video_subject": "cats", "avatar_provider": "brand-new-avatar"}}
    for path in ("/api/v1/jobs/quote", "/api/v1/jobs"):
        res = client.post(path, json=body, headers=_HEADERS)
        assert res.status_code == 402, res.text
        assert res.json()["data"]["code"] == "sku_unpriced"
    assert _balances(db, uid) == (5, 0, 10_000)
    assert pipeline.start_calls == []


def test_ai_video_credits_needed_follows_the_table():
    params = _params(layout="avatar_bottom_screen_top")
    assert premium.ai_video_credits_needed(params) == pricing.presenter_line(params).credits
    assert premium.ai_video_credits_needed(_params()) == 0


# --------------------------------------------------------------------------- #
# MH1: preset quote before render
# --------------------------------------------------------------------------- #
def test_preset_quote_prices_in_ai_video_credits_only(db, api, monkeypatch):  # noqa: F811 - shared fixtures
    from app.domains.routing import tiers

    monkeypatch.setattr(tiers, "provider_configured", lambda provider: True)
    client, pipeline = api
    uid = _user(db, credits=5, ai=50)
    body = {"preset_sku": "broll_clip", "tier": "draft", "seconds": 5, "variants": 2}
    res = client.post("/api/v1/jobs/quote/preset", json=body, headers=_HEADERS)
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    quote, route = pricing.preset_credit_cost("broll_clip", "draft", 5)
    assert data["route"]["model_id"] == route.model_id
    assert data["per_variant"] == {"standard": 0, "premium_voice": 0, "ai_video": quote.ai_video_credits}
    assert data["total"]["ai_video"] == 2 * quote.ai_video_credits
    assert data["balances"] == {"ai_video": 50}
    assert data["affordable"] is (50 >= 2 * quote.ai_video_credits)
    assert pipeline.start_calls == []
    assert _balances(db, uid) == (5, 0, 50)


def test_unpriced_preset_quote_is_402(db, api):  # noqa: F811 - shared fixtures
    client, _pipeline = api
    _user(db, credits=5)
    for body in (
        {"preset_sku": "no_such_preset", "tier": "draft", "seconds": 5},
        {"preset_sku": "broll_clip", "tier": "final", "seconds": 5, "resolution": "4k"},
    ):
        res = client.post("/api/v1/jobs/quote/preset", json=body, headers=_HEADERS)
        assert res.status_code == 402, res.text
        assert res.json()["data"]["code"] == "sku_unpriced"
