"""Photo-avatar + multi-backend voice adapters, and the MCP tool surface."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.routing.base import (
    RUN_COMPLETED,
    RUN_QUEUED,
    ProviderAdapter,
    ProviderError,
    ProviderRegistry,
)
from app.domains.routing.providers.registry import build_adapter
from app.domains.routing.providers.sadtalker import SadTalkerAdapter
from app.domains.routing.providers.tts import SelfHostTTSAdapter
from app.mcp.tools import MCPToolError, dispatch, tool_specs
from app.models.db.base import Base
from app.models.db.models import User


class FakeTransport:
    def __init__(self, responses: dict) -> None:
        self.responses = responses
        self.calls: list = []

    def __call__(self, method: str, path: str, *, json: dict | None = None) -> dict:
        self.calls.append((method, path, json))
        value = self.responses.get((method, path))
        if value is None:
            for (m, p), v in self.responses.items():
                if m == method and path.startswith(p):
                    value = v
                    break
        if isinstance(value, Exception):
            raise value
        return value or {}


_PRICE_SEC = SimpleNamespace(id="pv", unit_price_micros=500, min_charge_micros=0, flat_fee_micros=0, quote_rules={"default_units": 30})
_PRICE_CHAR = SimpleNamespace(id="pv", unit_price_micros=5, min_charge_micros=0, flat_fee_micros=0, quote_rules={"default_units": 600})


# --------------------------------------------------------------------------- #
# SadTalker (avatar, async)
# --------------------------------------------------------------------------- #
def test_sadtalker_async_lifecycle():
    t = FakeTransport(
        {
            ("POST", "/run"): {"run_id": "st1"},
            ("GET", "/status/st1"): {"state": "completed", "seconds": 12, "output_url": "http://v"},
        }
    )
    a = SadTalkerAdapter(api_key="k", request_fn=t)
    assert isinstance(a, ProviderAdapter)
    assert a.catalog()[0].model_id == "sadtalker/photo-avatar"
    run = a.submit(
        {"image_url": "http://img", "audio_url": "http://aud"},
        {"model_id": "sadtalker/photo-avatar"},
        "c",
    )
    assert run.state == RUN_QUEUED
    polled = a.poll(run)
    assert polled.state == RUN_COMPLETED
    assert polled.usage.quantity_units == 12
    assert polled.result_ref == "http://v"


def test_sadtalker_requires_image_and_audio():
    a = SadTalkerAdapter(api_key="k", request_fn=FakeTransport({}))
    with pytest.raises(ProviderError):
        a.submit({"image_url": "x"}, {"model_id": "sadtalker/photo-avatar"}, "c")


# --------------------------------------------------------------------------- #
# Self-host TTS (voice, sync) — Chatterbox/Kokoro/Edge
# --------------------------------------------------------------------------- #
def test_selfhost_tts_sync_and_quote():
    t = FakeTransport({("POST", "/tts"): {"id": "x", "audio_url": "http://a"}})
    a = SelfHostTTSAdapter(provider_key="chatterbox", base_url="http://cb", api_key="k", request_fn=t)
    assert isinstance(a, ProviderAdapter)
    q = a.quote({"text": "x" * 600}, _PRICE_CHAR)
    assert q.max_cost_micros == 5 * 600
    run = a.submit({"text": "hello"}, {"model_id": "chatterbox/tts"}, "c")
    assert run.state == RUN_COMPLETED
    assert run.usage.unit == "characters"
    assert run.usage.quantity_units == 5
    assert run.result_ref == "http://a"


def test_edge_tts_needs_no_auth_header():
    # No api_key -> no Authorization header is attached (EdgeTTS is free).
    def _fake(method, path, *, json=None):
        return {"audio_url": "u"}

    a = SelfHostTTSAdapter(provider_key="edge", base_url="http://edge", request_fn=_fake)
    run = a.submit({"text": "hi"}, {"model_id": "edge/tts"}, "c")
    assert run.state == RUN_COMPLETED


def test_build_adapter_covers_new_providers():
    assert isinstance(build_adapter("sadtalker", "k"), SadTalkerAdapter)
    assert isinstance(build_adapter("chatterbox", "k"), SelfHostTTSAdapter)
    assert isinstance(build_adapter("kokoro", "k"), SelfHostTTSAdapter)
    assert isinstance(build_adapter("edge", ""), SelfHostTTSAdapter)
    assert build_adapter("nope", "k") is None


def test_registry_registers_new_providers():
    from app.domains.routing.providers.registry import register_available_adapters

    reg = ProviderRegistry()
    keys = register_available_adapters(
        reg,
        env={"SADTALKER_API_KEY": "s", "REELFORGE_ENABLE_EDGE_TTS": "1", "CHATTERBOX_API_KEY": "c"},
    )
    assert set(keys) == {"sadtalker", "edge", "chatterbox"}


# --------------------------------------------------------------------------- #
# MCP tool surface
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


def test_tool_specs_shape():
    names = {t["name"] for t in tool_specs()}
    assert {
        "reelforge_list_models",
        "reelforge_generation_quote",
        "reelforge_wallet_balance",
        "reelforge_create_repurpose",
        "reelforge_get_job",
    } <= names
    for spec in tool_specs():
        assert "handler" not in spec  # never leak the callable to the agent
        assert spec["input_schema"]["type"] == "object"


def test_dispatch_wallet_and_catalog_and_repurpose(factory):
    from app.domains.catalog.seed_data import seed_default_catalog

    with factory() as s:
        seed_default_catalog(s, live_models={"pixelle/wan-i2v"})
        u = User(email="a@example.com", api_key_hash="h")
        s.add(u)
        s.flush()
        uid = u.id
        s.commit()

    with factory() as s:
        # list_models
        models = dispatch(s, uid, "reelforge_list_models", {"capability": "broll"})
        assert any(m["model_id"] == "pixelle/wan-i2v" for m in models["models"])
        # generation_quote
        quote = dispatch(
            s, uid, "reelforge_generation_quote", {"stages": {"broll": "pixelle/wan-i2v"}}
        )
        assert quote["total_micros"] == 240_000
        assert quote["signature"]
        # wallet_balance
        bal = dispatch(s, uid, "reelforge_wallet_balance", {})
        assert bal["available_micros"] == 0
        # create_repurpose
        job = dispatch(
            s, uid, "reelforge_create_repurpose", {"source_ref": "https://youtu.be/x"}
        )
        assert job["status"] == "created"
        s.commit()


def test_dispatch_unknown_tool_raises(factory):
    with factory() as s:
        with pytest.raises(MCPToolError):
            dispatch(s, "u", "nope", {})
