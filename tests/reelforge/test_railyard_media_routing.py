"""W3-G: paid provider calls route through Railyard and media jobs meter to Rago.

Fakes only; no network. Covers:

* ``run_chat_payload``: Abacus first, then Relay, then ``None`` (direct);
  402/429 are hard stops.
* ``OpenRouterAdapter.submit``: routes via Relay when configured, falls back to
  direct OpenRouter when Relay is unavailable, never routes around a cap.
* ``media_gateway._settle_job``: every captured media job emits a Rago usage
  event (per render + credits), and a failing meter never breaks settlement.
"""

from __future__ import annotations

import functools
from typing import Any

import pytest

from app.domains.railyard.chat_payload import RoutedChat, run_chat_payload
from app.domains.railyard.errors import RailyardError
from app.domains.routing.base import RUN_COMPLETED, ProviderError
from app.domains.routing.providers.openrouter import OpenRouterAdapter
from app.integrations.railyard import metering
from tests.reelforge.test_media_gateway import (  # noqa: F401 - pytest fixture
    FakeFal,
    _bind_session,
    _Resp,
    client,
)

RELAY_ENV = {"RELAY_URL": "http://relay.test/", "RELAY_API_KEY": "relay-key"}
ABACUS_ENV = {
    "ABACUS_URL": "http://abacus.test",
    "ABACUS_API_KEY": "abacus-key",
    "ABACUS_AGENT_ID": "menivor",
}
OK_CHAT = {
    "id": "chatcmpl-1",
    "choices": [{"message": {"role": "assistant", "content": "a hook"}}],
    "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
}


class FakeHttp:
    """``(url, headers, body, timeout) -> (status, dict)`` transport."""

    def __init__(self, status: int = 200, payload: Any = None, raises: Exception | None = None):
        self.status = status
        self.payload = OK_CHAT if payload is None else payload
        self.raises = raises
        self.calls: list[dict] = []

    def __call__(self, url, headers, body, timeout_s):
        self.calls.append({"url": url, "headers": dict(headers), "body": dict(body)})
        if self.raises is not None:
            raise self.raises
        return self.status, self.payload


BODY = {"model": "meta-llama/llama-3-8b", "messages": [{"role": "user", "content": "hi"}]}


# ── run_chat_payload ────────────────────────────────────────────────────────
def test_payload_returns_none_when_nothing_configured():
    relay = FakeHttp()
    assert run_chat_payload(BODY, env={}, relay_request_fn=relay) is None
    assert relay.calls == []


def test_payload_routes_via_relay_with_tensorzero_model_and_bearer():
    relay = FakeHttp()
    routed = run_chat_payload(
        BODY, relay_provider="openrouter", env=RELAY_ENV, relay_request_fn=relay
    )
    assert isinstance(routed, RoutedChat) and routed.routed_via == "relay"
    assert routed.payload["usage"]["total_tokens"] == 10
    call = relay.calls[0]
    assert call["url"] == "http://relay.test/openai/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer relay-key"
    assert call["body"]["model"] == "tensorzero::model_name::openrouter::meta-llama/llama-3-8b"


@pytest.mark.parametrize("status", [502, 503, 504, 400])
def test_payload_falls_back_when_relay_cannot_serve(status):
    relay = FakeHttp(status=status, payload={"error": {"code": "provider_not_configured"}})
    assert run_chat_payload(BODY, env=RELAY_ENV, relay_request_fn=relay) is None


def test_payload_falls_back_when_relay_unreachable():
    relay = FakeHttp(raises=RailyardError("down", service="abacus", code="http_error"))
    assert run_chat_payload(BODY, env=RELAY_ENV, relay_request_fn=relay) is None


@pytest.mark.parametrize("status,code", [(402, "cap_exceeded"), (429, "rate_limited")])
def test_payload_relay_policy_status_is_a_hard_stop(status, code):
    relay = FakeHttp(status=status, payload={})
    with pytest.raises(RailyardError) as err:
        run_chat_payload(BODY, env=RELAY_ENV, relay_request_fn=relay)
    assert err.value.code == code


