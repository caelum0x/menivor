# ruff: noqa: F811 - pytest fixtures are imported from test_user_entitlements
"""MV-ENT1: a premium voice or AI-video pack unlocks the clean MP4.

Owner decision (2026-09-28): a premium-credit purchase counts as paid, under
the same grace rule as a standard pack. A refunded or disputed premium pack
does not unlock it. The refund and dispute paths are driven through the real
MG2 code (``dodo_billing.reverse_payment`` / ``handle_dispute``); only the Dodo
payment lookup, alerts and notices are faked.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app.models.db.premium_credit import KIND_AI_VIDEO, KIND_PREMIUM_VOICE, PremiumCreditLedger
from app.services import user_entitlements as ue
from app.services.billing import dodo_billing
from app.services.billing import premium_credits as pc
from tests.reelforge.test_user_entitlements import _grant, _subscribe, db, rc_denies  # noqa: F401


@pytest.fixture()
def dodo(monkeypatch, db):
    """Resolve premium payments to the test user; silence alerts and notices."""
    _factory, user_id = db

    def resolve(pid):
        return {"payment_id": pid, "kind": "premium", "user_id": user_id, "workspace_id": None,
                "credits": 0, "subscription_id": "", "total": 0, "metadata": {}}

    monkeypatch.setattr(dodo_billing, "resolve_payment", resolve)
    monkeypatch.setattr(dodo_billing, "_alert_owner", lambda _text: None)
    monkeypatch.setattr(dodo_billing, "_notify_user", lambda *_a, **_k: None)
    return db


def _buy(user_id, key, pid):
    return pc.grant_purchase_once(user_id, pc.get_pack(key), provider="dodo", reference=pid)


def _spend(factory, user_id, kind, amount, job="job_1"):
    with factory() as s:
        pc.debit(s, user_id, kind, amount, f"{pc.DEBIT_REASON}:{job}", job)
        s.commit()


def _age_premium(factory, user_id, days):
    with factory() as s:
        s.execute(
            update(PremiumCreditLedger)
            .where(PremiumCreditLedger.user_id == user_id)
            .values(created_at=datetime.now(timezone.utc) - timedelta(days=days))
        )
        s.commit()


# --------------------------------------------------------------------------- #
# Premium packs count as paid
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("key", ["premium_voice_25", "ai_video_2000"])
def test_premium_pack_with_credits_left_unlocks(db, rc_denies, key):
    _factory, user_id = db
    assert _buy(user_id, key, "pay_p1") > 0
    result = ue.user_entitlements(user_id)
    assert (result.plan, result.source) == (ue.PACK, ue.SOURCE_PREMIUM_PACK)
    assert result.clean_download and result.publish and not result.watermark
    assert rc_denies == []  # local grant: no billing request


def test_spent_premium_pack_keeps_access_inside_grace_then_closes(db, rc_denies):
    factory, user_id = db
    _buy(user_id, "premium_voice_25", "pay_p2")
    _spend(factory, user_id, KIND_PREMIUM_VOICE, 25)
    assert ue.user_entitlements(user_id).clean_download
    _age_premium(factory, user_id, ue.PACK_GRACE_DAYS + 1)
    assert not ue.user_entitlements(user_id).clean_download


def test_premium_credits_without_a_purchase_do_not_unlock(db, rc_denies):
    factory, user_id = db
    with factory() as s:
        pc.grant(s, user_id, KIND_AI_VIDEO, 500, "support_adjust:ticket_1")
        pc.grant(s, user_id, KIND_PREMIUM_VOICE, 2, f"{pc.REFUND_REASON}:job_9", "job_9")
        s.commit()
    assert not ue.user_entitlements(user_id).clean_download


# --------------------------------------------------------------------------- #
# Refunds and disputes (MG2 events) do not unlock
# --------------------------------------------------------------------------- #
def test_refunded_premium_pack_does_not_unlock(dodo, rc_denies):
    _factory, user_id = dodo
    _buy(user_id, "ai_video_2000", "pay_r1")
    out = dodo_billing.reverse_payment("pay_r1")
    assert out["kind"] == "premium" and out["debited"] == 2000
    assert not ue.user_entitlements(user_id).clean_download


def test_refund_after_credits_were_spent_does_not_unlock(dodo, rc_denies):
    factory, user_id = dodo
    _buy(user_id, "premium_voice_25", "pay_r2")
    _spend(factory, user_id, KIND_PREMIUM_VOICE, 25)
    out = dodo_billing.reverse_payment("pay_r2")
    assert out["debited"] == 0  # nothing left to claw back: only the audit row records it
    assert not ue.user_entitlements(user_id).clean_download


def test_open_dispute_blocks_then_won_dispute_restores(dodo, rc_denies):
    _factory, user_id = dodo
    _buy(user_id, "premium_voice_25", "pay_d1")
    dodo_billing.handle_dispute(dodo_billing.DISPUTE_OPENED, {"payment_id": "pay_d1"})
    assert not ue.user_entitlements(user_id).clean_download
    dodo_billing.handle_dispute("dispute.won", {"payment_id": "pay_d1"})
    result = ue.user_entitlements(user_id)
    assert result.clean_download and result.source == ue.SOURCE_PREMIUM_PACK


@pytest.mark.parametrize("etype", sorted(dodo_billing.DISPUTE_LOST_EVENTS))
def test_lost_dispute_does_not_unlock(dodo, rc_denies, etype):
    _factory, user_id = dodo
    _buy(user_id, "ai_video_2000", "pay_d2")
    dodo_billing.handle_dispute(dodo_billing.DISPUTE_OPENED, {"payment_id": "pay_d2"})
    dodo_billing.handle_dispute(etype, {"payment_id": "pay_d2"})
    assert not ue.user_entitlements(user_id).clean_download


def test_other_clean_premium_pack_still_unlocks(dodo, rc_denies):
    _factory, user_id = dodo
    _buy(user_id, "ai_video_2000", "pay_bad")
    dodo_billing.reverse_payment("pay_bad")
    _buy(user_id, "premium_voice_25", "pay_good")
    assert ue.user_entitlements(user_id).clean_download


def test_refund_row_matches_one_payment_id_exactly(dodo, rc_denies):
    """A refund row matches one payment id exactly (``pay_1`` is not ``pay_12``)."""
    _factory, user_id = dodo
    _buy(user_id, "premium_voice_25", "pay_12")
    with _factory() as s:
        s.add(PremiumCreditLedger(user_id=user_id, kind=KIND_AI_VIDEO, delta=0,
                                  reason="refund:dodo:pay_1", balance_after=0))
        s.commit()
    assert ue.user_entitlements(user_id).clean_download


# --------------------------------------------------------------------------- #
# Existing sources are unchanged
# --------------------------------------------------------------------------- #
def test_plan_and_standard_pack_keep_their_source(db, rc_denies):
    factory, user_id = db
    _buy(user_id, "premium_voice_25", "pay_p3")
    _grant(factory, user_id, 30, "purchase:dodo:pay_std")
    assert ue.user_entitlements(user_id).source == ue.SOURCE_PACK
    _subscribe(factory, user_id, provider="dodo", plan_key="pro")
    assert ue.user_entitlements(user_id).source == "dodo"
