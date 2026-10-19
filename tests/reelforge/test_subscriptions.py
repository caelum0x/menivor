"""Unit tests for the subscription lifecycle + IDEMPOTENT webhook (Billing, Epic 3).

The #1 invariant under test is money-correctness: a redelivered subscription
webhook must grant the workspace's monthly credits + entitlements EXACTLY once.

Runs against a REAL in-memory SQLite DB (so the shared idempotent workspace-pool
grant in :mod:`app.services.billing.service` runs for real), with ``get_session``
pointed at that DB and Redis faked (``SETNX`` semantics). Covered behaviour:

* a ``customer.subscription.created`` webhook activates the subscription row and
  funds the workspace pool once; a REPLAY of the same event grants nothing more;
* :func:`subscriptions.change_plan` swaps the plan (DB-authoritative);
* :func:`subscriptions.cancel_subscription` flips status to ``canceled`` so the
  entitlement gate falls back to the base/free plan.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.base import Base
from app.models.db.models import User, Workspace
from app.models.db.repositories import CreditRepository, SubscriptionRepository
from app.services import entitlements, subscriptions


# --------------------------------------------------------------------------- #
# Fake Redis (SETNX semantics) — shared with the billing service under test
# --------------------------------------------------------------------------- #
class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_calls = 0

    def set(self, name, value="1", nx=False, ex=None):
        self.set_calls += 1
        if nx and name in self.store:
            return None  # key already claimed -> duplicate
        self.store[name] = value
        return True

    def delete(self, name):
        self.store.pop(name, None)


# --------------------------------------------------------------------------- #
# Fixture: real SQLite + patched get_session + fake Redis
# --------------------------------------------------------------------------- #
@pytest.fixture()
def billing_env(monkeypatch):
    import app.models.db.base as db_base
    from app.services.billing import service as billing_service

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )

    @contextmanager
    def _fake_get_session():
        session = Factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(db_base, "get_session", _fake_get_session)
    fake_redis = _FakeRedis()
    monkeypatch.setattr(billing_service, "_get_redis", lambda: fake_redis)

    # Seed a workspace + acting admin.
    with _fake_get_session() as s:
        admin = User(email="admin@example.com")
        s.add(admin)
        s.flush()
        ws = Workspace(owner_id=admin.id, name="Acme")
        s.add(ws)
        s.flush()
        ws_id, admin_id = ws.id, admin.id

    return Factory, ws_id, admin_id, fake_redis


def _sub_event(event_id: str, ws_id: str, admin_id: str, plan_key: str = "pro",
               status: str = "active", etype: str = "customer.subscription.created",
               period: object = None):
    return {
        "id": event_id,
        "type": etype,
        "data": {
            "object": {
                "id": "sub_123",
                "status": status,
                "current_period_end": period,
                "metadata": {
                    "workspace_id": ws_id,
                    "plan_key": plan_key,
                    "user_id": admin_id,
                },
            }
        },
    }


def _workspace_balance(Factory, ws_id: str) -> int:
    with Factory() as s:
        return CreditRepository(s).workspace_balance(ws_id)


def _subscription(Factory, ws_id: str):
    with Factory() as s:
        row = SubscriptionRepository(s).get_for_workspace(ws_id)
        # Detach a plain snapshot so the closed session doesn't expire attrs.
        if row is None:
            return None
        return {"plan_key": row.plan_key, "status": row.status,
                "provider_ref": row.provider_ref, "seats": row.seats}


# --------------------------------------------------------------------------- #
# Webhook — activates subscription + funds pool once (IDEMPOTENT)
# --------------------------------------------------------------------------- #
def test_webhook_activates_and_funds_pool_once(billing_env):
    Factory, ws_id, admin_id, _ = billing_env

    result = subscriptions.process_subscription_event(
        _sub_event("evt_1", ws_id, admin_id, plan_key="pro")
    )

    assert result["status"] == "active"
    assert result["granted"] is True
    assert result["credits"] == 120  # pro monthly allotment
    # The workspace shared pool was funded exactly once.
    assert _workspace_balance(Factory, ws_id) == 120
    sub = _subscription(Factory, ws_id)
    assert sub == {"plan_key": "pro", "status": "active",
                   "provider_ref": "sub_123", "seats": 1}


def test_webhook_is_idempotent_on_duplicate_event(billing_env):
    """The SAME provider event id grants the monthly credits at most once."""
    Factory, ws_id, admin_id, fake_redis = billing_env
    event = _sub_event("evt_dup", ws_id, admin_id, plan_key="pro")

    subscriptions.process_subscription_event(event)
    subscriptions.process_subscription_event(event)  # replay

    # Funded once despite two deliveries.
    assert _workspace_balance(Factory, ws_id) == 120
    assert fake_redis.set_calls == 2  # SETNX attempted on both deliveries


def test_webhook_distinct_periods_grant_each_period(billing_env):
    """Distinct billing PERIODS (monthly renewals) each grant once."""
    Factory, ws_id, admin_id, _ = billing_env

    subscriptions.process_subscription_event(
        _sub_event("evt_m1", ws_id, admin_id, period=datetime(2026, 1, 31))
    )
    subscriptions.process_subscription_event(
        _sub_event("evt_m2", ws_id, admin_id, period=datetime(2026, 2, 28))
    )

    assert _workspace_balance(Factory, ws_id) == 240  # two monthly grants


def test_webhook_overlapping_events_one_period_grant_once(billing_env):
    """The #1 invariant: the several DISTINCT events Stripe emits for a SINGLE
    period (created + repeated updated + invoice.payment_succeeded), each with its
    own unique event id, together grant the monthly allotment EXACTLY once — a
    customer toggling billing-portal settings can never mint free credits."""
    Factory, ws_id, admin_id, _ = billing_env

    # Same period, same subscription, distinct event ids and distinct
    # (overlapping) event types.
    period = datetime(2026, 3, 31)
    subscriptions.process_subscription_event(
        _sub_event("evt_created", ws_id, admin_id, period=period,
                   etype="customer.subscription.created")
    )
    subscriptions.process_subscription_event(
        _sub_event("evt_invoice", ws_id, admin_id, period=period,
                   etype="invoice.payment_succeeded")
    )
    subscriptions.process_subscription_event(
        _sub_event("evt_update_1", ws_id, admin_id, period=period,
                   etype="customer.subscription.updated")
    )
    subscriptions.process_subscription_event(
        _sub_event("evt_update_2", ws_id, admin_id, period=period,
                   etype="customer.subscription.updated")
    )

    # Funded ONCE for the period despite four distinct events.
    assert _workspace_balance(Factory, ws_id) == 120


def test_webhook_cancel_event_flips_status_no_grant(billing_env):
    Factory, ws_id, admin_id, _ = billing_env
    # Activate first.
    subscriptions.process_subscription_event(_sub_event("evt_a", ws_id, admin_id))
    assert _workspace_balance(Factory, ws_id) == 120

    # Then a cancellation event: status -> canceled, no additional grant.
    result = subscriptions.process_subscription_event(
        _sub_event("evt_cancel", ws_id, admin_id,
                   etype="customer.subscription.deleted", status="canceled")
    )
    assert result["status"] == "canceled"
    assert result["granted"] is False
    assert _workspace_balance(Factory, ws_id) == 120  # unchanged
    assert _subscription(Factory, ws_id)["status"] == "canceled"


def test_webhook_past_due_update_does_not_grant(billing_env):
    Factory, ws_id, admin_id, _ = billing_env
    result = subscriptions.process_subscription_event(
        _sub_event("evt_pd", ws_id, admin_id,
                   etype="customer.subscription.updated", status="past_due")
    )
    assert result["status"] == "past_due"
    assert result["granted"] is False
    assert _workspace_balance(Factory, ws_id) == 0


def test_webhook_ignores_unrelated_event(billing_env):
    Factory, ws_id, admin_id, _ = billing_env
    result = subscriptions.process_subscription_event(
        {"id": "evt_x", "type": "ping", "data": {"object": {}}}
    )
    assert result is None


def test_handle_subscription_webhook_verifies_then_processes(billing_env, monkeypatch):
    """End-to-end through the verification seam (signature check monkeypatched)."""
    Factory, ws_id, admin_id, _ = billing_env
    from app.services.billing import stripe_client

    event = _sub_event("evt_hook", ws_id, admin_id, plan_key="pro")
    monkeypatch.setattr(
        stripe_client, "verify_and_parse_webhook", lambda payload, sig: event
    )

    first = subscriptions.handle_subscription_webhook(b"{}", "sig")
    second = subscriptions.handle_subscription_webhook(b"{}", "sig")  # replay

    assert first["credits"] == 120
    assert second is not None
    assert _workspace_balance(Factory, ws_id) == 120  # granted once


# --------------------------------------------------------------------------- #
# change_plan / cancel (RBAC billing.manage gated at the API layer)
# --------------------------------------------------------------------------- #
@pytest.fixture
def provider_calls(monkeypatch):
    """Record provider-side plan switches / cancels (no live Stripe call)."""
    from app.services.billing import subscription_providers

    calls: list[tuple] = []
    monkeypatch.setattr(
        subscription_providers, "change_plan",
        lambda provider, ref, **kw: calls.append(("change_plan", provider, ref, kw["plan"].key)),
    )
    monkeypatch.setattr(
        subscription_providers, "cancel",
        lambda provider, ref: calls.append(("cancel", provider, ref)),
    )
    return calls


def test_change_plan_switches_between_paid_tiers_when_provider_backed(billing_env, provider_calls):
    """A tenant with a LIVE, provider-backed subscription may switch paid tiers.
    The provider subscription moves first, then the local row."""
    Factory, ws_id, admin_id, _ = billing_env
    with Factory() as s:
        SubscriptionRepository(s).upsert(
            ws_id, plan_key="starter", provider="stripe",
            provider_ref="sub_live", status="active",
        )
        s.commit()

    with Factory() as s:
        row = subscriptions.change_plan(
            s, workspace_id=ws_id, plan_key="pro", actor_user_id=admin_id
        )
        assert row.plan_key == "pro"
        s.commit()

    assert _subscription(Factory, ws_id)["plan_key"] == "pro"
    assert provider_calls == [("change_plan", "stripe", "sub_live", "pro")]


def test_change_plan_leaves_row_untouched_when_provider_fails(billing_env, monkeypatch):
    from app.services.billing import subscription_providers

    Factory, ws_id, admin_id, _ = billing_env
    with Factory() as s:
        SubscriptionRepository(s).upsert(
            ws_id, plan_key="starter", provider="stripe",
            provider_ref="sub_live", status="active",
        )
        s.commit()

    def _fail(*_a, **_k):
        raise RuntimeError("stripe unavailable")

    monkeypatch.setattr(subscription_providers, "change_plan", _fail)
    with Factory() as s:
        with pytest.raises(RuntimeError):
            subscriptions.change_plan(
                s, workspace_id=ws_id, plan_key="pro", actor_user_id=admin_id
            )
    assert _subscription(Factory, ws_id)["plan_key"] == "starter"


def test_change_plan_rejects_paid_upgrade_without_subscription(billing_env):
    """Entitlement-bypass guard: free-tier tenant cannot self-upgrade to a paid
    plan (no verified Stripe subscription) — must go through checkout instead."""
    Factory, ws_id, admin_id, _ = billing_env
    with Factory() as s:
        with pytest.raises(PermissionError):
            subscriptions.change_plan(
                s, workspace_id=ws_id, plan_key="enterprise", actor_user_id=admin_id
            )
    # Nothing was written / no entitlement was granted.
    assert _subscription(Factory, ws_id) is None


def test_change_plan_rejects_paid_when_subscription_not_provider_backed(billing_env):
    """A row that is 'active' but has NO provider_ref (never confirmed by Stripe)
    does not satisfy the paid-tier guard."""
    Factory, ws_id, admin_id, _ = billing_env
    with Factory() as s:
        SubscriptionRepository(s).upsert(ws_id, plan_key="free", status="active")
        s.commit()
    with Factory() as s:
        with pytest.raises(PermissionError):
            subscriptions.change_plan(
                s, workspace_id=ws_id, plan_key="pro", actor_user_id=admin_id
            )


def test_change_plan_downgrade_to_free_always_allowed(billing_env, provider_calls):
    """Downgrading to Free is always allowed; a live paid subscription is
    canceled at the provider first so no further charges happen."""
    Factory, ws_id, admin_id, _ = billing_env
    with Factory() as s:
        SubscriptionRepository(s).upsert(
            ws_id, plan_key="pro", provider="stripe",
            provider_ref="sub_live", status="active",
        )
        s.commit()
    with Factory() as s:
        row = subscriptions.change_plan(
            s, workspace_id=ws_id, plan_key="free", actor_user_id=admin_id
        )
        assert row.plan_key == "free"
        s.commit()
    assert _subscription(Factory, ws_id)["plan_key"] == "free"
    assert provider_calls == [("cancel", "stripe", "sub_live")]


def test_change_plan_rejects_unknown_plan(billing_env):
    Factory, ws_id, admin_id, _ = billing_env
    with Factory() as s:
        with pytest.raises(ValueError):
            subscriptions.change_plan(s, workspace_id=ws_id, plan_key="galaxy")


def test_cancel_subscription_falls_back_to_free(billing_env):
    Factory, ws_id, admin_id, _ = billing_env
    with Factory() as s:
        SubscriptionRepository(s).upsert(ws_id, plan_key="pro", status="active")
        s.commit()

    with Factory() as s:
        row = subscriptions.cancel_subscription(
            s, workspace_id=ws_id, actor_user_id=admin_id
        )
        assert row.status == "canceled"
        s.commit()

    # Entitlement gate now falls back to the base/free plan.
    with Factory() as s:
        assert entitlements.active_plan_key(s, ws_id) == "free"
        assert entitlements.is_entitled(s, ws_id, entitlements.FEAT_PRIORITY_RENDER) is False


def test_cancel_missing_subscription_returns_none(billing_env):
    Factory, ws_id, admin_id, _ = billing_env
    with Factory() as s:
        assert subscriptions.cancel_subscription(s, workspace_id=ws_id) is None
