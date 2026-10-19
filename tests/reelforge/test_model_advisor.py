"""Model advisor tests — typed Choice (primary pick) + Score (render arbitration).

Covers the pure advisor with an injected fake Jev client (no network), the
graceful degradation to the cost/latency policy pass-through when no client /
``TYPESAFE_API_KEY`` is present, and the wiring into
:meth:`RoutingService.resolve_route` over a seeded in-memory catalog.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.routing.base import (
    NormalizedUsage,
    ProviderRegistry,
    ProviderRun,
    QuoteResult,
)
from app.domains.routing.model_advisor import (
    SOURCE_ADVISOR,
    SOURCE_DEGRADED,
    SOURCE_POLICY,
    RenderCandidate,
    ShotBrief,
    advise_primary,
    arbitrate_renders,
)
from app.domains.routing.policy import Candidate
from app.domains.routing.service import RoutingService
from app.models.db.base import Base
from app.models.db.marketplace import (
    ModelCatalogEntry,
    PriceVersion,
    ProviderCatalog,
)


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakePickClient:
    """Fake Jev client that returns a canned Choice answer for the primary pick."""

    def __init__(self, choice: str, confidence: float, probabilities=None) -> None:
        self._choice = choice
        self._confidence = confidence
        self._probs = probabilities or {}
        self.calls = 0

    async def system_one(self, state, questions):
        self.calls += 1
        return {
            "answers": {
                "best_model": {
                    "choice": self._choice,
                    "confidence": self._confidence,
                    "probabilities": self._probs,
                }
            }
        }


class FakeScoreClient:
    """Fake Jev client returning a per-render raw quality score from a mapping."""

    def __init__(self, by_ref: dict[str, float]) -> None:
        self._by_ref = by_ref

    async def system_one(self, state, questions):
        ref = state.get("render", {}).get("resultRef")
        return {"answers": {"output_quality": {"score": self._by_ref.get(ref, 0), "confidence": 0.8}}}


class FakeAdapter:
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
        return NormalizedUsage(unit="seconds", quantity_units=0, cost_micros=0, raw={})


def _candidates() -> list[Candidate]:
    return [
        Candidate("pixelle/wan-i2v", "pixelle", "video", 600_000, latency_band="fast"),
        Candidate("runway/gen", "runway", "video", 900_000, latency_band="standard"),
    ]


BRIEF = ShotBrief(prompt="a neon city drone flythrough", motion="fast camera", duration_s=6)


# --------------------------------------------------------------------------- #
# Pure advisor — typed Choice
# --------------------------------------------------------------------------- #
def test_advise_primary_trusts_confident_pick():
    client = FakePickClient("runway/gen", confidence=0.92, probabilities={"runway/gen": 0.9})
    advice = asyncio.run(advise_primary(BRIEF, _candidates(), client=client))
    assert advice.model_id == "runway/gen"
    assert advice.provider_key == "runway"
    assert advice.source == SOURCE_ADVISOR
    assert advice.degraded is False
    assert client.calls == 1


def test_advise_primary_low_confidence_falls_back_to_policy():
    # Cheapest admissible (fast, 600k) is the cost/latency policy pick.
    client = FakePickClient("runway/gen", confidence=0.2)
    advice = asyncio.run(advise_primary(BRIEF, _candidates(), client=client))
    assert advice.model_id == "pixelle/wan-i2v"
    assert advice.source == SOURCE_POLICY
    assert advice.degraded is False


def test_advise_primary_rejects_inadmissible_pick():
    # Model names a candidate the policy would not route -> policy pick wins.
    client = FakePickClient("ghost/model", confidence=0.99)
    advice = asyncio.run(advise_primary(BRIEF, _candidates(), client=client))
    assert advice.model_id == "pixelle/wan-i2v"
    assert advice.source == SOURCE_POLICY


def test_advise_primary_degrades_without_client(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("typesafe_api_key", raising=False)
    advice = asyncio.run(advise_primary(BRIEF, _candidates(), client=None))
    assert advice.degraded is True
    assert advice.source == SOURCE_DEGRADED
    # Degrades to the current cost/latency policy pass-through: cheapest admissible.
    assert advice.model_id == "pixelle/wan-i2v"


def test_advise_primary_single_candidate_skips_inference():
    client = FakePickClient("x", confidence=0.99)
    advice = asyncio.run(advise_primary(BRIEF, _candidates()[:1], client=client))
    assert advice.model_id == "pixelle/wan-i2v"
    assert advice.source == SOURCE_POLICY
    assert client.calls == 0  # no inference spent on a trivial choice


# --------------------------------------------------------------------------- #
# Fallback render arbitration — typed Score
# --------------------------------------------------------------------------- #
def test_arbitrate_renders_ranks_by_quality():
    renders = [
        RenderCandidate(id="a", model_id="pixelle/wan-i2v", result_ref="ref-a"),
        RenderCandidate(id="b", model_id="runway/gen", result_ref="ref-b"),
    ]
    client = FakeScoreClient({"ref-a": 1, "ref-b": 3})
    result = asyncio.run(arbitrate_renders(BRIEF, renders, client=client))
    assert result.best.id == "b"
    assert [r.id for r in result.ranked] == ["b", "a"]
    assert result.degraded is False
    assert result.best.quality == pytest.approx(1.0)


def test_arbitrate_renders_degrades_without_client(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("typesafe_api_key", raising=False)
    renders = [RenderCandidate(id="a"), RenderCandidate(id="b")]
    result = asyncio.run(arbitrate_renders(BRIEF, renders, client=None))
    assert result.degraded is True
    assert result.best.id == "a"  # input order preserved
    assert all(not r.scored for r in result.ranked)


# --------------------------------------------------------------------------- #
# Wiring into RoutingService.resolve_route
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


def _seed_catalog(session) -> None:
    pixelle = ProviderCatalog(provider_key="pixelle", display_name="Pixelle", enabled=True)
    runway = ProviderCatalog(provider_key="runway", display_name="Runway", enabled=True)
    session.add_all([pixelle, runway])
    session.flush()

    entries = [
        ModelCatalogEntry(
            model_id="pixelle/wan-i2v", provider_id=pixelle.id, capability="video",
            metering_unit="seconds", region="us", availability_state="available",
            latency_band="fast", release_status="ga",
        ),
        ModelCatalogEntry(
            model_id="runway/gen", provider_id=runway.id, capability="video",
            metering_unit="seconds", region="us", availability_state="available",
            latency_band="standard", release_status="ga",
        ),
    ]
    session.add_all(entries)
    session.flush()
    prices = {"pixelle/wan-i2v": 100_000, "runway/gen": 150_000}
    for entry in entries:
        session.add(
            PriceVersion(
                model_entry_id=entry.id, model_id=entry.model_id, unit="seconds",
                unit_price_micros=prices[entry.model_id],
                quote_rules={"default_units": 6}, version=1,
            )
        )
    session.commit()


def _svc(session, *adapters: str) -> RoutingService:
    reg = ProviderRegistry()
    for key in adapters:
        reg.register(FakeAdapter(key))
    return RoutingService(session, provider_registry=reg)


def test_resolve_route_uses_advisor_pick(factory):
    with factory() as s:
        _seed_catalog(s)
    with factory() as s:
        client = FakePickClient("runway/gen", confidence=0.9)
        route = _svc(s, "pixelle", "runway").resolve_route(
            capability="video", brief=BRIEF, advisor_client=client,
        )
        assert route.primary.model_id == "runway/gen"
        assert route.advice is not None
        assert route.advice.source == SOURCE_ADVISOR
        assert route.to_dict()["advice"]["model_id"] == "runway/gen"


def test_resolve_route_degrades_to_policy_pass_through(factory, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("typesafe_api_key", raising=False)
    with factory() as s:
        _seed_catalog(s)
    with factory() as s:
        # No advisor client + no key -> cost/latency policy pick (cheapest = fast/6s).
        route = _svc(s, "pixelle", "runway").resolve_route(
            capability="video", brief=BRIEF, advisor_client=None,
        )
        assert route.primary.model_id == "pixelle/wan-i2v"
        assert route.advice is not None
        assert route.advice.degraded is True
        assert route.advice.source == SOURCE_DEGRADED


def test_resolve_route_explicit_model_id_bypasses_advisor(factory):
    with factory() as s:
        _seed_catalog(s)
    with factory() as s:
        client = FakePickClient("runway/gen", confidence=0.99)
        route = _svc(s, "pixelle", "runway").resolve_route(
            capability="video", model_id="pixelle/wan-i2v", brief=BRIEF, advisor_client=client,
        )
        # Explicit pin wins; advisor is not consulted.
        assert route.primary.model_id == "pixelle/wan-i2v"
        assert route.advice is None
        assert client.calls == 0
