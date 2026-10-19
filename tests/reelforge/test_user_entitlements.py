"""Unified personal entitlements (M0.1): web plans, packs and mobile Pro.

Real SQLite ledger and ``creator_subscriptions`` rows; only RevenueCat is faked.
Every source unlocks the clean download and paid actions; "none" fails closed
(402), and an unverifiable source with no grant answers 503, never 200.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.db.base as db_base
from app.models.db.base import Base
from app.models.db.creator_subscription import CreatorSubscription
from app.models.db.models import CreditLedger, User
from app.models.db.repositories import CreditRepository
from app.models.exception import HttpException
from app.services import user_entitlements as ue
from app.services.billing import pro_access, revenuecat_client

API_ROOT = Path(__file__).resolve().parents[2] / "apps" / "api" / "app"


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(db_base, "get_session", _session)
    with _session() as s:
        user = User(email="buyer@example.com", display_name="Buyer", api_key_hash="h1")
        s.add(user)
        s.flush()
        user_id = user.id
    return factory, user_id


@pytest.fixture()
def rc_denies(monkeypatch):
    calls: list[str] = []

    def deny(user_id):
        calls.append(user_id)
        raise revenuecat_client.RevenueCatAccessDenied("no")

    monkeypatch.setattr(revenuecat_client, "require_pro_entitlement", deny)
    return calls


def _subscribe(factory, user_id, *, provider, status="active", plan_key="creator"):
    with factory() as s:
        s.add(
            CreatorSubscription(
                user_id=user_id,
                plan_key=plan_key,
                provider=provider,
                provider_ref=f"sub_{provider}",
                status=status,
            )
        )
        s.commit()


def _grant(factory, user_id, credits, reason):
    with factory() as s:
        CreditRepository(s).grant(user_id, credits, reason)
        s.commit()


def _debit(factory, user_id, credits, reason="job_debit"):
    with factory() as s:
        CreditRepository(s).debit(user_id, credits, None, reason)
        s.commit()


def _age_ledger(factory, user_id, days):
    with factory() as s:
        s.execute(
            update(CreditLedger)
            .where(CreditLedger.user_id == user_id)
            .values(created_at=datetime.now(timezone.utc) - timedelta(days=days))
        )
        s.commit()


# --------------------------------------------------------------------------- #
# One case per source
# --------------------------------------------------------------------------- #
def test_dodo_monthly_plan_unlocks_everything(db, rc_denies):
    factory, user_id = db
    _subscribe(factory, user_id, provider="dodo", plan_key="pro")
    result = ue.user_entitlements(user_id)
    assert (result.plan, result.source) == ("pro", "dodo")
    assert result.clean_download and result.publish and not result.watermark
    assert rc_denies == []  # local grant: no billing request


def test_creem_monthly_plan_unlocks_everything(db, rc_denies):
    factory, user_id = db
    _subscribe(factory, user_id, provider="creem")
    result = ue.user_entitlements(user_id)
    assert (result.plan, result.source) == ("creator", "creem")
    assert result.clean_download and result.publish


def test_revenuecat_pro_unlocks_everything(db, monkeypatch):
    _factory, user_id = db
    monkeypatch.setattr(revenuecat_client, "require_pro_entitlement", lambda _uid: object())
    result = ue.user_entitlements(user_id)
    assert (result.plan, result.source) == ("pro", "revenuecat")
    assert result.clean_download and result.publish


def test_pack_with_credits_left_unlocks(db, rc_denies):
    factory, user_id = db
    _grant(factory, user_id, 30, "purchase:dodo:pay_1")
    result = ue.user_entitlements(user_id)
    assert (result.plan, result.source, result.credits_left) == ("pack", "pack", 30)
    assert result.clean_download


def test_none_fails_closed(db, rc_denies):
    factory, user_id = db
    _grant(factory, user_id, 3, "signup")
    result = ue.user_entitlements(user_id)
    assert (result.plan, result.source) == ("free", "none")
    assert not result.clean_download and not result.publish and result.watermark
    assert not result.unavailable
    with pytest.raises(ue.PaidAccessDenied):
        ue.require_paid_access(user_id)


# --------------------------------------------------------------------------- #
# Edges that must not open paid features
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("status", ["past_due", "canceled"])
def test_lapsed_plan_does_not_unlock(db, rc_denies, status):
    factory, user_id = db
    _subscribe(factory, user_id, provider="dodo", status=status)
    assert not ue.user_entitlements(user_id).clean_download


def test_card_check_and_signup_do_not_count_as_pack(db, rc_denies):
    factory, user_id = db
    _grant(factory, user_id, 1, "purchase:creem:chk_1")
    _grant(factory, user_id, 3, "signup")
    assert not ue.user_entitlements(user_id).clean_download


def test_monthly_plan_grant_is_not_a_pack(db, rc_denies):
    factory, user_id = db
    _grant(factory, user_id, 35, "purchase:dodo:msub:sub_1:1790000000")
    assert not ue.user_entitlements(user_id).clean_download


def test_refunded_pack_does_not_count(db, rc_denies):
    factory, user_id = db
    _grant(factory, user_id, 30, "purchase:dodo:pay_9")
    _debit(factory, user_id, 30, "refund:dodo:pay_9")
    _grant(factory, user_id, 3, "signup")
    assert not ue.user_entitlements(user_id).clean_download


def test_spent_pack_keeps_access_inside_grace_then_closes(db, rc_denies):
    factory, user_id = db
    _grant(factory, user_id, 30, "purchase:dodo:pay_2")
    _debit(factory, user_id, 30)
    assert ue.user_entitlements(user_id).clean_download
    _age_ledger(factory, user_id, ue.PACK_GRACE_DAYS + 1)
    assert not ue.user_entitlements(user_id).clean_download


def test_unverifiable_source_without_grant_is_unavailable(db, monkeypatch):
    _factory, user_id = db

    def outage(_uid):
        raise revenuecat_client.RevenueCatUnavailableError("down")

    monkeypatch.setattr(revenuecat_client, "require_pro_entitlement", outage)
    result = ue.user_entitlements(user_id)
    assert not result.clean_download and result.unavailable
    with pytest.raises(ue.PaidAccessUnavailable):
        ue.require_paid_access(user_id)


def test_database_outage_fails_closed(monkeypatch, rc_denies):
    @contextmanager
    def broken():
        raise RuntimeError("db down")
        yield  # pragma: no cover

    monkeypatch.setattr(db_base, "get_session", broken)
    result = ue.user_entitlements("user-x")
    assert not result.clean_download and result.unavailable


def test_blank_user_is_free():
    assert not ue.user_entitlements("").clean_download


# --------------------------------------------------------------------------- #
# HTTP gates
# --------------------------------------------------------------------------- #
def test_require_pro_action_maps_outcomes(db, monkeypatch, rc_denies):
    factory, user_id = db
    with pytest.raises(HttpException) as denied:
        pro_access.require_pro_action(user_id, "req-1", action="share")
    assert denied.value.status_code == 402

    _subscribe(factory, user_id, provider="dodo")
    pro_access.require_pro_action(user_id, "req-2", action="share")  # no raise

    def outage(_uid):
        raise revenuecat_client.RevenueCatConfigurationError("unset")

    monkeypatch.setattr(revenuecat_client, "require_pro_entitlement", outage)
    with pytest.raises(HttpException) as unavailable:
        pro_access.require_pro_action("someone-else", "req-3", action="share")
    assert unavailable.value.status_code == 503


def test_dodo_subscriber_passes_every_paid_gate(db, rc_denies):
    factory, user_id = db
    _subscribe(factory, user_id, provider="dodo")
    from app.domains.adstudio.publish_gate import pro_state
    from app.domains.reels.router import _can_access_clean_result

    for action in (
        "auto-publish",
        "native publish",
        "export",
        "share",
        "scheduled publish",
        "studio publish",
        "direct publish",
    ):
        pro_access.require_pro_action(user_id, "req", action=action)
    assert _can_access_clean_result(user_id, "req") is True
    assert pro_state(user_id)["status"] == "active"


def test_no_call_site_bypasses_unified_entitlements():
    """Only the entitlements module may ask RevenueCat directly."""
    allowed = {API_ROOT / "services" / "user_entitlements.py", API_ROOT / "services" / "billing" / "revenuecat_client.py"}
    offenders = []
    for path in API_ROOT.rglob("*.py"):
        if path in allowed:
            continue
        if re.search(r"require_pro_entitlement\(", path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(API_ROOT)))
    assert offenders == []


# --------------------------------------------------------------------------- #
# Internal comp accounts (explicit MENIVOR_COMP_EMAILS list only)
# --------------------------------------------------------------------------- #
def test_comp_email_grants_clean_download(db, rc_denies, monkeypatch):
    _, user_id = db
    monkeypatch.setenv("MENIVOR_COMP_EMAILS", "other@example.com, BUYER@example.com")
    result = ue.user_entitlements(user_id)
    assert result.clean_download is True
    assert result.source == ue.SOURCE_COMP
    assert rc_denies == []


def test_comp_unset_or_unlisted_grants_nothing(db, rc_denies, monkeypatch):
    _, user_id = db
    monkeypatch.delenv("MENIVOR_COMP_EMAILS", raising=False)
    assert ue.user_entitlements(user_id).clean_download is False
    monkeypatch.setenv("MENIVOR_COMP_EMAILS", "someone@else.com")
    assert ue.user_entitlements(user_id).clean_download is False
