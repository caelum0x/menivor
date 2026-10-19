"""OpenRouter routing adapter tests (injected fake transport; no network)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domains.routing.base import RUN_COMPLETED, ProviderAdapter, ProviderError
from app.domains.routing.providers.openrouter import OpenRouterAdapter


class FakeTransport:
    """Records calls and returns canned responses keyed by (method, path)."""

    def __init__(self, responses: dict) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, method: str, path: str, *, json: dict | None = None) -> dict:
        self.calls.append((method, path, json))
        key = (method, path)
        value = self.responses.get(key)
        if isinstance(value, Exception):
            raise value
        return value or {}


def _adapter(responses: dict) -> tuple[OpenRouterAdapter, FakeTransport]:
    transport = FakeTransport(responses)
    return OpenRouterAdapter(api_key="k", request_fn=transport), transport


def test_is_provider_adapter():
    adapter, _ = _adapter({})
    assert isinstance(adapter, ProviderAdapter)
    assert adapter.provider_key == "openrouter"


def test_catalog_maps_models_namespaced():
    adapter, _ = _adapter(
        {
            ("GET", "/models"): {
                "data": [
                    {"id": "anthropic/claude-3.5", "name": "Claude"},
                    {"id": "", "name": "skip-me"},
                ]
            }
        }
    )
    listings = adapter.catalog()
    assert len(listings) == 1
    assert listings[0].model_id == "openrouter/anthropic/claude-3.5"
    assert listings[0].capability == "script"
    assert listings[0].metering_unit == "tokens"


def test_quote_uses_price_version_math():
    adapter, _ = _adapter({})
    price = SimpleNamespace(
        id="pv1",
        unit_price_micros=2,
        min_charge_micros=0,
        flat_fee_micros=0,
        quote_rules={"default_units": 1000},
    )
    q = adapter.quote({"estimated_quantity": 1500}, price)
    assert q.max_cost_micros == 3000  # 2 * 1500
    assert q.price_version_id == "pv1"
    assert q.expires_at is not None


def test_submit_returns_terminal_run_with_usage():
    adapter, transport = _adapter(
        {
            ("POST", "/chat/completions"): {
                "id": "gen-123",
                "choices": [{"message": {"content": "hello script"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost": "0.002"},
            }
        }
    )
    run = adapter.submit(
        {"messages": [{"role": "user", "content": "hi"}]},
        {"model_id": "openrouter/anthropic/claude-3.5"},
        "corr-1",
    )
    assert run.state == RUN_COMPLETED
    assert run.result_ref == "hello script"
    assert run.usage.quantity_units == 150  # prompt + completion
    assert run.usage.cost_micros == 2000  # $0.002
    # The upstream model id is un-namespaced before the call.
    _method, _path, body = transport.calls[-1]
    assert body["model"] == "anthropic/claude-3.5"
    # poll echoes a synchronous run; cancel is a no-op.
    assert adapter.poll(run) is run
    assert adapter.cancel(run) is False


def test_normalize_usage_without_cost_defaults_zero():
    adapter, _ = _adapter({})
    usage = adapter.normalize_usage({"total_tokens": 42})
    assert usage.unit == "tokens"
    assert usage.quantity_units == 42
    assert usage.cost_micros == 0


def test_client_error_raises_provider_error():
    adapter, _ = _adapter(
        {("GET", "/models"): ProviderError("boom", provider_key="openrouter")}
    )
    with pytest.raises(ProviderError):
        adapter.catalog()
