"""Unit tests for the Polar (polar.sh) billing adapter.

Coverage (all HTTP mocked — no network, no real SDK):

* **Checkout** (:func:`polar_client.create_checkout_session`): POSTs to the
  documented ``/v1/checkouts/`` endpoint with the Bearer access token, the
  plan's ``polar_price_id``, ``success_url`` and provenance ``metadata`` —
  including ``workspace_id`` when funding a shared pool, and omitting it for a
  personal purchase.
* **Webhook verification** (:func:`polar_client.verify_and_parse_webhook`):
  Standard-Webhooks HMAC-SHA256 signatures are accepted when valid and rejected
  when the body is tampered or the timestamp is expired / missing headers.
* **Extraction** (:func:`polar_client.extract_completed_purchase`): pulls the
  ``{user_id, credits, checkout_id, plan_key, workspace_id}`` provenance out of
  ``order.created`` / ``checkout.updated(status=succeeded)`` events and returns
  ``None`` for anything else.
"""

from __future__ import annotations

import base64
import json
import time
from types import SimpleNamespace

import pytest

from app.services.billing import polar_client

# A known Standard-Webhooks secret (``whsec_`` + base64 body), used by the tests
# to *generate* valid signatures the module must then accept.
_SECRET = "whsec_" + base64.b64encode(b"reelforge-polar-test-secret").decode()


@pytest.fixture()
def polar_cfg(monkeypatch):
    """Point the adapter at a fully-configured, in-memory ``[polar]`` section."""
    cfg = {
        "access_token": "polar_pat_test_123",
        "webhook_secret": _SECRET,
        "success_url": "https://app.reelforge.test/billing/success",
        "base_url": "https://api.polar.sh",
    }
    monkeypatch.setattr(polar_client, "_polar_config", lambda: dict(cfg))
    return cfg


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or json.dumps(self._payload)

    def json(self):
        return self._payload


# --------------------------------------------------------------------------- #
# Checkout
# --------------------------------------------------------------------------- #
def _fake_requests(capture, response):
    """Return a requests stand-in that records the POST and returns ``response``."""

    def _post(url, json=None, headers=None, timeout=None):  # noqa: A002 - mirror API
        capture["url"] = url
        capture["json"] = json
        capture["headers"] = headers
        capture["timeout"] = timeout
        return response

    return SimpleNamespace(post=_post)


def test_create_checkout_posts_price_and_metadata(polar_cfg, monkeypatch):
    capture: dict = {}
    response = _FakeResponse(
        200,
        {"id": "checkout_abc", "url": "https://polar.sh/checkout/checkout_abc"},
    )
    monkeypatch.setattr(polar_client, "requests", _fake_requests(capture, response))

    user = {"id": "user-1", "email": "buyer@example.com"}
    plan = SimpleNamespace(polar_price_id="price_pro", key="pro", credits=120)

    result = polar_client.create_checkout_session(user, plan)

    assert result == {
        "checkout_url": "https://polar.sh/checkout/checkout_abc",
        "session_id": "checkout_abc",
    }
    # Correct documented endpoint + Bearer auth from config (no hardcoded secret).
    assert capture["url"] == "https://api.polar.sh/v1/checkouts/"
    assert capture["headers"]["Authorization"] == "Bearer polar_pat_test_123"
    body = capture["json"]
    assert body["product_price_id"] == "price_pro"
    assert body["success_url"] == "https://app.reelforge.test/billing/success"
    assert body["customer_email"] == "buyer@example.com"
    # Provenance metadata (values coerced to strings, matching the Stripe shape).
    assert body["metadata"] == {
        "user_id": "user-1",
        "plan_key": "pro",
        "credits": "120",
    }
    # Personal purchase -> no workspace key.
    assert "workspace_id" not in body["metadata"]


def test_create_checkout_includes_workspace_id(polar_cfg, monkeypatch):
    capture: dict = {}
    response = _FakeResponse(200, {"id": "chk_ws", "url": "https://polar.sh/c/chk_ws"})
    monkeypatch.setattr(polar_client, "requests", _fake_requests(capture, response))

    plan = SimpleNamespace(polar_price_id="price_pro", key="pro", credits=120)
    result = polar_client.create_checkout_session(
        {"id": "admin-1"}, plan, workspace_id="ws-1"
    )

    assert result["session_id"] == "chk_ws"
    md = capture["json"]["metadata"]
    assert md["workspace_id"] == "ws-1"
    assert md["user_id"] == "admin-1"
    assert md["credits"] == "120"


def test_create_checkout_requires_price_id(polar_cfg, monkeypatch):
    monkeypatch.setattr(
        polar_client, "requests", _fake_requests({}, _FakeResponse())
    )
    plan = SimpleNamespace(polar_price_id="", key="pro", credits=120)
    with pytest.raises(ValueError):
        polar_client.create_checkout_session({"id": "user-1"}, plan)


def test_create_checkout_raises_on_http_error(polar_cfg, monkeypatch):
    response = _FakeResponse(422, {"detail": "bad price"}, text="bad price")
    monkeypatch.setattr(
        polar_client, "requests", _fake_requests({}, response)
    )
    plan = SimpleNamespace(polar_price_id="price_pro", key="pro", credits=120)
    with pytest.raises(RuntimeError):
        polar_client.create_checkout_session({"id": "user-1"}, plan)


def test_create_checkout_raises_without_success_url(monkeypatch):
    monkeypatch.setattr(
        polar_client,
        "_polar_config",
        lambda: {"access_token": "tok"},  # no success_url
    )
    monkeypatch.setattr(
        polar_client, "requests", _fake_requests({}, _FakeResponse())
    )
    plan = SimpleNamespace(polar_price_id="price_pro", key="pro", credits=120)
    with pytest.raises(RuntimeError):
        polar_client.create_checkout_session({"id": "user-1"}, plan)


