"""Unit tests for plan-based entitlement resolution (Billing Platform, Epic 3).

Runs against an in-memory SQLite DB built from the live ORM metadata. Covered
behaviour:

* :data:`PLAN_ENTITLEMENTS` exposes the locked per-plan entitlement bundles and
  the pure :func:`entitlements.resolve` maps plan -> feature value;
* :func:`entitlements.is_entitled` resolves a workspace's LIVE subscription plan
  through OpenFeature (in-process provider) — pro/enterprise grant their extras;
* **default-deny without a subscription** — a workspace with no subscription (or a
  lapsed / canceled one) falls back to the base/free plan, so a premium extra is
  never granted;
* **OpenFeature-absent safe default** — with the SDK path disabled the layer
  degrades to a direct map read with the SAME base/free safe default, and an
  unknown feature is still denied.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.base import Base
from app.models.db.models import User, Workspace
from app.models.db.repositories import SubscriptionRepository
from app.services import entitlements


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


def _subscribe(session, workspace_id: str, plan_key: str, status: str = "active"):
    return SubscriptionRepository(session).upsert(
        workspace_id, plan_key=plan_key, status=status
    )


# --------------------------------------------------------------------------- #
# The dependency is really available (task: "confirm import openfeature works")
# --------------------------------------------------------------------------- #
def test_openfeature_dependency_is_importable():
    import openfeature  # noqa: F401
    from openfeature import api  # noqa: F401

    assert entitlements._OPENFEATURE_AVAILABLE is True


# --------------------------------------------------------------------------- #
# PLAN_ENTITLEMENTS + pure resolve
# --------------------------------------------------------------------------- #
def test_plan_entitlements_map_locked_values():
    m = entitlements.PLAN_ENTITLEMENTS
    assert set(m) == {"free", "starter", "pro", "enterprise"}
    # Monthly credits mirror the locked billing plan credits.
    assert m["free"][entitlements.FEAT_MONTHLY_CREDITS] == 3
    assert m["starter"][entitlements.FEAT_MONTHLY_CREDITS] == 30
    assert m["pro"][entitlements.FEAT_MONTHLY_CREDITS] == 120
    # SSO is an enterprise-only capability.
    assert m["free"][entitlements.FEAT_SSO] is False
    assert m["pro"][entitlements.FEAT_SSO] is False
    assert m["enterprise"][entitlements.FEAT_SSO] is True
    # max_variants grows with the plan.
    assert m["free"][entitlements.FEAT_MAX_VARIANTS] == 1
    assert m["pro"][entitlements.FEAT_MAX_VARIANTS] == 6


def test_resolve_plan_to_feature_value():
    assert entitlements.resolve("pro", entitlements.FEAT_PRIORITY_RENDER) is True
    assert entitlements.resolve("free", entitlements.FEAT_PRIORITY_RENDER) is False
    assert entitlements.resolve("enterprise", entitlements.FEAT_SEATS) == 100


def test_resolve_unknown_plan_falls_back_to_free():
    # Unknown plan -> base/free value (default-deny extras).
    assert entitlements.resolve("galaxy", entitlements.FEAT_SSO) is False
    assert entitlements.resolve("galaxy", entitlements.FEAT_MAX_VARIANTS) == 1


def test_resolve_unknown_feature_returns_supplied_default():
    assert entitlements.resolve("pro", "does_not_exist", "DEF") == "DEF"
    assert entitlements.resolve("pro", "does_not_exist") is None


def test_plan_entitlements_unknown_plan_is_free_copy():
    bundle = entitlements.plan_entitlements("nope")
    assert bundle[entitlements.FEAT_SSO] is False
    assert bundle[entitlements.FEAT_MONTHLY_CREDITS] == 3
    # A plain, mutable copy — mutating it must not corrupt the frozen map.
    bundle[entitlements.FEAT_SSO] = True
    assert entitlements.PLAN_ENTITLEMENTS["free"][entitlements.FEAT_SSO] is False


# --------------------------------------------------------------------------- #
# is_entitled — subscription-aware resolution via OpenFeature
# --------------------------------------------------------------------------- #
def test_is_entitled_grants_active_plan_extras(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s, "pro-team")
        _subscribe(s, ws, "pro", status="active")

        assert entitlements.is_entitled(s, ws, entitlements.FEAT_PRIORITY_RENDER) is True
        assert entitlements.is_entitled(s, ws, entitlements.FEAT_API_ACCESS) is True
        # pro does not include SSO -> denied.
        assert entitlements.is_entitled(s, ws, entitlements.FEAT_SSO) is False


def test_is_entitled_enterprise_grants_sso(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s, "ent-team")
        _subscribe(s, ws, "enterprise", status="active")
        assert entitlements.is_entitled(s, ws, entitlements.FEAT_SSO) is True


def test_entitlement_value_returns_numeric_limit(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s, "pro-team")
        _subscribe(s, ws, "pro", status="active")
        assert (
            entitlements.entitlement_value(s, ws, entitlements.FEAT_MAX_VARIANTS)
            == 6
        )


def test_default_deny_without_subscription(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s, "free-team")  # no subscription at all

        assert entitlements.active_plan_key(s, ws) == "free"
        assert entitlements.is_entitled(s, ws, entitlements.FEAT_SSO) is False
        assert entitlements.is_entitled(s, ws, entitlements.FEAT_API_ACCESS) is False
        assert (
            entitlements.entitlement_value(s, ws, entitlements.FEAT_MAX_VARIANTS)
            == 1
        )


def test_lapsed_subscription_falls_back_to_free(session_factory):
    """A past_due / canceled subscription must not keep granting premium extras."""
    with _session(session_factory) as s:
        ws = _make_workspace(s, "lapsed-team")
        _subscribe(s, ws, "enterprise", status="past_due")
        assert entitlements.active_plan_key(s, ws) == "free"
        assert entitlements.is_entitled(s, ws, entitlements.FEAT_SSO) is False

        _subscribe(s, ws, "enterprise", status="canceled")
        assert entitlements.is_entitled(s, ws, entitlements.FEAT_SSO) is False


def test_trialing_subscription_is_live(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s, "trial-team")
        _subscribe(s, ws, "pro", status="trialing")
        assert entitlements.active_plan_key(s, ws) == "pro"
        assert entitlements.is_entitled(s, ws, entitlements.FEAT_PRIORITY_RENDER) is True


# --------------------------------------------------------------------------- #
# OpenFeature-absent safe default (degrades to the direct map, same fallback)
# --------------------------------------------------------------------------- #
def test_openfeature_absent_degrades_to_safe_default(session_factory, monkeypatch):
    """With the SDK path disabled the layer still resolves per-plan and still
    denies an unknown feature (base/free safe default) — no bypass, no crash.
    """
    # Simulate the SDK being unavailable: force resolution down the direct-map
    # fallback path exactly as the import guard does when openfeature is absent.
    monkeypatch.setattr(
        entitlements,
        "_sdk_resolve",
        lambda plan_key, feature, default: entitlements.resolve(
            plan_key, feature, default
        ),
    )

    with _session(session_factory) as s:
        ws_pro = _make_workspace(s, "pro-noSDK")
        _subscribe(s, ws_pro, "pro", status="active")
        ws_free = _make_workspace(s, "free-noSDK")  # no subscription

        # Per-plan resolution still works without the SDK.
        assert entitlements.is_entitled(s, ws_pro, entitlements.FEAT_PRIORITY_RENDER) is True
        # Safe default (base/free) for a workspace with no subscription.
        assert entitlements.is_entitled(s, ws_free, entitlements.FEAT_SSO) is False
        # Unknown feature is default-denied even without the SDK.
        assert entitlements.is_entitled(s, ws_pro, "totally_unknown_feature") is False


def test_sdk_resolution_failure_degrades_to_map(session_factory, monkeypatch):
    """A live OpenFeature failure must not lose the decision (falls back to map)."""
    if not entitlements._OPENFEATURE_AVAILABLE:  # pragma: no cover - SDK present in CI
        pytest.skip("OpenFeature not installed")

    class _BoomClient:
        def get_boolean_value(self, *a, **k):
            raise RuntimeError("provider exploded")

        def get_integer_value(self, *a, **k):
            raise RuntimeError("provider exploded")

    monkeypatch.setattr(entitlements._of_api, "get_client", lambda *a, **k: _BoomClient())

    with _session(session_factory) as s:
        ws = _make_workspace(s, "boom-team")
        _subscribe(s, ws, "pro", status="active")
        # Falls back to the direct map -> still correct.
        assert entitlements.is_entitled(s, ws, entitlements.FEAT_PRIORITY_RENDER) is True
