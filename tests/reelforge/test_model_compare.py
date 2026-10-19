"""Model comparison — price+health enrichment, sort, and route precedence."""

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
from app.models.db.base import Base
from app.models.exception import HttpException
from app.utils import utils

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


@pytest.fixture()
def client(monkeypatch, factory):
    with factory() as s:
        # Promote several broll models live + record health for one provider.
        seed_default_catalog(
            s, live_models={"kling/v1", "pixelle/wan-i2v", "runway/gen-3"}
        )
        h = ProviderHealthService(s)
        for _ in range(5):
            h.record("pixelle", ok=True, latency_ms=200)
        s.commit()

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
    return TestClient(app)


def test_compare_sorts_by_price_and_joins_health(client):
    resp = client.get("/api/v1/catalog/models/compare?capability=broll&sort=price")
    assert resp.status_code == 200, resp.text
    models = resp.json()["data"]["models"]
    prices = [m["price"]["unit_price_micros"] for m in models]
    assert prices == sorted(prices)  # cheapest first
    # pixelle carries a healthy summary from the recorded runs.
    pixelle = next(m for m in models if m["model_id"] == "pixelle/wan-i2v")
    assert pixelle["health"]["state"] == "healthy"
    assert pixelle["health"]["avg_latency_ms"] == 200


def test_compare_route_not_shadowed_by_model_path(client):
    # 'compare' must NOT be treated as a model id (404 by the {model_id:path} route).
    resp = client.get("/api/v1/catalog/models/compare?capability=broll")
    assert resp.status_code == 200
    assert "models" in resp.json()["data"]


def test_compare_sort_latency(client):
    resp = client.get("/api/v1/catalog/models/compare?capability=broll&sort=latency")
    assert resp.status_code == 200
    assert resp.json()["data"]["sort"] == "latency"
