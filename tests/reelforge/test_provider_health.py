"""Provider health — events/summary/state, health-weighted routing, endpoint."""

from __future__ import annotations

import importlib
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.domains.catalog.health import ProviderHealthService
from app.domains.catalog.seed_data import seed_default_catalog
from app.domains.routing.base import ProviderRegistry
from app.domains.routing.policy import (
    FALLBACK_EQUIVALENT,
    Candidate,
    RoutePolicy,
    select_route,
)
from app.domains.routing.service import RoutingService
from app.models.db.base import Base
from app.models.db.marketplace import ProviderCatalog
from app.utils import utils
from app.models.exception import HttpException

catalog_mod = importlib.import_module("app.domains.catalog.router")


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


# --------------------------------------------------------------------------- #
# Service: record -> summary -> state
# --------------------------------------------------------------------------- #
def _record(factory, provider, oks, fails, latency=100):
    with factory() as s:
        h = ProviderHealthService(s)
        for _ in range(oks):
            h.record(provider, ok=True, latency_ms=latency)
        for _ in range(fails):
            h.record(provider, ok=False, latency_ms=latency)
        s.commit()


def test_summary_states(factory):
    _record(factory, "healthy", 19, 1)   # 95% -> healthy
    _record(factory, "degraded", 8, 2)   # 80% -> degraded
    _record(factory, "down", 5, 5)       # 50% -> down
    _record(factory, "few", 1, 0)        # <3 samples -> unknown
    with factory() as s:
        h = ProviderHealthService(s)
        assert h.summary("healthy")["state"] == "healthy"
        assert h.summary("healthy")["avg_latency_ms"] == 100
        assert h.summary("degraded")["state"] == "degraded"
        assert h.summary("down")["state"] == "down"
        assert h.summary("few")["state"] == "unknown"
        assert h.summary("never-seen")["samples"] == 0


def test_refresh_state_persists(factory):
    with factory() as s:
        seed_default_catalog(s)
        s.commit()
    _record(factory, "pixelle", 0, 5)  # all failures -> down
    with factory() as s:
        state = ProviderHealthService(s).refresh_state("pixelle")
        s.commit()
    assert state == "down"
    with factory() as s:
        provider = s.query(ProviderCatalog).filter(ProviderCatalog.provider_key == "pixelle").first()
        assert provider.health_state == "down"


def test_status_lists_observed_providers(factory):
    _record(factory, "a", 3, 0)
    _record(factory, "b", 3, 0)
    with factory() as s:
        rows = ProviderHealthService(s).status()
    assert {r["provider_key"] for r in rows} == {"a", "b"}


# --------------------------------------------------------------------------- #
# Routing: health deprioritizes unstable providers (soft)
# --------------------------------------------------------------------------- #
def _c(mid, provider, cost, health="unknown"):
    return Candidate(
        model_id=mid, provider_key=provider, capability="broll",
        est_cost_micros=cost, health_state=health, availability_state="available",
    )


def test_down_provider_is_deprioritized_not_excluded():
    cands = [
        _c("a", "pa", 900, "healthy"),
        _c("cheapdown", "pb", 100, "down"),   # cheapest but unhealthy
        _c("healthymid", "pc", 500, "healthy"),
    ]
    route = select_route("a", cands, RoutePolicy(fallback=FALLBACK_EQUIVALENT))
    ids = [c.model_id for c in route]
    assert ids[0] == "a"
    # healthy mid beats the cheaper 'down' one; down is last but present.
    assert ids.index("healthymid") < ids.index("cheapdown")
    assert "cheapdown" in ids


# --------------------------------------------------------------------------- #
# Execute records health outcomes
# --------------------------------------------------------------------------- #
def test_execute_records_health(factory):
    from tests.reelforge.test_routing_execution import ProgAdapter

    with factory() as s:
        seed_default_catalog(s, live_models={"pixelle/wan-i2v"})
        s.commit()
    calls: list = []
    with factory() as s:
        reg = ProviderRegistry()
        reg.register(ProgAdapter("pixelle", poll_to_complete=0))
        route = RoutingService(s, provider_registry=reg).resolve_route(
            capability="broll", model_id="pixelle/wan-i2v"
        )
        RoutingService(s, provider_registry=reg).execute(
            route, {}, health_recorder=lambda pk, ok, ms, cap="": calls.append((pk, ok)),
        )
    assert ("pixelle", True) in calls


# --------------------------------------------------------------------------- #
# Endpoint
# --------------------------------------------------------------------------- #
@pytest.fixture()
def client(monkeypatch, factory):
    @contextmanager
    def _gs():
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr(catalog_mod, "get_session", _gs)
    monkeypatch.setattr(catalog_mod, "_DB_IMPORT_ERROR", None)
    app = FastAPI()
    app.include_router(catalog_mod.router)

    def _http_handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), factory


def test_health_endpoint(client):
    tc, factory = client
    _record(factory, "pixelle", 5, 0)
    resp = tc.get("/api/v1/catalog/providers/health")
    assert resp.status_code == 200, resp.text
    providers = resp.json()["data"]["providers"]
    assert any(p["provider_key"] == "pixelle" and p["state"] == "healthy" for p in providers)
