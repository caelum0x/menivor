"""Fail-closed server entitlement checks for RevenueCat-protected actions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.config import config
from app.services.billing import revenuecat_client

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


def _payload(*, expires=None, grace=None, include=True):
    entitlements = {}
    if include:
        entitlements["pro"] = {
            "expires_date": expires,
            "grace_period_expires_date": grace,
            "product_identifier": "video_pro_monthly",
            "purchase_date": "2026-08-20T12:00:00Z",
        }
    return {"subscriber": {"entitlements": entitlements}}


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setitem(config.revenuecat, "secret_api_key", "sk_test_server_only")
    monkeypatch.setitem(config.revenuecat, "entitlement_id", "pro")
    monkeypatch.setitem(
        config.revenuecat, "api_base_url", "https://api.revenuecat.com/v1"
    )
    monkeypatch.setitem(config.revenuecat, "timeout_seconds", 5)


@pytest.mark.parametrize(
    ("payload", "active", "in_grace"),
    [
        (_payload(expires="2026-08-24T12:00:00Z"), True, False),
        (_payload(expires=None), True, False),
        (_payload(expires="2026-08-22T12:00:00Z"), False, False),
        (
            _payload(
                expires="2026-08-22T12:00:00Z",
                grace="2026-08-24T12:00:00Z",
            ),
            True,
            True,
        ),
        (_payload(include=False), False, False),
    ],
)
def test_evaluate_subscriber_entitlement(payload, active, in_grace):
    decision = revenuecat_client.evaluate_subscriber_entitlement(
        payload,
        app_user_id="user-1",
        entitlement_id="pro",
        now=NOW,
    )
    assert decision.active is active
    assert decision.in_grace_period is in_grace


def test_get_entitlement_uses_encoded_backend_user_and_secret_header():
    captured = {}

    def fake_get(url, *, headers, timeout):
        captured.update(url=url, headers=headers, timeout=timeout)
        return SimpleNamespace(
            status_code=200,
            json=lambda: _payload(expires="2026-08-24T12:00:00Z"),
        )

    decision = revenuecat_client.get_entitlement(
        "user/with space",
        now=NOW,
        request_get=fake_get,
    )
    assert decision.active is True
    assert captured["url"].endswith("/subscribers/user%2Fwith%20space")
    assert captured["headers"]["Authorization"] == "Bearer sk_test_server_only"
    assert captured["timeout"] == 5


def test_require_pro_denies_expired_customer(monkeypatch):
    monkeypatch.setattr(
        revenuecat_client,
        "get_entitlement",
        lambda _user_id: revenuecat_client.EntitlementDecision(
            active=False,
            entitlement_id="pro",
            app_user_id="user-1",
            expires_at=NOW - timedelta(days=1),
        ),
    )
    with pytest.raises(revenuecat_client.RevenueCatAccessDenied):
        revenuecat_client.require_pro_entitlement("user-1")


def test_missing_secret_fails_closed(monkeypatch):
    monkeypatch.setitem(config.revenuecat, "secret_api_key", "")
    with pytest.raises(revenuecat_client.RevenueCatConfigurationError):
        revenuecat_client.get_entitlement("user-1", request_get=lambda *_a, **_k: None)


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(status_code=503, json=lambda: {}),
        SimpleNamespace(status_code=200, json=lambda: {"unexpected": True}),
    ],
)
def test_provider_and_shape_errors_fail_closed(response):
    with pytest.raises(revenuecat_client.RevenueCatUnavailableError):
        revenuecat_client.get_entitlement(
            "user-1",
            now=NOW,
            request_get=lambda *_a, **_k: response,
        )
