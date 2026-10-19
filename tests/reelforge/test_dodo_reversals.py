# ruff: noqa: F811 - pytest fixtures are imported from test_dodo_payments
"""MG2: Dodo money reversals (gtm/policy/MONEY-REVERSALS.md).

Real SQLite ledger + real billing service; only Dodo HTTP, Redis, owner
alerts and mail are faked.

* A refunded pack is debited in full even after spending (owed), renders are
  refused while owed, and the next top-up settles owed first.
* A partial refund is pro rata; a later dispute loss debits only the rest.
* dispute.opened freezes every class and alerts the owner; top-ups stay frozen;
  dispute.won releases exactly what was held.
* dispute.lost reverses like a full refund; a refund after it changes nothing.
* A plan refund expires the period's included reels and ends the plan.
* A workspace pack refund debits the pool; a card check refund removes the trial.
* Every path is idempotent under replays.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.db.creator_subscription import CreatorSubscription
from app.models.db.models import AuditLog, CreditLedger, Workspace
from app.models.db.repositories import CreditRepository
from app.services.billing import dodo_billing
from app.services.billing.plans import SIGNUP_GRANT, get_plan
from tests.reelforge.test_dodo_payments import (  # noqa: F401 - fixture import
    CARD,
    PLAN_CREATOR_M,
    STARTER,
    _balance,
    _payment_event,
    _signed,
    env,
)

URL = "/api/v1/billing/webhook/dodo"


@pytest.fixture()
def alerts(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(dodo_billing, "_alert_owner", seen.append)
    monkeypatch.setattr(dodo_billing, "_notify_user", lambda *a, **k: None)
    return seen


def _post(client, event: dict, msg: str):
    body, headers = _signed(event, msg_id=msg)
    resp = client.post(URL, content=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _refund(pid: str, *, refund_id="ref_1", amount=None, partial=False) -> dict:
    data = {"refund_id": refund_id, "payment_id": pid, "status": "succeeded", "is_partial": partial}
    if amount is not None:
        data["amount"] = amount
    return {"type": "refund.succeeded", "business_id": "bus_1", "data": data}


def _dispute(etype: str, pid: str) -> dict:
    return {"type": etype, "business_id": "bus_1",
            "data": {"dispute_id": "dsp_1", "payment_id": pid, "amount": 1900}}


def _buy(client, fake, user_id: str, pid: str, *, total=1900, msg=None, workspace_id=""):
    event = _payment_event(user_id, STARTER, payment_id=pid)
    if workspace_id:
        event["data"]["metadata"]["workspace_id"] = workspace_id
    fake.payments[pid] = {**event["data"], "total_amount": total}
    _post(client, event, msg or f"buy_{pid}")


def _spend(Factory, user_id: str, amount: int) -> None:
    with Factory() as s:
        CreditRepository(s).debit(user_id, amount, None, "job_debit")
        s.commit()


STARTER_CREDITS = get_plan("starter").credits


def test_refund_after_spending_leaves_owed_and_next_topup_settles_it(env, alerts):
    client, Factory, (user_id, _), fake = env
    _buy(client, fake, user_id, "pay_a")
    _spend(Factory, user_id, 2)
    for msg in ("r1", "r2"):
        _post(client, _refund("pay_a"), msg)
    assert _balance(Factory, user_id) == -2
    assert dodo_billing.owed(user_id) == 2
    with Factory() as s, pytest.raises(ValueError):
        CreditRepository(s).debit(user_id, 1, None, "job_debit")
    _buy(client, fake, user_id, "pay_b")
    assert _balance(Factory, user_id) == STARTER_CREDITS - 2
    assert dodo_billing.owed(user_id) == 0


def test_partial_refund_is_pro_rata_and_dispute_loss_takes_only_the_rest(env, alerts):
    client, Factory, (user_id, _), fake = env
    _buy(client, fake, user_id, "pay_p", total=1000)
    _post(client, _refund("pay_p", refund_id="ref_half", amount=500, partial=True), "rp1")
    _post(client, _refund("pay_p", refund_id="ref_half", amount=500, partial=True), "rp2")
    half = (STARTER_CREDITS * 500 + 500) // 1000
    assert _balance(Factory, user_id) == STARTER_CREDITS - half
    _post(client, _dispute("dispute.opened", "pay_p"), "d1")
    _post(client, _dispute("dispute.lost", "pay_p"), "d2")
    assert _balance(Factory, user_id) == 0
    _post(client, _refund("pay_p", refund_id="ref_all"), "rp3")  # after the loss: no change
    assert _balance(Factory, user_id) == 0


def test_dispute_opened_freezes_alerts_and_won_releases(env, alerts):
    client, Factory, (user_id, _), fake = env
    _buy(client, fake, user_id, "pay_d")
    for msg in ("o1", "o2"):
        _post(client, _dispute("dispute.opened", "pay_d"), msg)
    assert _balance(Factory, user_id) == 0
    assert dodo_billing.spending_frozen(user_id) is True
    assert any("dispute.opened" in text for text in alerts)
    with Factory() as s, pytest.raises(ValueError):
        CreditRepository(s).debit(user_id, 1, None, "job_debit")
    _buy(client, fake, user_id, "pay_e")  # a top-up during the dispute stays frozen
    assert _balance(Factory, user_id) == 0
    for msg in ("w1", "w2"):
        _post(client, _dispute("dispute.won", "pay_d"), msg)
    assert dodo_billing.spending_frozen(user_id) is False
    assert _balance(Factory, user_id) == 2 * STARTER_CREDITS


def test_dispute_lost_reverses_once_and_refund_after_changes_nothing(env, alerts):
    client, Factory, (user_id, _), fake = env
    _buy(client, fake, user_id, "pay_l")
    _buy(client, fake, user_id, "pay_keep")
    _post(client, _dispute("dispute.opened", "pay_l"), "l1")
    for msg in ("l2", "l3"):
        _post(client, _dispute("dispute.lost", "pay_l"), msg)
    _post(client, _refund("pay_l"), "l4")
    assert _balance(Factory, user_id) == STARTER_CREDITS
    assert dodo_billing.spending_frozen(user_id) is False
    with Factory() as s:
        actions = [a for (a,) in s.query(AuditLog.action).all()]
    assert "billing.dispute.lost" in actions and "billing.dispute_lost" in actions


def test_plan_refund_expires_included_reels_and_ends_plan(env, alerts):
    client, Factory, (user_id, _), fake = env
    period_end = datetime.now(timezone.utc) + timedelta(days=30)
    sub = {
        "type": "subscription.active", "business_id": "bus_1",
        "data": {"payload_type": "Subscription", "subscription_id": "sub_r", "status": "active",
                 "product_id": PLAN_CREATOR_M, "customer": {"customer_id": "cus_9"},
                 "next_billing_date": period_end.isoformat(), "cancel_at_next_billing_date": False,
                 "metadata": {"kind": "creator_plan", "user_id": user_id, "plan_key": "creator",
                              "interval": "month"}},
    }
    _post(client, sub, "s1")
    granted = _balance(Factory, user_id)
    assert granted > 0
    fake.payments["pay_sub"] = {"payment_id": "pay_sub", "status": "succeeded",
                                "subscription_id": "sub_r", "total_amount": 1900,
                                "metadata": {"user_id": user_id, "kind": "creator_plan"}}
    for msg in ("sr1", "sr2"):
        _post(client, _refund("pay_sub"), msg)
    assert _balance(Factory, user_id) == 0
    with Factory() as s:
        row = s.query(CreatorSubscription).filter_by(user_id=user_id).one()
        assert row.status == "canceled"
    assert any(c["method"] == "PATCH" and c["path"].endswith("/sub_r") for c in fake.calls)
    _post(client, sub, "s2")  # a late "active" never revives a refunded plan
    assert _balance(Factory, user_id) == 0


def test_workspace_pack_refund_debits_the_pool(env, alerts):
    client, Factory, (user_id, _), fake = env
    with Factory() as s:
        ws = Workspace(name="Team", owner_id=user_id)
        s.add(ws)
        s.commit()
        ws_id = ws.id
    _buy(client, fake, user_id, "pay_w", workspace_id=ws_id)
    with Factory() as s:
        assert CreditRepository(s).workspace_balance(ws_id) == STARTER_CREDITS
    for msg in ("w1", "w2"):
        _post(client, _refund("pay_w"), msg)
    with Factory() as s:
        assert CreditRepository(s).workspace_balance(ws_id) == 0


def test_card_check_refund_removes_the_trial(env, alerts):
    client, Factory, (user_id, _), fake = env
    event = _payment_event(user_id, CARD, payment_id="pay_c", kind="card_check", plan_key="card_check")
    fake.payments["pay_c"] = {**event["data"], "total_amount": 100}
    _post(client, event, "c1")
    assert _balance(Factory, user_id) == 1 + SIGNUP_GRANT
    for msg in ("c2", "c3"):
        _post(client, _refund("pay_c"), msg)
    assert _balance(Factory, user_id) == 0
    with Factory() as s:
        rows = s.query(CreditLedger.reason).filter(CreditLedger.reason.like("refund:dodo:pay_c%")).all()
    assert len(rows) == 1


def test_unknown_refund_alerts_owner(env, alerts):
    client, _Factory, _ids, _fake = env
    out = _post(client, _refund("pay_nobody"), "u1")
    assert out["removed"] == 0
    assert any("pay_nobody" in text for text in alerts)


def test_owner_alert_email_outage_does_not_fail_the_webhook(monkeypatch):
    """A processed refund/dispute must not turn into a 500 because SMTP is down."""
    from app.services import mailer
    from app.services.billing import dodo_billing as billing

    monkeypatch.setenv("MENIVOR_OWNER_ALERT_EMAIL", "owner@example.com")
    monkeypatch.delenv("MENIVOR_OWNER_NTFY_URL", raising=False)

    def smtp_down(**_kwargs):
        raise ConnectionError("smtp down")

    monkeypatch.setattr(mailer, "send_email", smtp_down)
    billing._alert_owner("dispute opened")  # must not raise
