"""Tests for the capability provider adapters + registry population.

Each adapter is exercised with an injected fake transport (no network). Covers
the ProviderAdapter protocol conformance, quote-from-price parity, sync vs async
submit/poll lifecycles, usage normalization, and credential-gated registration.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domains.routing.base import (
    RUN_COMPLETED,
    RUN_QUEUED,
    RUN_RUNNING,
    ProviderAdapter,
    ProviderError,
    ProviderRegistry,
)
from app.domains.routing.providers.elevenlabs import ElevenLabsAdapter
from app.domains.routing.providers.heygen import HeyGenAdapter
from app.domains.routing.providers.image import ImageAdapter
from app.domains.routing.providers.pixelle import PixelleAdapter
from app.domains.routing.providers.registry import register_available_adapters


class FakeTransport:
    def __init__(self, responses: dict) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, method: str, path: str, *, json: dict | None = None) -> dict:
        self.calls.append((method, path, json))
        value = self.responses.get((method, path))
        if value is None:
            # Allow prefix matches for query-string / id paths.
            for (m, p), v in self.responses.items():
                if m == method and path.startswith(p):
                    value = v
                    break
        if isinstance(value, Exception):
            raise value
        return value or {}


PRICE_VOICE = SimpleNamespace(
    id="pv", unit_price_micros=300, min_charge_micros=0, flat_fee_micros=0,
    quote_rules={"default_units": 600},
)
PRICE_SEC = SimpleNamespace(
    id="pv", unit_price_micros=5000, min_charge_micros=0, flat_fee_micros=0,
    quote_rules={"default_units": 30},
)
PRICE_IMG = SimpleNamespace(
    id="pv", unit_price_micros=40000, min_charge_micros=0, flat_fee_micros=0,
    quote_rules={"default_units": 1},
)


# --------------------------------------------------------------------------- #
# ElevenLabs (voice, sync)
# --------------------------------------------------------------------------- #
def test_elevenlabs_is_adapter_and_lifecycle():
    t = FakeTransport(
        {
            ("GET", "/v1/voices"): {"voices": [{"voice_id": "abc"}, {"voice_id": ""}]},
            ("POST", "/v1/text-to-speech/abc"): {"request_id": "r1", "audio_ref": "s3://a"},
        }
    )
    a = ElevenLabsAdapter(api_key="k", request_fn=t)
    assert isinstance(a, ProviderAdapter)
    assert [m.model_id for m in a.catalog()] == ["elevenlabs/abc"]

    # quote estimates characters from text when no explicit quantity.
    q = a.quote({"text": "x" * 900}, PRICE_VOICE)
    assert q.max_cost_micros == 300 * 900

    run = a.submit({"text": "hello"}, {"model_id": "elevenlabs/abc"}, "corr")
    assert run.state == RUN_COMPLETED
    assert run.usage.unit == "characters"
    assert run.usage.quantity_units == 5
    assert a.poll(run) is run


def test_elevenlabs_submit_requires_text():
    a = ElevenLabsAdapter(api_key="k", request_fn=FakeTransport({}))
    with pytest.raises(ProviderError):
        a.submit({}, {"model_id": "elevenlabs/abc"}, "corr")


# --------------------------------------------------------------------------- #
# HeyGen (avatar, async)
# --------------------------------------------------------------------------- #
def test_heygen_async_submit_then_poll():
    t = FakeTransport(
        {
            ("POST", "/v2/video/generate"): {"data": {"video_id": "vid1"}},
            ("GET", "/v1/video_status.get"): {
                "data": {"status": "completed", "duration": 12.4, "video_url": "http://v"}
            },
        }
    )
    a = HeyGenAdapter(api_key="k", request_fn=t)
    run = a.submit({"avatar_id": "x"}, {"model_id": "heygen/x"}, "corr")
    assert run.state == RUN_QUEUED
    assert run.run_id == "vid1"
    polled = a.poll(run)
    assert polled.state == RUN_COMPLETED
    assert polled.usage.unit == "seconds"
    assert polled.usage.quantity_units == 13  # 12.4 rounded up
    assert polled.result_ref == "http://v"


def test_heygen_submit_without_video_id_raises():
    a = HeyGenAdapter(api_key="k", request_fn=FakeTransport({("POST", "/v2/video/generate"): {"data": {}}}))
    with pytest.raises(ProviderError):
        a.submit({}, {"model_id": "heygen/x"}, "corr")


def test_heygen_poll_processing_is_running():
    t = FakeTransport(
        {("GET", "/v1/video_status.get"): {"data": {"status": "processing"}}}
    )
    a = HeyGenAdapter(api_key="k", request_fn=t)
    from app.domains.routing.base import ProviderRun

    polled = a.poll(ProviderRun(provider_key="heygen", run_id="vid1", state=RUN_QUEUED))
    assert polled.state == RUN_RUNNING


# --------------------------------------------------------------------------- #
# Pixelle (video, async)
# --------------------------------------------------------------------------- #
def test_pixelle_async_lifecycle_and_quote():
    t = FakeTransport(
        {
            ("POST", "/run"): {"run_id": "run1"},
            ("GET", "/status/run1"): {
                "state": "completed",
                "progress": 100,
                "seconds": 6,
                "output_url": "http://clip",
            },
        }
    )
    a = PixelleAdapter(api_key="k", request_fn=t)
    q = a.quote({}, PRICE_SEC)
    assert q.max_cost_micros == 5000 * 30
    run = a.submit({"prompt": "waves"}, {"model_id": "pixelle/wan-i2v"}, "corr")
    assert run.state == RUN_QUEUED
    polled = a.poll(run)
    assert polled.state == RUN_COMPLETED
    assert polled.usage.quantity_units == 6
    assert polled.result_ref == "http://clip"


# --------------------------------------------------------------------------- #
# Image (generic, sync)
# --------------------------------------------------------------------------- #
def test_image_adapter_sync_generate():
    t = FakeTransport(
        {("POST", "/generate"): {"id": "img1", "images": [{"url": "http://img"}]}}
    )
    a = ImageAdapter(
        provider_key="black-forest-labs",
        base_url="https://api.bfl.ai",
        api_key="k",
        request_fn=t,
    )
    assert isinstance(a, ProviderAdapter)
    q = a.quote({}, PRICE_IMG)
    assert q.max_cost_micros == 40000  # 1 image default
    run = a.submit({"prompt": "cat"}, {"model_id": "black-forest-labs/flux-1.1-pro"}, "c")
    assert run.state == RUN_COMPLETED
    assert run.usage.unit == "images"
    assert run.usage.quantity_units == 1
    assert run.result_ref == "http://img"


# --------------------------------------------------------------------------- #
# Registry population (credential-gated)
# --------------------------------------------------------------------------- #
def test_register_available_adapters_gated_by_env():
    reg = ProviderRegistry()
    keys = register_available_adapters(
        reg,
        env={
            "ELEVENLABS_API_KEY": "e",
            "HEYGEN_API_KEY": "h",
            "STABILITY_API_KEY": "s",
            # openrouter / pixelle / others intentionally absent
        },
    )
    assert set(keys) == {"elevenlabs", "heygen", "stability"}
    assert reg.has("elevenlabs")
    assert reg.has("heygen")
    assert reg.has("stability")
    assert not reg.has("openrouter")
    assert not reg.has("pixelle")


def test_register_available_adapters_empty_env():
    reg = ProviderRegistry()
    assert register_available_adapters(reg, env={}) == []
    assert reg.keys() == []
