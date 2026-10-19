"""Catalog admin + seed + OpenRouter import tests (in-memory SQLite)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.catalog.admin import CatalogAdmin
from app.domains.catalog.openrouter_import import import_openrouter_models
from app.domains.catalog.repository import CatalogRepository
from app.domains.catalog.schemas import GenerationQuoteRequest
from app.domains.catalog.seed_data import MODELS, PROVIDERS, seed_default_catalog
from app.domains.catalog.service import CatalogService
from app.models.db.base import Base
from app.models.db.marketplace import (
    ModelCatalogEntry,
    PriceVersion,
    ProviderCatalog,
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


def _count(session, model) -> int:
    return int(session.execute(select(func.count()).select_from(model)).scalar_one())


# --------------------------------------------------------------------------- #
# Seed
# --------------------------------------------------------------------------- #
def test_seed_publishes_full_catalog(factory):
    with factory() as s:
        counts = seed_default_catalog(s)
        s.commit()
    assert counts["providers"] == len(PROVIDERS)
    assert counts["models"] == len(MODELS)
    with factory() as s:
        assert _count(s, ProviderCatalog) == len(PROVIDERS)
        assert _count(s, ModelCatalogEntry) == len(MODELS)
        assert _count(s, PriceVersion) == len(MODELS)
        # Every capability is represented.
        caps = {
            row[0]
            for row in s.execute(select(ModelCatalogEntry.capability).distinct())
        }
        assert {"script", "voice", "avatar", "broll", "image", "music"} <= caps


def test_seed_is_idempotent(factory):
    with factory() as s:
        seed_default_catalog(s)
        s.commit()
    with factory() as s:
        seed_default_catalog(s)  # second run
        s.commit()
    with factory() as s:
        # No duplicate rows, and prices did not churn (still one version each).
        assert _count(s, ModelCatalogEntry) == len(MODELS)
        assert _count(s, PriceVersion) == len(MODELS)


def test_seed_everything_shadow_by_default(factory):
    with factory() as s:
        seed_default_catalog(s)
        s.commit()
    with factory() as s:
        live = s.execute(
            select(func.count())
            .select_from(ModelCatalogEntry)
            .where(ModelCatalogEntry.release_status != "shadow")
        ).scalar_one()
        assert live == 0
        # Providers disabled until promoted.
        enabled = s.execute(
            select(func.count())
            .select_from(ProviderCatalog)
            .where(ProviderCatalog.enabled.is_(True))
        ).scalar_one()
        assert enabled == 0


def test_seed_promote_live(factory):
    with factory() as s:
        seed_default_catalog(s, live_models={"pixelle/wan-i2v"})
        s.commit()
    with factory() as s:
        entry = CatalogRepository(s).get_model("pixelle/wan-i2v")
        assert entry.release_status == "ga"
        provider = s.get(ProviderCatalog, entry.provider_id)
        assert provider.enabled is True
        assert provider.credential_state == "configured"


def test_seeded_live_model_browsable_and_quotable(factory):
    with factory() as s:
        seed_default_catalog(
            s, live_models={"anthropic/claude-sonnet-4", "pixelle/wan-i2v"}
        )
        s.commit()
    with factory() as s:
        svc = CatalogService(s)
        models = svc.browse_models(capability="broll")
        assert any(m["model_id"] == "pixelle/wan-i2v" for m in models)
        # An ad-hoc quote against a promoted model resolves + signs.
        quote = svc.quote_generation(
            GenerationQuoteRequest(stages={"broll": "pixelle/wan-i2v"}),
            user_id="u1",
        )
        # 40_000 micros/sec * 6 default seconds
        assert quote["total_micros"] == 240_000
        assert quote["signature"]


def test_price_change_creates_new_version(factory):
    with factory() as s:
        admin = CatalogAdmin(s)
        admin.upsert_model(
            "x/y", provider_key="x", capability="image", metering_unit="images"
        )
        admin.ensure_price("x/y", unit="images", unit_price_micros=10_000)
        s.commit()
    with factory() as s:
        admin = CatalogAdmin(s)
        admin.ensure_price("x/y", unit="images", unit_price_micros=12_000)  # changed
        admin.ensure_price("x/y", unit="images", unit_price_micros=12_000)  # no-op
        s.commit()
    with factory() as s:
        versions = list(
            s.execute(
                select(PriceVersion).where(PriceVersion.model_id == "x/y")
            ).scalars()
        )
        assert len(versions) == 2
        active = CatalogRepository(s).active_price_version("x/y")
        assert active.unit_price_micros == 12_000
        assert active.version == 2


# --------------------------------------------------------------------------- #
# OpenRouter import
# --------------------------------------------------------------------------- #
class _FakeORAdapter:
    def raw_models(self):
        return [
            {
                "id": "anthropic/claude-3.5-sonnet",
                "name": "Claude 3.5 Sonnet",
                "pricing": {"prompt": "0.000003", "completion": "0.000015"},
            },
            {
                "id": "black-forest-labs/flux",
                "name": "FLUX",
                "architecture": {"output_modalities": "image"},
                "pricing": {},
            },
            {"id": "", "name": "skip"},
        ]


def test_openrouter_import_registers_shadow_models(factory):
    with factory() as s:
        result = import_openrouter_models(s, adapter=_FakeORAdapter())
        s.commit()
    assert result["imported"] == 2
    assert result["priced"] == 1  # only the text model had a completion price
    with factory() as s:
        repo = CatalogRepository(s)
        text = repo.get_model("openrouter/anthropic/claude-3.5-sonnet")
        assert text.capability == "script"
        assert text.release_status == "shadow"
        price = repo.active_price_version("openrouter/anthropic/claude-3.5-sonnet")
        assert price.unit_price_micros == 15  # $0.000015/token -> 15 micros
        img = repo.get_model("openrouter/black-forest-labs/flux")
        assert img.capability == "image"


def test_openrouter_import_idempotent(factory):
    with factory() as s:
        import_openrouter_models(s, adapter=_FakeORAdapter())
        s.commit()
    with factory() as s:
        import_openrouter_models(s, adapter=_FakeORAdapter())
        s.commit()
    with factory() as s:
        # Two valid models, no duplicates, one price version for the text model.
        assert _count(s, ModelCatalogEntry) == 2
        assert _count(s, PriceVersion) == 1
