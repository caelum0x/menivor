"""Dodo usage-based plans: overage grants + ``reel.rendered`` metering outbox.

Real SQLite ledger/jobs; only Dodo HTTP is faked.

* Free-tier, pack-only and non-Dodo-plan renders are never metered.
* A live Dodo plan meters renders inside the included window (free threshold).
* Past the included reels, pack-credit renders are not metered; overage-funded
  renders are, and overage grants respect MENIVOR_PLAN_OVERAGE(_CAP).
* Flush: ≤1,000 events per request, retry on 5xx/429/transport, permanent on
  other 4xx, idempotent event ids, stale timestamps re-stamped.
* A failed overage-funded reel is not refunded into a free credit.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.db.base as db_base
from app.models import const
from app.models.db.base import Base
from app.models.db.creator_subscription import CreatorSubscription
from app.models.db.dodo_usage_event import DodoUsageEvent
from app.models.db.models import CreditLedger, Job, User
from app.models.db.repositories import CreditRepository
from app.domains.reels import refunds
from app.services.billing import dodo_client, dodo_usage

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
PERIOD_END = datetime(2026, 10, 25, tzinfo=timezone.utc)


class FakeDodo:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.fail_with: list[Exception] = []

    def request(self, method, path, *, body=None, params=None):
        self.calls.append({"method": method, "path": path, "body": body})
        if self.fail_with:
            raise self.fail_with.pop(0)
        return {"ingested_count": len((body or {}).get("events", []))}


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        session = Factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(db_base, "get_session", _session)
    fake = FakeDodo()
    monkeypatch.setattr(dodo_client, "request", fake.request)
    monkeypatch.setattr(dodo_client, "is_configured", lambda: True)
    monkeypatch.delenv("MENIVOR_PLAN_OVERAGE", raising=False)
    monkeypatch.delenv("MENIVOR_PLAN_OVERAGE_CAP", raising=False)
    with _session() as s:
        user = User(email="meter@example.com", display_name="Meter")
        s.add(user)
        s.flush()
        uid = user.id
    return Factory, _session, uid, fake


def _plan(Session, uid, *, provider="dodo", status="active", customer="cus_1", plan="creator"):
    with Session() as s:
        s.add(
            CreatorSubscription(
                user_id=uid,
                plan_key=plan,
                interval="month",
                provider=provider,
                provider_ref="sub_1",
                customer_ref=customer,
                status=status,
                current_period_end=PERIOD_END,
            )
        )


def _grant(Session, uid, amount, reason="purchase:dodo:pay_pack"):
    with Session() as s:
        CreditRepository(s).grant(uid, amount, reason)


def _render(Session, uid, *, succeed=True) -> tuple[str, bool]:
    """Create + debit a reel job the way the reels router does; returns (job_id, ok)."""
    with Session() as s:
        job = Job(user_id=uid, kind="avatar_reel", state=const.TASK_STATE_PROCESSING)
        s.add(job)
        s.flush()
        jid = job.id
    try:
        with Session() as s:
            CreditRepository(s).debit(uid, 1, jid, "job_debit")
    except ValueError:
        return jid, False
    if succeed:
        dodo_usage.record_render(jid, seconds=31.5, now=NOW, flush=False)
    return jid, True


def _opt_in(Session, uid, granted=True, version=None):
    from app.services.compliance import consent

    with Session() as s:
        consent.record_consent(
            s, uid, dodo_usage.OVERAGE_CONSENT_KIND, granted,
            version=dodo_usage.consent_version() if version is None else version,
        )


def _events(Factory):
    with Factory() as s:
        return list(s.execute(select(DodoUsageEvent).order_by(DodoUsageEvent.id)).scalars())


def _balance(Factory, uid):
    with Factory() as s:
        return CreditRepository(s).balance(uid)


# --------------------------------------------------------------------------- #
# Decision matrix
# --------------------------------------------------------------------------- #
def test_free_tier_user_is_not_metered(env):
    Factory, Session, uid, _ = env
    _grant(Session, uid, 3, "signup")
    _render(Session, uid)
    assert _events(Factory) == []


def test_non_dodo_or_dead_plan_is_not_metered(env):
    Factory, Session, uid, _ = env
    _plan(Session, uid, provider="creem")
    _grant(Session, uid, 5)
    _render(Session, uid)
    assert _events(Factory) == []


def test_plan_without_customer_is_not_metered(env):
    Factory, Session, uid, _ = env
    _plan(Session, uid, customer="")
    _grant(Session, uid, 5)
    _render(Session, uid)
    assert _events(Factory) == []


def test_included_window_is_metered_then_pack_credits_are_not(env, monkeypatch):
    Factory, Session, uid, _ = env
    monkeypatch.setattr(dodo_usage, "included_reels", lambda row: 2)
    _plan(Session, uid)
    _grant(Session, uid, 2, "purchase:dodo:msub:sub_1:1")  # included reels
    _grant(Session, uid, 1)  # a pack credit
    for _ in range(3):
        _render(Session, uid)
    events = _events(Factory)
    assert len(events) == 2
    assert all(not e.overage for e in events)
    assert events[0].event_id.startswith("reel_")
    assert events[0].customer_id == "cus_1"
    assert events[0].meta["seconds"] == 31.5


def test_overage_is_granted_and_metered(env, monkeypatch):
    Factory, Session, uid, _ = env
    monkeypatch.setattr(dodo_usage, "included_reels", lambda row: 1)
    _plan(Session, uid)
    _opt_in(Session, uid)
    _grant(Session, uid, 1, "purchase:dodo:msub:sub_1:1")
    _render(Session, uid)  # included
    jid, ok = _render(Session, uid)  # no credits left -> overage
    assert ok
    with Factory() as s:
        reasons = [r for (r,) in s.execute(select(CreditLedger.reason).where(CreditLedger.job_id == jid))]
    assert f"overage:{jid}" in reasons
    events = _events(Factory)
    assert [e.overage for e in events] == [False, True]
    assert _balance(Factory, uid) == 0


def test_overage_cap_and_switch(env, monkeypatch):
    Factory, Session, uid, _ = env
    monkeypatch.setattr(dodo_usage, "included_reels", lambda row: 0)
    _plan(Session, uid)
    monkeypatch.setenv("MENIVOR_PLAN_OVERAGE_CAP", "2")
    _opt_in(Session, uid)
    assert _render(Session, uid)[1]
    assert _render(Session, uid)[1]
    assert not _render(Session, uid)[1]  # cap reached -> 402 path
    monkeypatch.setenv("MENIVOR_PLAN_OVERAGE_CAP", "10")
    monkeypatch.setenv("MENIVOR_PLAN_OVERAGE", "0")
    assert not _render(Session, uid)[1]
    monkeypatch.setenv("MENIVOR_PLAN_OVERAGE", "1")
    monkeypatch.setenv("MENIVOR_PLAN_OVERAGE_CAP", "0")
    assert not _render(Session, uid)[1]


# --------------------------------------------------------------------------- #
# MG6: overage is off until the user opts in to the shown terms
# --------------------------------------------------------------------------- #
def test_overage_is_off_by_default(env, monkeypatch):
    Factory, Session, uid, _ = env
    monkeypatch.setattr(dodo_usage, "included_reels", lambda row: 0)
    _plan(Session, uid)
    assert not _render(Session, uid)[1]  # no opt-in -> 402 path, nothing granted
    assert _balance(Factory, uid) == 0
    assert _events(Factory) == []


def test_opt_out_and_stale_terms_stop_overage(env, monkeypatch):
    Factory, Session, uid, _ = env
    monkeypatch.setattr(dodo_usage, "included_reels", lambda row: 0)
    _plan(Session, uid)
    _opt_in(Session, uid)
    assert _render(Session, uid)[1]
    _opt_in(Session, uid, granted=False)
    assert not _render(Session, uid)[1]
    _opt_in(Session, uid)
    monkeypatch.setenv("MENIVOR_PLAN_OVERAGE_CAP", "500")  # terms changed -> re-consent
    assert not _render(Session, uid)[1]
    _opt_in(Session, uid, version="something-else")
    assert not _render(Session, uid)[1]


def test_open_dispute_freezes_overage(env, monkeypatch):
    Factory, Session, uid, _ = env
    monkeypatch.setattr(dodo_usage, "included_reels", lambda row: 0)
    _plan(Session, uid)
    _opt_in(Session, uid)
    from app.services.billing import dodo_billing

    monkeypatch.setattr(dodo_billing, "open_disputes", lambda session, user_id: ["pay_1"])
    assert not _render(Session, uid)[1]
    monkeypatch.setattr(dodo_billing, "open_disputes", lambda session, user_id: [])
    assert _render(Session, uid)[1]


def test_overage_price_matches_the_dodo_meter():
    import importlib.util
    import sys
    from pathlib import Path

    from app.services.billing import creator_plans

    path = Path(__file__).resolve().parents[2] / "apps/api/tools/ops/create_dodo_products.py"
    spec = importlib.util.spec_from_file_location("create_dodo_products_mg6", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    for spec_ in mod.plan_specs("mtr_1"):
        _, key, interval = spec_.key.split("_")
        meter_cents = float(spec_.price["meters"][0]["price_per_unit"])
        assert float(dodo_usage.overage_price_usd(key, interval)) * 100 == pytest.approx(meter_cents)
    assert dodo_usage.overage_price_usd("creator", "month") == "0.4285"
    assert dodo_usage.overage_price_usd("nope", "month") == ""
    terms = dodo_usage.overage_terms()
    assert terms["default_on"] is False and terms["consent_kind"] == "plan_overage"
    assert set(terms["per_reel_usd"]) == {p.key for p in creator_plans.list_plans()}


def test_no_overage_for_non_subscribers_or_non_reel_debits(env):
    Factory, Session, uid, _ = env
    assert not _render(Session, uid)[1]
    _plan(Session, uid)
    with Factory() as s:
        job = Job(user_id=uid, kind="dub_video")
        s.add(job)
        s.commit()
        jid = job.id
    with pytest.raises(ValueError):
        with Session() as s:
            CreditRepository(s).debit(uid, 1, jid, "dub_debit")


def test_record_render_is_idempotent(env, monkeypatch):
    Factory, Session, uid, _ = env
    monkeypatch.setattr(dodo_usage, "included_reels", lambda row: 5)
    _plan(Session, uid)
    _grant(Session, uid, 1)
    jid, _ = _render(Session, uid)
    assert dodo_usage.record_render(jid, now=NOW, flush=False) is False
    assert len(_events(Factory)) == 1


# --------------------------------------------------------------------------- #
# Refund of an overage-funded failure
# --------------------------------------------------------------------------- #
def test_failed_overage_reel_leaves_no_free_credit(env, monkeypatch):
    Factory, Session, uid, _ = env
    monkeypatch.setattr(dodo_usage, "included_reels", lambda row: 0)
    _plan(Session, uid)
    _opt_in(Session, uid)
    jid, ok = _render(Session, uid, succeed=False)
    assert ok
    with Factory() as s:
        job = s.get(Job, jid)
        job.state = const.TASK_STATE_FAILED
        s.commit()
    assert refunds.refund_failed_reel_once(jid) == 0
    assert _balance(Factory, uid) == 0


def test_failed_pack_reel_is_still_refunded(env):
    Factory, Session, uid, _ = env
    _grant(Session, uid, 1)
    jid, _ = _render(Session, uid, succeed=False)
    with Factory() as s:
        s.get(Job, jid).state = const.TASK_STATE_FAILED
        s.commit()
    assert refunds.refund_failed_reel_once(jid) == 1
    assert _balance(Factory, uid) == 1


# --------------------------------------------------------------------------- #
# Flush
# --------------------------------------------------------------------------- #
def _queue(Session, uid, n, *, stamp=NOW):
    with Session() as s:
        for i in range(n):
            s.add(
                DodoUsageEvent(
                    event_id=f"reel_job{i}",
                    user_id=uid,
                    customer_id="cus_1",
                    event_name="reel.rendered",
                    timestamp=stamp,
                    meta={"plan_key": "creator"},
                )
            )


def test_flush_splits_into_batches_of_1000(env):
    Factory, Session, uid, fake = env
    _queue(Session, uid, 2001)
    counts = dodo_usage.flush_pending(now=NOW)
    assert counts["sent"] == 2001
    sizes = [len(c["body"]["events"]) for c in fake.calls]
    assert sizes == [1000, 1000, 1]
    assert all(c["path"] == "/events/ingest" for c in fake.calls)
    assert {e.status for e in _events(Factory)} == {"sent"}


@pytest.mark.parametrize("status", [500, 503, 429, 0])
def test_flush_retries_transient_errors(env, status):
    Factory, Session, uid, fake = env
    _queue(Session, uid, 1)
    fake.fail_with = [dodo_client.DodoError(status, "boom")]
    assert dodo_usage.flush_pending(now=NOW)["retry"] == 1
    row = _events(Factory)[0]
    assert row.status == "pending" and row.attempts == 1 and row.next_attempt_at is not None
    # Not due yet: nothing is sent.
    assert dodo_usage.flush_pending(now=NOW)["sent"] == 0
    later = NOW + timedelta(minutes=5)
    assert dodo_usage.flush_pending(now=later)["sent"] == 1


@pytest.mark.parametrize("status", [400, 401, 422])
def test_flush_marks_other_4xx_permanent(env, status):
    Factory, Session, uid, fake = env
    _queue(Session, uid, 1)
    fake.fail_with = [dodo_client.DodoError(status, "bad event")]
    assert dodo_usage.flush_pending(now=NOW)["failed"] == 1
    row = _events(Factory)[0]
    assert row.status == "failed_permanent"
    assert str(status) in row.last_error
    assert dodo_usage.flush_pending(now=NOW + timedelta(hours=1)) == {"sent": 0, "retry": 0, "failed": 0}


def test_flush_restamps_stale_events(env):
    Factory, Session, uid, fake = env
    _queue(Session, uid, 1, stamp=NOW - timedelta(hours=2))
    dodo_usage.flush_pending(now=NOW)
    event = fake.calls[0]["body"]["events"][0]
    assert event["timestamp"].startswith("2026-10-10T12:00")
    assert event["metadata"]["rendered_at"].startswith("2026-10-10T10:00")
    assert event["event_id"] == "reel_job0" and event["customer_id"] == "cus_1"


def test_flush_is_noop_without_dodo(env, monkeypatch):
    Factory, Session, uid, fake = env
    monkeypatch.setattr(dodo_client, "is_configured", lambda: False)
    _queue(Session, uid, 1)
    assert dodo_usage.flush_pending(now=NOW)["sent"] == 0
    assert fake.calls == []


def test_period_bounds_month_and_year():
    row = type("R", (), {"current_period_end": datetime(2026, 3, 31, tzinfo=timezone.utc), "interval": "month"})
    start, end = dodo_usage.period_bounds(row)
    assert start == datetime(2026, 2, 28, tzinfo=timezone.utc) and end.month == 3
    row.interval = "year"
    assert dodo_usage.period_bounds(row)[0].year == 2025
