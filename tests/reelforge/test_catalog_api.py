"""Catalog domain API tests — model/profile browse + generation quote.

Exercises ``app.domains.catalog.router`` end-to-end over a FastAPI ``TestClient``
with Postgres replaced by in-memory SQLite. No external I/O. Identity is switched
per request via the ``x-api-key`` header (SHA-256 stored as ``User.api_key_hash``)
so the same client acts as different callers by swapping the header.

Covered
-------
* model listing hides shadow entries and filters by capability
* model detail returns provider + active price; 404 for unknown/shadow
* profile listing returns curated + owner-owned, never a stranger's private one
* generation quote: profile + ad-hoc stages, estimate override, budget cap flag,
  unknown model / missing price / unknown / forbidden profile errors
* the returned quote snapshot carries a valid server signature
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import importlib

from app.domains.catalog.service import CatalogService

# The package ``__init__`` re-exports the APIRouter as ``app.domains.catalog.router``
# (shadowing the submodule attribute), so resolve the real module explicitly to
# monkeypatch its ``get_session`` global.
catalog_mod = importlib.import_module("app.domains.catalog.router")
from app.models.db.base import Base
from app.models.db.marketplace import (
    GenerationProfile,
    ModelCatalogEntry,
    PriceVersion,
    ProviderCatalog,
)
from app.models.db.models import User
from app.models.exception import HttpException
from app.utils import utils


def _key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _headers(raw_key: str) -> dict[str, str]:
    return {"x-api-key": raw_key}


@pytest.fixture()
def env(monkeypatch):
    """Catalog router wired to a shared in-memory SQLite DB."""
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

    monkeypatch.setattr(catalog_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(catalog_mod, "_DB_IMPORT_ERROR", None)

    app = FastAPI()
    app.include_router(catalog_mod.router)

    def _http_handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


@pytest.fixture()
def seeded(env):
    """Seed two users, a provider, live+shadow models, prices, and profiles."""
    _client, Factory = env
    out: dict[str, object] = {}
    with Factory() as s:
        alice = User(email="alice@example.com", api_key_hash=_key_hash("alice-key"))
        bob = User(email="bob@example.com", api_key_hash=_key_hash("bob-key"))
        s.add_all([alice, bob])
        s.flush()
        out["alice"] = alice.id
        out["bob"] = bob.id

        provider = ProviderCatalog(
            provider_key="pixelle",
            display_name="Pixelle",
            region="us",
            data_policy="no-retain",
            health_state="healthy",
            enabled=True,
        )
        anthropic = ProviderCatalog(
            provider_key="anthropic", display_name="Anthropic", enabled=True
        )
        s.add_all([provider, anthropic])
        s.flush()

        broll = ModelCatalogEntry(
            model_id="pixelle/wan-i2v",
            provider_id=provider.id,
            capability="broll",
            display_name="Wan i2v",
            metering_unit="seconds",
            release_status="ga",
            availability_state="available",
        )
        script = ModelCatalogEntry(
            model_id="anthropic/claude-sonnet",
            provider_id=anthropic.id,
            capability="script",
            display_name="Claude Sonnet",
            metering_unit="output_tokens",
            release_status="ga",
            availability_state="available",
        )
        shadow = ModelCatalogEntry(
            model_id="pixelle/wan-shadow",
            provider_id=provider.id,
            capability="broll",
            display_name="Wan (shadow)",
            metering_unit="seconds",
            release_status="shadow",
        )
        s.add_all([broll, script, shadow])
        s.flush()

        # $0.10/sec broll, default 6s; $0.000002/token script, default 1000 tok.
        s.add_all(
            [
                PriceVersion(
                    model_entry_id=broll.id,
                    model_id=broll.model_id,
                    unit="seconds",
                    unit_price_micros=100_000,
                    quote_rules={"default_units": 6},
                    version=1,
                ),
                PriceVersion(
                    model_entry_id=script.id,
                    model_id=script.model_id,
                    unit="output_tokens",
                    unit_price_micros=2,
                    quote_rules={"default_units": 1000},
                    version=1,
                ),
            ]
        )

        s.add_all(
            [
                GenerationProfile(
                    slug="creator-fast-v1",
                    display_name="Creator Fast",
                    stages={
                        "script": {"model_id": "anthropic/claude-sonnet"},
                        "broll": {"model_id": "pixelle/wan-i2v"},
                    },
                    routing={"fallback": "none"},
                    is_curated=True,
                ),
                GenerationProfile(
                    slug="alice-private",
                    display_name="Alice Private",
                    owner_user_id=alice.id,
                    stages={"broll": {"model_id": "pixelle/wan-i2v"}},
                    is_curated=False,
                ),
            ]
        )
        s.commit()
    return out


# =========================================================================== #
# Model browse
# =========================================================================== #
def test_list_models_hides_shadow(env, seeded):
    client, _ = env
    resp = client.get("/api/v1/catalog/models", headers=_headers("alice-key"))
    assert resp.status_code == 200, resp.text
    ids = {m["model_id"] for m in resp.json()["data"]["models"]}
    assert "pixelle/wan-i2v" in ids
    assert "anthropic/claude-sonnet" in ids
    assert "pixelle/wan-shadow" not in ids


def test_list_models_capability_filter(env, seeded):
    client, _ = env
    resp = client.get("/api/v1/catalog/models?capability=broll")
    assert resp.status_code == 200, resp.text
    models = resp.json()["data"]["models"]
    assert models and all(m["capability"] == "broll" for m in models)
    broll = next(m for m in models if m["model_id"] == "pixelle/wan-i2v")
    assert broll["provider"]["provider_key"] == "pixelle"
    assert broll["price"]["unit_price_micros"] == 100_000


def test_get_model_detail_and_404(env, seeded):
    client, _ = env
    ok = client.get("/api/v1/catalog/models/pixelle/wan-i2v")
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["model_id"] == "pixelle/wan-i2v"

    missing = client.get("/api/v1/catalog/models/pixelle/nope")
    assert missing.status_code == 404
    # A shadow model is not exposed via the public detail endpoint either.
    shadow = client.get("/api/v1/catalog/models/pixelle/wan-shadow")
    assert shadow.status_code == 404


# =========================================================================== #
# Profiles
# =========================================================================== #
def test_profiles_owner_scoping(env, seeded):
    client, _ = env
    # Alice sees the curated profile AND her own private one.
    alice = client.get("/api/v1/catalog/profiles", headers=_headers("alice-key"))
    assert alice.status_code == 200, alice.text
    alice_slugs = {p["slug"] for p in alice.json()["data"]["profiles"]}
    assert alice_slugs == {"creator-fast-v1", "alice-private"}

    # Bob sees only the curated one, never Alice's private profile.
    bob = client.get("/api/v1/catalog/profiles", headers=_headers("bob-key"))
    bob_slugs = {p["slug"] for p in bob.json()["data"]["profiles"]}
    assert bob_slugs == {"creator-fast-v1"}


def test_profiles_requires_auth(env, seeded):
    client, _ = env
    assert client.get("/api/v1/catalog/profiles").status_code == 401


# =========================================================================== #
# Generation quote
# =========================================================================== #
def test_quote_from_profile_sums_stages(env, seeded):
    client, _ = env
    resp = client.post(
        "/api/v1/catalog/quotes/generation",
        json={"profile": "creator-fast-v1"},
        headers=_headers("alice-key"),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    # broll: 100_000 * 6 = 600_000 ; script: 2 * 1000 = 2_000 ; total 602_000
    assert data["total_micros"] == 602_000
    assert data["max_cost_micros"] == 602_000
    assert data["within_budget"] is True
    assert {s["stage"] for s in data["stages"]} == {"script", "broll"}
    assert data["signature"]


def test_quote_estimate_override_and_cap_flag(env, seeded):
    client, _ = env
    resp = client.post(
        "/api/v1/catalog/quotes/generation",
        json={
            "profile": "creator-fast-v1",
            "estimates": {"broll": 30},
            "max_cost_usd": "1.00",
        },
        headers=_headers("alice-key"),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    # broll now 100_000 * 30 = 3_000_000 ; +2_000 = 3_002_000 > $1.00 cap.
    assert data["total_micros"] == 3_002_000
    assert data["cap_micros"] == 1_000_000
    assert data["within_budget"] is False


def test_quote_signature_verifies(env, seeded):
    client, Factory = env
    resp = client.post(
        "/api/v1/catalog/quotes/generation",
        json={"profile": "creator-fast-v1"},
        headers=_headers("alice-key"),
    )
    snapshot = resp.json()["data"]
    with Factory() as s:
        assert CatalogService(s).verify_quote_snapshot(snapshot) is True
        tampered = dict(snapshot)
        tampered["max_cost_micros"] = 1
        assert CatalogService(s).verify_quote_snapshot(tampered) is False


def test_quote_unknown_and_forbidden_profile(env, seeded):
    client, _ = env
    missing = client.post(
        "/api/v1/catalog/quotes/generation",
        json={"profile": "does-not-exist"},
        headers=_headers("alice-key"),
    )
    assert missing.status_code == 404
    # Bob cannot quote Alice's private profile.
    forbidden = client.post(
        "/api/v1/catalog/quotes/generation",
        json={"profile": "alice-private"},
        headers=_headers("bob-key"),
    )
    assert forbidden.status_code == 403


def test_quote_ad_hoc_unknown_model_422(env, seeded):
    client, _ = env
    resp = client.post(
        "/api/v1/catalog/quotes/generation",
        json={"stages": {"broll": "pixelle/ghost"}},
        headers=_headers("alice-key"),
    )
    assert resp.status_code == 422


def test_quote_shadow_model_not_available_422(env, seeded):
    client, _ = env
    resp = client.post(
        "/api/v1/catalog/quotes/generation",
        json={"stages": {"broll": "pixelle/wan-shadow"}},
        headers=_headers("alice-key"),
    )
    assert resp.status_code == 422


def test_quote_requires_profile_or_stages_400(env, seeded):
    client, _ = env
    resp = client.post(
        "/api/v1/catalog/quotes/generation",
        json={},
        headers=_headers("alice-key"),
    )
    assert resp.status_code == 400