def test_payload_prefers_abacus_then_skips_relay():
    abacus = FakeHttp(payload={"success": True, "data": OK_CHAT})
    relay = FakeHttp()
    routed = run_chat_payload(
        BODY,
        relay_provider="openrouter",
        provider_api_key="or-key",
        env={**RELAY_ENV, **ABACUS_ENV},
        abacus_request_fn=abacus,
        relay_request_fn=relay,
    )
    assert routed is not None and routed.routed_via == "abacus"
    assert relay.calls == []
    call = abacus.calls[0]
    assert call["url"] == "http://abacus.test/v1/proxy"
    assert call["headers"]["X-Abacus-Agent"].endswith("menivor")
    assert call["body"]["model"].startswith("tensorzero::model_name::openrouter::")


def test_payload_abacus_cap_is_a_hard_stop():
    abacus = FakeHttp(status=402, payload={"error": "cap"})
    relay = FakeHttp()
    with pytest.raises(RailyardError) as err:
        run_chat_payload(
            BODY, provider_api_key="k", env={**RELAY_ENV, **ABACUS_ENV},
            abacus_request_fn=abacus, relay_request_fn=relay,
        )
    assert err.value.code == "cap_exceeded"
    assert relay.calls == []


def test_payload_abacus_outage_falls_through_to_relay():
    abacus = FakeHttp(raises=RailyardError("down", service="abacus", code="http_error"))
    relay = FakeHttp()
    routed = run_chat_payload(
        BODY, provider_api_key="k", env={**RELAY_ENV, **ABACUS_ENV},
        abacus_request_fn=abacus, relay_request_fn=relay,
    )
    assert routed is not None and routed.routed_via == "relay"


# ── OpenRouter adapter ──────────────────────────────────────────────────────
class DirectTransport:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def __call__(self, method, path, *, json=None):
        self.calls.append((method, path, json))
        return {"id": "direct-1", "choices": [{"message": {"content": "direct"}}], "usage": {"total_tokens": 4}}


def _adapter(env: dict, relay: FakeHttp) -> tuple[OpenRouterAdapter, DirectTransport]:
    direct = DirectTransport()
    adapter = OpenRouterAdapter(
        api_key="or-key",
        request_fn=direct,
        railyard_env=env,
        railyard_chat_fn=functools.partial(run_chat_payload, relay_request_fn=relay),
    )
    return adapter, direct


SNAPSHOT = {"model_id": "openrouter/meta-llama/llama-3-8b"}
REQUEST = {"messages": [{"role": "user", "content": "write a hook"}]}


def test_openrouter_direct_when_railyard_unset():
    relay = FakeHttp()
    adapter, direct = _adapter({}, relay)
    run = adapter.submit(REQUEST, SNAPSHOT, "corr-1")
    assert run.result_ref == "direct" and len(direct.calls) == 1
    assert relay.calls == []


