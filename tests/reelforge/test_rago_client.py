"""Unit tests for :class:`RagoClient` and the best-effort settlement metering.

Covers the ``POST /api/v1/events`` envelope + Bearer auth, bare-int usage
properties, the 2xx parse and non-2xx / transport error mapping to
:class:`RagoClientError`, the ``RAGO_URL``/``RAGO_API_KEY`` config gate, and the
env-gated, never-raising :func:`meter_job_settlement` helper. No network and no
live rago — the transport is an in-memory ``httpx.MockTransport``.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.domains.wallet import rago_client
from app.domains.wallet.rago_client import (
    RagoClient,
    RagoClientError,
    meter_job_settlement,
    rago_client_from_config,
    rago_enabled,
    reset_rago_client_cache,
)


def make_rago_client(handler) -> RagoClient:
    """A :class:`RagoClient` backed by an in-memory MockTransport handler."""
    return RagoClient(
        "http://rago.test",
        "test-key",
        client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url="http://rago.test"
        ),
    )


@pytest.fixture()
def rago_config(monkeypatch):
    """Install a mutable fake ``config.rago`` dict and reset the client cache."""
    cfg = {
        "url": "",
        "api_key": "",
        "metric_code": "reel_ai_credits",
        "external_subscription_id": "",
        "timeout_seconds": 10,
    }

    class _Cfg:
        rago = cfg

    import app.config as app_config

    monkeypatch.setattr(app_config, "config", _Cfg, raising=False)
    reset_rago_client_cache()
    yield cfg
    reset_rago_client_cache()


# --------------------------------------------------------------------------- #
# record_event: envelope + auth + bare ints
# --------------------------------------------------------------------------- #
def test_record_event_posts_wrapped_envelope_with_bearer_and_bare_ints():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"event": {"lago_id": "e1"}})

    client = make_rago_client(handler)
    result = client.record_event(
        code="reel_ai_credits",
        transaction_id="job1:settle",
        external_subscription_id="ws_1",
        properties={"credits": 250_000},
        timestamp=1_700_000_000.0,
        precise_total_amount_cents="25",
    )

    assert result == {"event": {"lago_id": "e1"}}
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/events"
    assert captured["auth"] == "Bearer test-key"
    event = captured["body"]["event"]
    assert event["code"] == "reel_ai_credits"
    assert event["transaction_id"] == "job1:settle"
    assert event["external_subscription_id"] == "ws_1"
    assert event["properties"]["credits"] == 250_000
    assert isinstance(event["properties"]["credits"], int)
    assert event["timestamp"] == 1_700_000_000.0
    assert event["precise_total_amount_cents"] == "25"


def test_record_event_omits_optional_fields_when_absent():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"event": {}})

    client = make_rago_client(handler)
    client.record_event(
        code="reel_ai_credits",
        transaction_id="t1",
        external_subscription_id="sub",
    )
    event = captured["body"]["event"]
    assert "timestamp" not in event
    assert "precise_total_amount_cents" not in event
    assert event["properties"] == {}


# --------------------------------------------------------------------------- #
# Error mapping
# --------------------------------------------------------------------------- #
def test_non_2xx_maps_to_rago_client_error_with_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error": "value_is_invalid"})

    client = make_rago_client(handler)
    with pytest.raises(RagoClientError) as ei:
        client.record_event(
            code="c", transaction_id="t", external_subscription_id="s"
        )
    assert ei.value.status_code == 422
    assert "value_is_invalid" in ei.value.message


def test_transport_error_maps_to_502():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = make_rago_client(handler)
    with pytest.raises(RagoClientError) as ei:
        client.record_event(
            code="c", transaction_id="t", external_subscription_id="s"
        )
    assert ei.value.status_code == 502
    assert "unreachable" in ei.value.message


# --------------------------------------------------------------------------- #
# Config gate
# --------------------------------------------------------------------------- #
def test_disabled_when_url_unset(rago_config):
    assert rago_enabled() is False
    assert rago_client_from_config() is None


def test_enabled_returns_cached_client(rago_config):
    rago_config["url"] = "http://rago.test"
    rago_config["api_key"] = "k"
    assert rago_enabled() is True
    first = rago_client_from_config()
    second = rago_client_from_config()
    assert isinstance(first, RagoClient)
    assert first is second  # process-cached


# --------------------------------------------------------------------------- #
# meter_job_settlement: env-gated, best-effort, never raises
# --------------------------------------------------------------------------- #
def test_meter_is_noop_when_disabled(rago_config):
    # url/api_key unset => rago_client_from_config() is None => logged no-op.
    assert (
        meter_job_settlement(
            job_id="job1", actual_micros=100_000, owner_key="ws_1"
        )
        is False
    )


def test_meter_sends_expected_event_on_success(monkeypatch, rago_config):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"event": {"lago_id": "e1"}})

    monkeypatch.setattr(
        rago_client, "rago_client_from_config", lambda: make_rago_client(handler)
    )
    ok = meter_job_settlement(
        job_id="job1",
        actual_micros=250_000,
        owner_key="ws_1",
        settlement_rail="mint",
    )
    assert ok is True
    assert captured["path"] == "/api/v1/events"
    event = captured["body"]["event"]
    assert event["code"] == "reel_ai_credits"
    assert event["transaction_id"] == "job1:settle"
    assert event["external_subscription_id"] == "ws_1"
    assert event["properties"]["credits"] == 250_000
    assert event["properties"]["settlement_rail"] == "mint"
    # 250_000 micros / 10_000 == 25 cents.
    assert event["precise_total_amount_cents"] == "25"


def test_meter_prefers_configured_subscription_over_owner(monkeypatch, rago_config):
    rago_config["external_subscription_id"] = "sub_fixed"
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"event": {}})

    monkeypatch.setattr(
        rago_client, "rago_client_from_config", lambda: make_rago_client(handler)
    )
    meter_job_settlement(job_id="j", actual_micros=1, owner_key="ws_ignored")
    assert captured["body"]["event"]["external_subscription_id"] == "sub_fixed"


def test_meter_swallows_transport_error_and_returns_false(monkeypatch, rago_config):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    monkeypatch.setattr(
        rago_client, "rago_client_from_config", lambda: make_rago_client(handler)
    )
    # A failing rago must never raise out of settlement — only return False.
    assert (
        meter_job_settlement(
            job_id="job1", actual_micros=100_000, owner_key="ws_1"
        )
        is False
    )


def test_meter_skips_when_no_subscription_id(monkeypatch, rago_config):
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"event": {}})

    monkeypatch.setattr(
        rago_client, "rago_client_from_config", lambda: make_rago_client(handler)
    )
    # No owner_key and no configured subscription => nothing to meter against.
    assert meter_job_settlement(job_id="j", actual_micros=1, owner_key="") is False
    assert calls == []
