"""Unit tests for the Creem (creem.io) billing adapter.

All HTTP is mocked (``requests`` monkeypatched); no network is touched. The
webhook tests use a known secret and sign fixtures with the same HMAC-SHA256
scheme the adapter verifies.

Coverage:

* ``create_checkout_session`` posts to the documented endpoint with the
  ``x-api-key`` header, the plan's Creem product id, the success URL, and the
  full provenance metadata — including ``workspace_id`` when set (and omitting it
  entirely for a personal purchase). The hosted url + id are returned.
* ``verify_and_parse_webhook`` accepts a correctly-signed body and REJECTS a
  tampered body / bad signature / missing header.
* ``extract_completed_purchase`` pulls provenance (incl. ``workspace_id``) from a
  completed-checkout event and returns ``None`` for other event types.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest

from app.services.billing import creem_client

_WEBHOOK_SECRET = "whsec_creem_test_123"


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or json.dumps(self._payload)

    def json(self):
        return self._payload


def _sign(body: bytes, secret: str = _WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


@pytest.fixture()
def creem_env(monkeypatch):
    """Stub config + a capturing ``requests.post`` for one test."""
    captured: dict = {}

    def _fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers or {}
        captured["json"] = json or {}
        captured["timeout"] = timeout
        return _FakeResponse(
            status_code=200,
            payload={
                "id": "ch_test_123",
                "checkout_url": "https://creem.io/checkout/ch_test_123",
            },
        )

    fake_requests = SimpleNamespace(post=_fake_post)
    monkeypatch.setattr(creem_client, "requests", fake_requests)
    monkeypatch.setattr(
        creem_client,
        "_creem_config",
        lambda: {
            "api_key": "creem_sk_test",
            "webhook_secret": _WEBHOOK_SECRET,
            "success_url": "https://app.reelforge/ok",
        },
    )
    return captured


# --------------------------------------------------------------------------- #
# Checkout
# --------------------------------------------------------------------------- #
def test_create_checkout_builds_request_and_metadata(creem_env):
    plan = SimpleNamespace(creem_product_id="prod_pro", key="pro", credits=120)

    result = creem_client.create_checkout_session({"id": "user-1"}, plan)

    assert result == {
        "checkout_url": "https://creem.io/checkout/ch_test_123",
        "session_id": "ch_test_123",
    }
    # Endpoint + auth header.
    assert creem_env["url"] == "https://api.creem.io/v1/checkouts"
    assert creem_env["headers"]["x-api-key"] == "creem_sk_test"
    # Body carries the product id + success url + provenance metadata.
    body = creem_env["json"]
    assert body["product_id"] == "prod_pro"
    assert body["success_url"] == "https://app.reelforge/ok"
    assert body["metadata"] == {
        "user_id": "user-1",
        "plan_key": "pro",
        "credits": "120",
    }
    # Personal purchase must NOT carry a workspace_id key.
    assert "workspace_id" not in body["metadata"]


def test_create_checkout_includes_workspace_id_in_metadata(creem_env):
    plan = SimpleNamespace(creem_product_id="prod_pro", key="pro", credits=120)

    creem_client.create_checkout_session(
        {"id": "admin-1"}, plan, workspace_id="ws-1"
    )

    metadata = creem_env["json"]["metadata"]
    assert metadata["workspace_id"] == "ws-1"
    assert metadata["user_id"] == "admin-1"
    assert metadata["credits"] == "120"


def test_create_checkout_success_url_falls_back_to_stripe(monkeypatch):
    captured: dict = {}

    def _fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json or {}
        return _FakeResponse(
            payload={"id": "ch_1", "checkout_url": "https://creem.io/checkout/ch_1"}
        )

    monkeypatch.setattr(creem_client, "requests", SimpleNamespace(post=_fake_post))
    # creem section has no success_url -> stripe fallback is used.
    monkeypatch.setattr(
        creem_client,
        "_creem_config",
        lambda: {"api_key": "creem_sk_test", "webhook_secret": _WEBHOOK_SECRET},
    )
    monkeypatch.setattr(
        creem_client, "_stripe_config", lambda: {"success_url": "https://stripe/ok"}
    )

    plan = SimpleNamespace(creem_product_id="prod_s", key="starter", credits=30)
    creem_client.create_checkout_session({"id": "u1"}, plan)

    assert captured["json"]["success_url"] == "https://stripe/ok"


def test_create_checkout_requires_user_id(creem_env):
    plan = SimpleNamespace(creem_product_id="prod_pro", key="pro", credits=120)
    with pytest.raises(ValueError):
        creem_client.create_checkout_session({"id": ""}, plan)


def test_create_checkout_requires_product_id(creem_env):
    plan = SimpleNamespace(creem_product_id="", key="pro", credits=120)
    with pytest.raises(ValueError):
        creem_client.create_checkout_session({"id": "u1"}, plan)


def test_create_checkout_raises_on_error_status(monkeypatch):
    def _fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResponse(status_code=402, payload={}, text="payment required")

    monkeypatch.setattr(creem_client, "requests", SimpleNamespace(post=_fake_post))
    monkeypatch.setattr(
        creem_client,
        "_creem_config",
        lambda: {
            "api_key": "creem_sk_test",
            "webhook_secret": _WEBHOOK_SECRET,
            "success_url": "https://app/ok",
        },
    )

    plan = SimpleNamespace(creem_product_id="prod_pro", key="pro", credits=120)
    with pytest.raises(RuntimeError):
        creem_client.create_checkout_session({"id": "u1"}, plan)


# --------------------------------------------------------------------------- #
# Webhook signature verification
# --------------------------------------------------------------------------- #
@pytest.fixture()
def webhook_config(monkeypatch):
    monkeypatch.setattr(
        creem_client,
        "_creem_config",
        lambda: {"webhook_secret": _WEBHOOK_SECRET},
    )


def _completed_event_body(**overrides) -> bytes:
    event = {
        "eventType": "checkout.completed",
        "id": "evt_1",
        "object": {
            "id": "ch_test_123",
            "metadata": {
                "user_id": "user-1",
                "plan_key": "pro",
                "credits": "120",
            },
        },
    }
    event.update(overrides)
    return json.dumps(event).encode("utf-8")


def test_verify_accepts_correctly_signed_body(webhook_config):
    body = _completed_event_body()
    signature = _sign(body)

    event = creem_client.verify_and_parse_webhook(body, signature)

    assert event["eventType"] == "checkout.completed"
    assert event["object"]["id"] == "ch_test_123"


def test_verify_accepts_sha256_prefixed_signature(webhook_config):
    body = _completed_event_body()
    signature = "sha256=" + _sign(body)

    event = creem_client.verify_and_parse_webhook(body, signature)
    assert event["object"]["id"] == "ch_test_123"


def test_verify_rejects_tampered_body(webhook_config):
    body = _completed_event_body()
    signature = _sign(body)  # signature of the ORIGINAL body
    tampered = body.replace(b'"120"', b'"999999"')

    with pytest.raises(ValueError):
        creem_client.verify_and_parse_webhook(tampered, signature)


def test_verify_rejects_wrong_secret_signature(webhook_config):
    body = _completed_event_body()
    bad_signature = _sign(body, secret="not-the-secret")

    with pytest.raises(ValueError):
        creem_client.verify_and_parse_webhook(body, bad_signature)


def test_verify_rejects_missing_signature(webhook_config):
    body = _completed_event_body()
    with pytest.raises(ValueError):
        creem_client.verify_and_parse_webhook(body, "")


def test_verify_rejects_malformed_json_even_if_signed(webhook_config):
    body = b"not-json"
    signature = _sign(body)  # correctly signed, but body is not JSON
    with pytest.raises(ValueError):
        creem_client.verify_and_parse_webhook(body, signature)


def test_verify_raises_when_secret_unconfigured(monkeypatch):
    monkeypatch.setattr(creem_client, "_creem_config", lambda: {})
    with pytest.raises(RuntimeError):
        creem_client.verify_and_parse_webhook(b"{}", "sig")


# --------------------------------------------------------------------------- #
# Purchase extraction
# --------------------------------------------------------------------------- #
def test_extract_completed_purchase_personal():
    event = {
        "eventType": "checkout.completed",
        "object": {
            "id": "ch_x",
            "metadata": {
                "user_id": "user-1",
                "plan_key": "starter",
                "credits": "30",
            },
        },
    }

    purchase = creem_client.extract_completed_purchase(event)

    assert purchase == {
        "user_id": "user-1",
        "credits": 30,
        "session_id": "ch_x",
        "plan_key": "starter",
        "workspace_id": None,
    }


def test_extract_completed_purchase_surfaces_workspace_id():
    event = {
        "eventType": "checkout.completed",
        "object": {
            "id": "ch_ws",
            "metadata": {
                "user_id": "admin-1",
                "plan_key": "pro",
                "credits": "120",
                "workspace_id": "ws-1",
            },
        },
    }

    purchase = creem_client.extract_completed_purchase(event)

    assert purchase is not None
    assert purchase["workspace_id"] == "ws-1"
    assert purchase["user_id"] == "admin-1"
    assert purchase["credits"] == 120
    assert purchase["session_id"] == "ch_ws"


def test_extract_handles_stripe_style_data_object_envelope():
    event = {
        "type": "checkout.completed",
        "data": {
            "object": {
                "id": "ch_nested",
                "metadata": {
                    "user_id": "user-2",
                    "plan_key": "pro",
                    "credits": "120",
                },
            }
        },
    }

    purchase = creem_client.extract_completed_purchase(event)
    assert purchase is not None
    assert purchase["session_id"] == "ch_nested"
    assert purchase["user_id"] == "user-2"


def test_extract_returns_none_for_other_event_types():
    event = {
        "eventType": "checkout.created",
        "object": {"id": "ch_x", "metadata": {"user_id": "u", "credits": "30"}},
    }
    assert creem_client.extract_completed_purchase(event) is None


def test_extract_returns_none_when_credits_missing():
    event = {
        "eventType": "checkout.completed",
        "object": {"id": "ch_x", "metadata": {"user_id": "user-1"}},
    }
    assert creem_client.extract_completed_purchase(event) is None


def test_extract_falls_back_to_request_id_for_user():
    event = {
        "eventType": "checkout.completed",
        "object": {
            "id": "ch_x",
            "request_id": "user-9",
            "metadata": {"plan_key": "pro", "credits": "120"},
        },
    }

    purchase = creem_client.extract_completed_purchase(event)
    assert purchase is not None
    assert purchase["user_id"] == "user-9"
