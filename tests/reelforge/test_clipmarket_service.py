"""Clipmarket persistence + fraud-gated payout service (sqlite)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.clipmarket import service as svc
from app.domains.clipmarket.payout import ViewSignals
from app.models.db import clipmarket, models  # noqa: F401 - register tables
from app.models.db.base import Base
from app.models.db.models import User


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    for uid in ("brand", "clipper"):
        s.add(User(id=uid, email=f"{uid}@x.com"))
    s.flush()
    # Campaign budgets are escrowed from the brand's wallet.
    _fund_wallet(s, "brand", 1_000_000_000)
    yield s
    s.close()


def _fund_wallet(session, user_id: str, micros: int) -> None:
    """Grant wallet balance so campaign budgets can be escrowed."""
    from app.domains.wallet.repository import ENTRY_GRANT, WalletRepository

    repo = WalletRepository(session)
    account = repo.get_or_create_personal_account(user_id)
    repo.append_entry(account.id, entry_type=ENTRY_GRANT, reason="test_topup",
                      available_delta=micros)
    session.flush()


def _clean_signals(views):
    return ViewSignals(views=views, velocity_zscore=1.0, avg_watch_frac=0.55,
                       engagement_rate=0.05, geo_concentration=0.2, retention_cliff=0.2)


def _bot_signals(views):
    return ViewSignals(views=views, velocity_zscore=12.0, avg_watch_frac=0.02,
                       engagement_rate=0.0, geo_concentration=0.95, retention_cliff=0.95)


def test_clean_submission_approved_and_budget_advanced(session):
    camp = svc.create_campaign(session, brand_id="brand", cpm_micros=2_000_000,
                               budget_micros=500_000_000, title="Summer")
    sub = svc.submit_clip(session, campaign_id=camp.id, clipper_id="clipper", clip_url="https://x")
    assert sub.status == "pending"

    reviewed = svc.review_submission(session, submission_id=sub.id, reviewer_id="brand", signals=_clean_signals(50_000))
    assert reviewed.status == "approved"
    assert reviewed.payable_micros == 100_000_000  # 50k views @ $2 CPM
    # Budget advanced in the same txn.
    assert session.get(clipmarket.ClipCampaign, camp.id).spent_micros == 100_000_000


def test_viewbot_held_for_review_not_paid(session):
    camp = svc.create_campaign(session, brand_id="brand", cpm_micros=2_000_000, budget_micros=500_000_000)
    sub = svc.submit_clip(session, campaign_id=camp.id, clipper_id="clipper", clip_url="https://x")
    reviewed = svc.review_submission(session, submission_id=sub.id, reviewer_id="brand", signals=_bot_signals(100_000))
    assert reviewed.status == "held_review" and reviewed.payable_micros == 0
    assert reviewed.fraud_score >= 55 and "velocity_spike" in reviewed.fraud_flags
    # No budget spent on a held submission.
    assert session.get(clipmarket.ClipCampaign, camp.id).spent_micros == 0


def test_budget_cap_exhausts_campaign(session):
    camp = svc.create_campaign(session, brand_id="brand", cpm_micros=2_000_000, budget_micros=10_000_000)
    sub = svc.submit_clip(session, campaign_id=camp.id, clipper_id="clipper", clip_url="https://x")
    reviewed = svc.review_submission(session, submission_id=sub.id, reviewer_id="brand", signals=_clean_signals(50_000))
    # Payout capped to the 10M budget; campaign flips to exhausted.
    assert reviewed.payable_micros == 10_000_000
    assert session.get(clipmarket.ClipCampaign, camp.id).status == "exhausted"


def test_submit_to_inactive_campaign_rejected(session):
    camp = svc.create_campaign(session, brand_id="brand", cpm_micros=1_000_000, budget_micros=1_000_000)
    camp.status = "ended"
    session.flush()
    with pytest.raises(svc.ClipmarketError):
        svc.submit_clip(session, campaign_id=camp.id, clipper_id="clipper", clip_url="https://x")


def test_create_campaign_requires_funded_wallet(session):
    with pytest.raises(svc.ClipmarketError) as ei:
        svc.create_campaign(session, brand_id="clipper", cpm_micros=1_000_000,
                            budget_micros=10_000_000)
    assert ei.value.status_code == 402


def test_clean_payout_moves_escrow_to_clipper_wallet(session):
    from app.domains.wallet.repository import WalletRepository

    camp = svc.create_campaign(session, brand_id="brand", cpm_micros=2_000_000,
                               budget_micros=500_000_000)
    sub = svc.submit_clip(session, campaign_id=camp.id, clipper_id="clipper", clip_url="https://x")
    svc.review_submission(session, submission_id=sub.id, reviewer_id="brand",
                          signals=_clean_signals(50_000))
    repo = WalletRepository(session)
    clipper = repo.get_or_create_personal_account("clipper")
    brand = repo.get_or_create_personal_account("brand")
    session.refresh(clipper)
    session.refresh(brand)
    assert clipper.available_micros == 100_000_000
    # 1,000 USD funded - 500 escrowed; 400 of the escrow still held.
    assert brand.available_micros == 500_000_000
    assert brand.reserved_micros == 400_000_000


def test_only_campaign_brand_can_review(session):
    camp = svc.create_campaign(session, brand_id="brand", cpm_micros=2_000_000,
                               budget_micros=500_000_000)
    sub = svc.submit_clip(session, campaign_id=camp.id, clipper_id="clipper", clip_url="https://x")
    with pytest.raises(svc.ClipmarketError) as ei:
        svc.review_submission(session, submission_id=sub.id, reviewer_id="clipper",
                              signals=_clean_signals(50_000))
    assert ei.value.status_code == 404
