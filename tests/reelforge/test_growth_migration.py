"""P11 growth — sunset-model migration recommender (Sora-shutdown onboarding)."""

from __future__ import annotations

from datetime import date

from app.domains.growth.migration import recommend_migration, sunsetting_models


def test_sora_urgent_window():
    # Sora 2 sunsets 2026-09-24. 5 days out -> urgent.
    offer = recommend_migration("sora2", on=date(2026, 9, 19))
    assert offer.needs_migration and offer.urgency == "urgent"
    assert offer.replacement == "veo" and offer.days_left == 5
    assert "migrate now" in offer.headline.lower()


def test_sora_soon_window():
    offer = recommend_migration("sora2", on=date(2026, 9, 1), soon_days=30)
    assert offer.urgency == "soon" and offer.replacement == "veo"


def test_sora_expired():
    offer = recommend_migration("sora2", on=date(2026, 10, 1))
    assert offer.urgency == "expired" and "offline" in offer.headline


def test_far_out_no_migration():
    offer = recommend_migration("sora2", on=date(2026, 1, 1), soon_days=30)
    assert not offer.needs_migration and offer.urgency == "none"
    assert offer.replacement == "veo"  # still surfaces the eventual target


def test_non_sunset_model_no_migration():
    assert not recommend_migration("kling", on=date(2026, 9, 1)).needs_migration


def test_campaign_sweep_lists_sunsetting():
    offers = sunsetting_models(on=date(2026, 9, 20), within_days=60)
    assert any(o.from_model == "sora2" for o in offers)
    # Sorted by urgency (fewest days left first).
    days = [o.days_left for o in offers if o.days_left is not None]
    assert days == sorted(days)
