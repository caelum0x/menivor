"""Unit tests for usage metering + overage (Billing Platform, Epic 3).

Runs against an in-memory SQLite DB built from the live ORM metadata. Covered
behaviour:

* :func:`metering.record_usage` inserts exactly one :class:`MeteredUsage` row per
  ``idempotency_key`` — a replay of the SAME key is a no-op (``created=False``)
  and never double-counts;
* distinct keys accumulate;
* :func:`metering.aggregate_usage` totals per metric, tenant-scoped;
* :func:`metering.overage_for` computes ``max(0, used - plan_limit)`` per metric,
  falling back to the base/free plan limit when the workspace has no LIVE
  subscription, and reports an unbounded metric with ``overage=0``.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.base import Base
from app.models.db.models import User, Workspace
from app.models.db.repositories import SubscriptionRepository
from app.services import metering

_PERIOD_NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)
_PERIOD_YM = "2026-08"


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )


@contextmanager
def _session(factory):
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _make_workspace(session, name: str = "Tenant") -> str:
    owner = User(email=f"{name}-owner@example.com")
    session.add(owner)
    session.flush()
    ws = Workspace(owner_id=owner.id, name=name)
    session.add(ws)
    session.flush()
    return ws.id


# --------------------------------------------------------------------------- #
# record_usage — idempotent, no double-count
# --------------------------------------------------------------------------- #
def test_record_usage_inserts_once(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s)
        result = metering.record_usage(
            s, ws, "render", 1, "render:job-1", now=_PERIOD_NOW
        )
        assert result.created is True
        assert result.metric == "render"
        assert result.period_ym == _PERIOD_YM
        assert metering.aggregate_usage(s, ws, _PERIOD_YM) == {"render": 1}


def test_duplicate_idempotency_key_does_not_double_count(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s)

        first = metering.record_usage(s, ws, "render", 5, "render:job-9", now=_PERIOD_NOW)
        # SAME key replayed -> counts nothing more.
        second = metering.record_usage(s, ws, "render", 5, "render:job-9", now=_PERIOD_NOW)

        assert first.created is True
        assert second.created is False  # replay inserted nothing
        # Total stays 5, not 10 — the metering event was counted exactly once.
        assert metering.aggregate_usage(s, ws, _PERIOD_YM) == {"render": 5}


def test_distinct_keys_accumulate(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s)
        metering.record_usage(s, ws, "render", 2, "render:a", now=_PERIOD_NOW)
        metering.record_usage(s, ws, "render", 3, "render:b", now=_PERIOD_NOW)
        metering.record_usage(s, ws, "api_call", 7, "api:c", now=_PERIOD_NOW)

        totals = metering.aggregate_usage(s, ws, _PERIOD_YM)
        assert totals == {"render": 5, "api_call": 7}


def test_aggregate_is_tenant_scoped(session_factory):
    with _session(session_factory) as s:
        ws_a = _make_workspace(s, "A")
        ws_b = _make_workspace(s, "B")
        metering.record_usage(s, ws_a, "render", 4, "render:a1", now=_PERIOD_NOW)
        metering.record_usage(s, ws_b, "render", 9, "render:b1", now=_PERIOD_NOW)

        assert metering.aggregate_usage(s, ws_a, _PERIOD_YM) == {"render": 4}
        assert metering.aggregate_usage(s, ws_b, _PERIOD_YM) == {"render": 9}


def test_record_usage_rejects_blank_inputs(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s)
        with pytest.raises(ValueError):
            metering.record_usage(s, "", "render", 1, "k", now=_PERIOD_NOW)
        with pytest.raises(ValueError):
            metering.record_usage(s, ws, "", 1, "k", now=_PERIOD_NOW)
        with pytest.raises(ValueError):
            metering.record_usage(s, ws, "render", 1, "", now=_PERIOD_NOW)


def test_negative_quantity_is_floored(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s)
        result = metering.record_usage(s, ws, "render", -5, "render:neg", now=_PERIOD_NOW)
        assert result.quantity == 0
        assert metering.aggregate_usage(s, ws, _PERIOD_YM) == {"render": 0}


# --------------------------------------------------------------------------- #
# overage_for — usage vs plan entitlement
# --------------------------------------------------------------------------- #
def test_overage_for_pro_plan(session_factory):
    """pro monthly_credits == 120; 150 renders -> 30 overage."""
    with _session(session_factory) as s:
        ws = _make_workspace(s, "pro")
        SubscriptionRepository(s).upsert(ws, plan_key="pro", status="active")
        metering.record_usage(s, ws, "render", 150, "render:big", now=_PERIOD_NOW)

        overages = metering.overage_for(s, ws, _PERIOD_YM)
        assert overages["render"].used == 150
        assert overages["render"].limit == 120
        assert overages["render"].overage == 30


def test_overage_for_free_plan_no_subscription(session_factory):
    """No subscription -> free plan (monthly_credits == 3); 5 renders -> 2 overage."""
    with _session(session_factory) as s:
        ws = _make_workspace(s, "free")
        metering.record_usage(s, ws, "render", 5, "render:free", now=_PERIOD_NOW)

        overages = metering.overage_for(s, ws, _PERIOD_YM)
        assert overages["render"].limit == 3  # base/free safe default
        assert overages["render"].overage == 2


def test_no_overage_within_allotment(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s, "pro")
        SubscriptionRepository(s).upsert(ws, plan_key="pro", status="active")
        metering.record_usage(s, ws, "render", 100, "render:ok", now=_PERIOD_NOW)

        overages = metering.overage_for(s, ws, _PERIOD_YM)
        assert overages["render"].overage == 0


def test_unbounded_metric_has_no_overage(session_factory):
    """A metric with no plan limit reports limit=None, overage=0."""
    with _session(session_factory) as s:
        ws = _make_workspace(s, "pro")
        SubscriptionRepository(s).upsert(ws, plan_key="pro", status="active")
        metering.record_usage(s, ws, "api_call", 9999, "api:x", now=_PERIOD_NOW)

        overages = metering.overage_for(s, ws, _PERIOD_YM)
        assert overages["api_call"].limit is None
        assert overages["api_call"].overage == 0
