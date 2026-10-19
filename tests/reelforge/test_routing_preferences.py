"""OpenRouter-style routing preferences — provider order, sort, latency, variants."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.catalog.seed_data import seed_default_catalog
from app.domains.routing.base import ProviderRegistry
from app.domains.routing.policy import (
    FALLBACK_EQUIVALENT,
    SORT_LATENCY,
    SORT_PRICE,
    Candidate,
    RoutePolicy,
    resolve_variant,
    select_route,
)
from app.domains.routing.service import RoutingService
from app.models.db.base import Base


def _c(mid, provider, cost, latency="standard", cap="broll"):
    return Candidate(
        model_id=mid, provider_key=provider, capability=cap,
        est_cost_micros=cost, latency_band=latency, availability_state="available",
    )


# --------------------------------------------------------------------------- #
# Pure selection preferences
# --------------------------------------------------------------------------- #
def test_sort_price_orders_cheapest_first():
    cands = [_c("a", "pa", 900), _c("b", "pb", 500), _c("c", "pc", 700)]
    route = select_route("a", cands, RoutePolicy(fallback=FALLBACK_EQUIVALENT, sort=SORT_PRICE))
    # primary 'a' first (partition by model), then cheapest fallbacks.
    assert [c.model_id for c in route] == ["a", "b", "c"]


def test_sort_latency_orders_fastest_first():
    cands = [
        _c("a", "pa", 900, latency="slow"),
        _c("b", "pb", 900, latency="fast"),
        _c("c", "pc", 900, latency="standard"),
    ]
    route = select_route("a", cands, RoutePolicy(fallback=FALLBACK_EQUIVALENT, sort=SORT_LATENCY))
    assert [c.model_id for c in route] == ["a", "b", "c"]


def test_provider_order_preference_wins():
    cands = [_c("a", "pa", 900), _c("b", "cheap", 100), _c("c", "preferred", 800)]
    route = select_route(
        "a", cands,
        RoutePolicy(fallback=FALLBACK_EQUIVALENT, provider_order=("preferred",)),
    )
    # 'preferred' provider is tried before the cheaper 'cheap' one.
    assert [c.model_id for c in route] == ["a", "c", "b"]


def test_max_latency_band_is_soft_not_exclusion():
    cands = [
        _c("a", "pa", 900, latency="fast"),
        _c("slowcheap", "pb", 100, latency="slow"),
        _c("faststd", "pc", 500, latency="fast"),
    ]
    route = select_route(
        "a", cands,
        RoutePolicy(fallback=FALLBACK_EQUIVALENT, max_latency_band="fast"),
    )
    # slow candidate is deprioritized (last) but NOT excluded.
    assert route[-1].model_id == "slowcheap"
    assert "slowcheap" in [c.model_id for c in route]


def test_hard_cost_cap_still_excludes():
    cands = [_c("a", "pa", 500), _c("b", "pb", 900)]
    route = select_route(
        "a", cands,
        RoutePolicy(fallback=FALLBACK_EQUIVALENT, max_cost_micros=600),
    )
    assert [c.model_id for c in route] == ["a"]  # 'b' over cap -> excluded


def test_resolve_variant():
    assert resolve_variant("pixelle/wan-i2v:nitro") == ("pixelle/wan-i2v", SORT_LATENCY)
    assert resolve_variant("pixelle/wan-i2v:floor") == ("pixelle/wan-i2v", SORT_PRICE)
    assert resolve_variant("pixelle/wan-i2v") == ("pixelle/wan-i2v", None)


# --------------------------------------------------------------------------- #
# Service: variant suffix drives sort + equivalent fallback over the catalog
# --------------------------------------------------------------------------- #
@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def test_floor_variant_resolves_cheapest_route(factory):
    with factory() as s:
        # Promote three broll models with different prices.
        seed_default_catalog(
            s, live_models={"kling/v1", "pixelle/wan-i2v", "runway/gen-3"}
        )
        s.commit()
    with factory() as s:
        # Assert selection order via a registry that has all three adapters.
        reg = ProviderRegistry()
        from tests.reelforge.test_routing_execution import ProgAdapter  # reuse fake

        for pk in ("kling", "pixelle", "runway"):
            reg.register(ProgAdapter(pk, poll_to_complete=0))
        resolved = RoutingService(s, provider_registry=reg).resolve_route(
            capability="broll", model_id="runway/gen-3:floor"
        )
        # runway is primary (kept first); the cheapest fallback (kling 35k/s) beats
        # pixelle (40k/s).
        order = [c.model_id for c in resolved.order]
        assert order[0] == "runway/gen-3"
        assert order.index("kling/v1") < order.index("pixelle/wan-i2v")
