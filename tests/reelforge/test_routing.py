"""Routing domain tests — selection/fallback policy + route resolution + usage.

Uses in-memory SQLite for the catalog reads and a test-local provider registry
with fake adapters (no network). Covers the pure admissibility/selection policy,
route resolution over a seeded catalog, adapter-registration gating, and usage
normalization/persistence.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.routing.base import (
    NormalizedUsage,
    ProviderAdapter,
    ProviderRegistry,
    ProviderRun,
    QuoteResult,
)
from app.domains.routing.policy import (
    FALLBACK_EQUIVALENT,
    FALLBACK_NONE,
    Candidate,
    RoutePolicy,
    is_admissible,
    select_route,
)
from app.domains.routing.service import RoutingError, RoutingService
from app.models.db.base import Base
from app.models.db.marketplace import (
    ModelCatalogEntry,
    PriceVersion,
    ProviderCatalog,
    UsageRecord,
    WalletAccount,
)


# --------------------------------------------------------------------------- #
# Fakes / fixtures
# --------------------------------------------------------------------------- #
class FakeAdapter:
    """A minimal in-memory ProviderAdapter for routing tests."""

    def __init__(self, provider_key: str) -> None:
        self._key = provider_key

    @property
    def provider_key(self) -> str:
        return self._key

    def catalog(self):
        return []

    def quote(self, request, price_version):
        return QuoteResult(max_cost_micros=0, expires_at=None)

    def submit(self, request, snapshot, correlation_id):
        return ProviderRun(provider_key=self._key, run_id="run-1")

    def poll(self, run):
        return run

    def cancel(self, run):
        return True

    def normalize_usage(self, payload: dict) -> NormalizedUsage:
        return NormalizedUsage(
            unit=payload.get("unit", "seconds"),
            quantity_units=int(payload.get("qty", 0)),
            cost_micros=int(payload.get("cost", 0)),
            raw=dict(payload),
        )


@pytest.fixture()
def factory():
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


def _seed_catalog(session) -> None:
    pixelle = ProviderCatalog(provider_key="pixelle", display_name="Pixelle", enabled=True)
    runway = ProviderCatalog(provider_key="runway", display_name="Runway", enabled=True)
    session.add_all([pixelle, runway])
    session.flush()

    entries = [
        # cheap primary, region us
        ModelCatalogEntry(
            model_id="pixelle/wan-i2v",
            provider_id=pixelle.id,
            capability="broll",
            metering_unit="seconds",
            region="us",
            availability_state="available",
            latency_band="fast",
            release_status="ga",
        ),
        # pricier equivalent, region eu
        ModelCatalogEntry(
            model_id="runway/gen",
            provider_id=runway.id,
            capability="broll",
            metering_unit="seconds",
            region="eu",
            availability_state="available",
            latency_band="standard",
            release_status="ga",
        ),
        # degraded (limited) equivalent, region us
        ModelCatalogEntry(
            model_id="pixelle/wan-limited",
            provider_id=pixelle.id,
            capability="broll",
            metering_unit="seconds",
            region="us",
            availability_state="limited",
            latency_band="slow",
            release_status="ga",
        ),
    ]
    session.add_all(entries)
    session.flush()

    prices = {
        "pixelle/wan-i2v": 100_000,   # 6s -> 600_000
        "runway/gen": 150_000,        # 6s -> 900_000
        "pixelle/wan-limited": 90_000,  # 6s -> 540_000
    }
    for entry in entries:
        session.add(
            PriceVersion(
                model_entry_id=entry.id,
                model_id=entry.model_id,
                unit="seconds",
                unit_price_micros=prices[entry.model_id],
                quote_rules={"default_units": 6},
                version=1,
            )
        )
    session.commit()


def _svc(session, *adapters: str) -> RoutingService:
    reg = ProviderRegistry()
    for key in adapters:
        reg.register(FakeAdapter(key))
    return RoutingService(session, provider_registry=reg)


# --------------------------------------------------------------------------- #
# Pure policy
# --------------------------------------------------------------------------- #
def test_protocol_runtime_checkable():
    assert isinstance(FakeAdapter("x"), ProviderAdapter)


def test_is_admissible_rules():
    base = Candidate(
        model_id="m", provider_key="p", capability="broll", est_cost_micros=600_000,
        region="us", availability_state="available",
    )
    assert is_admissible(base, RoutePolicy())
    # region constraint
    assert not is_admissible(base, RoutePolicy(allowed_regions=frozenset({"eu"})))
    assert is_admissible(base, RoutePolicy(allowed_regions=frozenset({"us"})))
    # cost cap
    assert not is_admissible(base, RoutePolicy(max_cost_micros=500_000))
    # limited requires allow_degraded
    limited = Candidate(
        model_id="m2", provider_key="p", capability="broll", est_cost_micros=1,
        availability_state="limited",
    )
    assert not is_admissible(limited, RoutePolicy())
    assert is_admissible(limited, RoutePolicy(allow_degraded=True))


def test_select_route_none_vs_equivalent():
    cands = [
        Candidate("a", "pa", "broll", 600_000, region="us"),
        Candidate("b", "pb", "broll", 900_000, region="eu"),
        Candidate("c", "pc", "image", 100_000),  # different capability
    ]
    # none -> just primary
    assert [c.model_id for c in select_route("a", cands, RoutePolicy(FALLBACK_NONE))] == ["a"]
    # equivalent -> primary + same-capability alt (image excluded)
    route = select_route("a", cands, RoutePolicy(FALLBACK_EQUIVALENT))
    assert [c.model_id for c in route] == ["a", "b"]


def test_select_route_unknown_primary_is_empty():
    cands = [Candidate("a", "pa", "broll", 600_000)]
    assert select_route("ghost", cands, RoutePolicy(FALLBACK_EQUIVALENT)) == []


# --------------------------------------------------------------------------- #
# Route resolution over the catalog
# --------------------------------------------------------------------------- #
def test_resolve_route_no_fallback(factory):
    with factory() as s:
        _seed_catalog(s)
    with factory() as s:
        route = _svc(s, "pixelle").resolve_route(
            capability="broll", model_id="pixelle/wan-i2v"
        )
        assert route.primary.model_id == "pixelle/wan-i2v"
        assert route.fallbacks == []
        assert route.primary.est_cost_micros == 600_000


def test_resolve_route_equivalent_fallback_ordered(factory):
    with factory() as s:
        _seed_catalog(s)
    with factory() as s:
        route = _svc(s, "pixelle", "runway").resolve_route(
            capability="broll",
            model_id="pixelle/wan-i2v",
            policy=RoutePolicy(fallback=FALLBACK_EQUIVALENT),
        )
        # primary first, then the available equivalent (runway); limited excluded.
        assert [c.model_id for c in route.order] == ["pixelle/wan-i2v", "runway/gen"]


def test_resolve_route_cap_filters_fallback(factory):
    with factory() as s:
        _seed_catalog(s)
    with factory() as s:
        route = _svc(s, "pixelle", "runway").resolve_route(
            capability="broll",
            model_id="pixelle/wan-i2v",
            policy=RoutePolicy(fallback=FALLBACK_EQUIVALENT, max_cost_micros=700_000),
        )
        # runway (900k) exceeds the cap -> dropped; only the primary remains.
        assert [c.model_id for c in route.order] == ["pixelle/wan-i2v"]


def test_resolve_route_unknown_model_raises(factory):
    with factory() as s:
        _seed_catalog(s)
    with factory() as s:
        with pytest.raises(RoutingError) as ei:
            _svc(s, "pixelle").resolve_route(
                capability="broll", model_id="pixelle/ghost"
            )
        assert ei.value.status_code == 422


def test_resolve_route_primary_without_adapter_raises(factory):
    with factory() as s:
        _seed_catalog(s)
    with factory() as s:
        # Register only runway; the primary pixelle has no adapter.
        with pytest.raises(RoutingError):
            _svc(s, "runway").resolve_route(
                capability="broll", model_id="pixelle/wan-i2v"
            )


def test_resolve_route_drops_fallback_without_adapter(factory):
    with factory() as s:
        _seed_catalog(s)
    with factory() as s:
        # Only pixelle has an adapter; runway fallback is dropped, primary stays.
        route = _svc(s, "pixelle").resolve_route(
            capability="broll",
            model_id="pixelle/wan-i2v",
            policy=RoutePolicy(fallback=FALLBACK_EQUIVALENT),
        )
        assert [c.model_id for c in route.order] == ["pixelle/wan-i2v"]


def test_estimated_quantity_overrides_default(factory):
    with factory() as s:
        _seed_catalog(s)
    with factory() as s:
        route = _svc(s, "pixelle").resolve_route(
            capability="broll", model_id="pixelle/wan-i2v", estimated_quantity=10
        )
        assert route.primary.est_cost_micros == 1_000_000  # 100_000 * 10


# --------------------------------------------------------------------------- #
# Usage normalization + persistence
# --------------------------------------------------------------------------- #
def test_persist_usage_writes_record(factory):
    with factory() as s:
        acct = WalletAccount(user_id=None, workspace_id=None)
        s.add(acct)
        s.flush()
        account_id = acct.id
        svc = RoutingService(s, provider_registry=ProviderRegistry())
        normalized = FakeAdapter("pixelle").normalize_usage(
            {"unit": "seconds", "qty": 6, "cost": 600_000, "extra": "x"}
        )
        rec = svc.persist_usage(
            normalized=normalized,
            job_id=None,
            account_id=account_id,
            stage="broll",
            model_id="pixelle/wan-i2v",
            provider_key="pixelle",
            price_version_id="pv1",
            correlation_id="corr-1",
        )
        s.commit()
        loaded = s.get(UsageRecord, rec.id)
        assert loaded.cost_micros == 600_000
        assert loaded.quantity_units == 6
        assert loaded.unit == "seconds"
        assert loaded.provider_key == "pixelle"
        assert loaded.raw_usage["extra"] == "x"