# --------------------------------------------------------------------------- #
# Webhook verification (Standard Webhooks)
# --------------------------------------------------------------------------- #
def _signed_headers(payload: bytes, *, secret=_SECRET, msg_id="msg_1", ts=None):
    """Build valid Standard-Webhooks headers for ``payload`` using ``secret``."""
    timestamp = str(int(time.time())) if ts is None else str(ts)
    signature = polar_client._sign_content(secret, msg_id, timestamp, payload)
    return {
        "webhook-id": msg_id,
        "webhook-timestamp": timestamp,
        "webhook-signature": f"v1,{signature}",
    }


def test_verify_accepts_valid_signature(polar_cfg):
    payload = json.dumps({"type": "order.created", "data": {"id": "o1"}}).encode()
    headers = _signed_headers(payload)

    event = polar_client.verify_and_parse_webhook(payload, headers)

    assert event["type"] == "order.created"
    assert event["data"]["id"] == "o1"


def test_verify_accepts_case_insensitive_headers(polar_cfg):
    payload = json.dumps({"type": "order.created", "data": {"id": "o1"}}).encode()
    headers = _signed_headers(payload)
    upper = {k.upper(): v for k, v in headers.items()}

    event = polar_client.verify_and_parse_webhook(payload, upper)
    assert event["type"] == "order.created"


def test_verify_rejects_tampered_payload(polar_cfg):
    payload = json.dumps({"type": "order.created", "data": {"id": "o1"}}).encode()
    headers = _signed_headers(payload)
    # Attacker mutates the body after the signature was computed.
    tampered = json.dumps({"type": "order.created", "data": {"id": "HACKED"}}).encode()

    with pytest.raises(ValueError):
        polar_client.verify_and_parse_webhook(tampered, headers)


def test_verify_rejects_wrong_secret(polar_cfg):
    payload = json.dumps({"type": "order.created", "data": {"id": "o1"}}).encode()
    other = "whsec_" + base64.b64encode(b"a-different-secret").decode()
    headers = _signed_headers(payload, secret=other)

    with pytest.raises(ValueError):
        polar_client.verify_and_parse_webhook(payload, headers)


def test_verify_rejects_expired_timestamp(polar_cfg):
    payload = json.dumps({"type": "order.created", "data": {"id": "o1"}}).encode()
    old = int(time.time()) - (10 * 60)  # 10 minutes ago -> outside ±5min window
    headers = _signed_headers(payload, ts=old)

    with pytest.raises(ValueError):
        polar_client.verify_and_parse_webhook(payload, headers)


def test_verify_rejects_missing_headers(polar_cfg):
    payload = b"{}"
    with pytest.raises(ValueError):
        polar_client.verify_and_parse_webhook(payload, {})


def test_verify_requires_configured_secret(monkeypatch):
    monkeypatch.setattr(polar_client, "_polar_config", lambda: {})
    with pytest.raises(RuntimeError):
        polar_client.verify_and_parse_webhook(b"{}", {"webhook-id": "x"})


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
def test_extract_order_created_pulls_provenance():
    event = {
        "type": "order.created",
        "data": {
            "id": "order_1",
            "checkout_id": "chk_1",
            "metadata": {
                "user_id": "user-1",
                "plan_key": "pro",
                "credits": "120",
            },
        },
    }
    purchase = polar_client.extract_completed_purchase(event)

    assert purchase == {
        "user_id": "user-1",
        "credits": 120,
        "checkout_id": "chk_1",
        "plan_key": "pro",
        "workspace_id": None,
    }


def test_extract_checkout_updated_succeeded_with_workspace():
    event = {
        "type": "checkout.updated",
        "data": {
            "id": "chk_ws",
            "status": "succeeded",
            "metadata": {
                "user_id": "admin-1",
                "plan_key": "pro",
                "credits": "120",
                "workspace_id": "ws-1",
            },
        },
    }
    purchase = polar_client.extract_completed_purchase(event)

    assert purchase is not None
    assert purchase["checkout_id"] == "chk_ws"
    assert purchase["workspace_id"] == "ws-1"
    assert purchase["user_id"] == "admin-1"
    assert purchase["credits"] == 120


def test_extract_ignores_non_succeeded_checkout_update():
    event = {
        "type": "checkout.updated",
        "data": {
            "id": "chk_open",
            "status": "open",
            "metadata": {"user_id": "user-1", "credits": "120"},
        },
    }
    assert polar_client.extract_completed_purchase(event) is None


def test_extract_ignores_unrelated_event():
    event = {"type": "subscription.created", "data": {"id": "sub_1"}}
    assert polar_client.extract_completed_purchase(event) is None


def test_extract_returns_none_without_user_or_credits():
    event = {
        "type": "order.created",
        "data": {"id": "order_1", "metadata": {"plan_key": "pro"}},
    }
    assert polar_client.extract_completed_purchase(event) is None


def test_extract_falls_back_to_nested_checkout_metadata():
    event = {
        "type": "order.created",
        "data": {
            "id": "order_2",
            "checkout": {
                "id": "chk_nested",
                "metadata": {
                    "user_id": "user-9",
                    "plan_key": "starter",
                    "credits": "30",
                },
            },
        },
    }
    purchase = polar_client.extract_completed_purchase(event)
    assert purchase is not None
    assert purchase["user_id"] == "user-9"
    assert purchase["credits"] == 30
    # No checkout_id/id on data.checkout_id -> falls back to the order id.
    assert purchase["checkout_id"] == "order_2"