def test_openrouter_routes_through_relay_and_meters(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(
        "app.integrations.railyard.meter_llm_call", lambda **kw: sent.append(kw) or True
    )
    relay = FakeHttp()
    adapter, direct = _adapter(RELAY_ENV, relay)
    run = adapter.submit(REQUEST, SNAPSHOT, "corr-2")
    assert run.state == RUN_COMPLETED
    assert run.result_ref == "a hook"
    assert run.usage.quantity_units == 10
    assert direct.calls == []
    assert relay.calls[0]["body"]["model"] == "tensorzero::model_name::openrouter::meta-llama/llama-3-8b"
    assert sent and sent[0]["routed_via"] == "relay" and sent[0]["provider"] == "openrouter"


def test_openrouter_falls_back_direct_when_relay_unavailable():
    relay = FakeHttp(status=503, payload={"error": {"code": "provider_not_configured"}})
    adapter, direct = _adapter(RELAY_ENV, relay)
    run = adapter.submit(REQUEST, SNAPSHOT, "corr-3")
    assert run.result_ref == "direct" and len(direct.calls) == 1


def test_openrouter_cap_is_not_routed_around():
    relay = FakeHttp(status=402, payload={})
    adapter, direct = _adapter(RELAY_ENV, relay)
    with pytest.raises(ProviderError) as err:
        adapter.submit(REQUEST, SNAPSHOT, "corr-4")
    assert err.value.retryable is False
    assert direct.calls == []


def test_openrouter_honours_railyard_relay_url_alias():
    relay = FakeHttp()
    adapter, direct = _adapter({"RAILYARD_RELAY_URL": "http://ry.test"}, relay)
    adapter.submit(REQUEST, SNAPSHOT, "corr-5")
    assert relay.calls[0]["url"] == "http://ry.test/openai/v1/chat/completions"
    assert direct.calls == []


# ── media job settlement → Rago ─────────────────────────────────────────────
class RecordingSink:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.events: list[dict] = []

    def record_event(self, **kwargs):
        if self.fail:
            raise RuntimeError("rago down")
        self.events.append(kwargs)


def _generate_image(tc, monkeypatch):
    from app.domains.gateway import media_gateway

    monkeypatch.setenv("OPENAI_API_KEY", "sk-key")
    fal = FakeFal([_Resp(200, {"data": [{"url": "https://oai/panda.png"}]})])
    monkeypatch.setattr(
        media_gateway, "create_image", _bind_session(media_gateway.create_image, fal)
    )
    return tc.post(
        "/api/v1/media/images",
        json={"model": "openai/gpt-image-1", "prompt": "a red panda"},
    )


@pytest.fixture
def rago_sink(monkeypatch):
    metering.reset_for_tests()
    sink = RecordingSink()
    monkeypatch.setenv("RAILYARD_RAGO_URL", "http://rago.test")
    monkeypatch.setenv("RAILYARD_RAGO_API_KEY", "rago-key")
    monkeypatch.setenv("RAILYARD_RAGO_SUBSCRIPTION_ID", "sub_menivor")
    monkeypatch.setattr(metering, "_client_for", lambda settings: sink)
    yield sink
    metering.flush()
    metering.reset_for_tests()


def test_settled_media_job_emits_rago_usage(client, rago_sink):  # noqa: F811 - imported pytest fixture
    tc, _gs, monkeypatch = client
    resp = _generate_image(tc, monkeypatch)
    assert resp.status_code == 200, resp.text
    metering.flush()
    job_id = resp.json()["data"]["id"]
    by_tx = {e["transaction_id"]: e for e in rago_sink.events}
    render = by_tx[f"{job_id}:render"]
    credits = by_tx[f"{job_id}:settle"]
    assert render["code"] == "reel_generated"
    assert render["external_subscription_id"] == "sub_menivor"
    assert render["properties"]["job_kind"] == "media_image"
    assert credits["properties"]["credits"] == 40_000
    assert credits["precise_total_amount_cents"] == "4"


def test_media_settlement_survives_rago_failure(client, rago_sink):  # noqa: F811 - imported pytest fixture
    rago_sink.fail = True
    tc, gs, monkeypatch = client
    resp = _generate_image(tc, monkeypatch)
    assert resp.status_code == 200, resp.text
    from app.domains.wallet.service import WalletService

    with gs() as s:
        bal = WalletService(s).balance_view("u1")
    assert bal["reserved_micros"] == 0
    assert bal["available_micros"] == 100_000_000 - 40_000


def test_media_job_not_metered_when_rago_unset(client, monkeypatch):  # noqa: F811 - imported pytest fixture
    calls: list[dict] = []
    monkeypatch.setattr(metering, "_send", lambda sink, event: calls.append(event) or True)
    tc, _gs, mp = client
    resp = _generate_image(tc, mp)
    assert resp.status_code == 200, resp.text
    assert calls == []
