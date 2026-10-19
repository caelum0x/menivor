"""Wave 1 — production HTTP transport (``build_json_transport``).

Every adapter test injects a fake ``request_fn``, so the real httpx-backed
transport's error-normalization body is otherwise unexercised. These tests
monkeypatch ``httpx.request`` (never touching the network) and assert the
"a raw HTTP/SDK error never escapes -> normalized ProviderError with a retry
hint" contract, plus URL join, headers, and body decoding.
"""

from __future__ import annotations

import httpx
import pytest

from app.domains.routing.base import ProviderError
from app.domains.routing.providers._transport import build_json_transport


class _FakeResp:
    def __init__(self, status_code: int, *, content: bytes = b"", text: str = "",
                 json_value=None, json_raises: bool = False):
        self.status_code = status_code
        self.content = content
        self.text = text
        self._json_value = json_value
        self._json_raises = json_raises

    def json(self):
        if self._json_raises:
            raise ValueError("not JSON")
        return self._json_value


def _transport(**overrides):
    kwargs = dict(
        provider_key="testprov",
        base_url="https://api.example.com/",
        headers={"Authorization": "Bearer tok"},
    )
    kwargs.update(overrides)
    return build_json_transport(**kwargs)


def test_json_200_returns_parsed_dict(monkeypatch):
    captured = {}

    def fake_request(method, url, *, headers, json, timeout):
        captured.update(method=method, url=url, headers=headers, json=json, timeout=timeout)
        return _FakeResp(200, content=b'{"ok": true}', text='{"ok": true}', json_value={"ok": True})

    monkeypatch.setattr(httpx, "request", fake_request)
    transport = _transport()
    result = transport("POST", "/api/run", json={"a": 1})

    assert result == {"ok": True}
    # URL join: base_url + path (no doubled slash).
    assert captured["url"] == "https://api.example.com/api/run"
    assert captured["method"] == "POST"
    assert captured["json"] == {"a": 1}
    # Headers include the injected Authorization plus a JSON content type.
    assert captured["headers"]["Authorization"] == "Bearer tok"
    assert captured["headers"]["Content-Type"] == "application/json"


def test_5xx_raises_retryable_provider_error(monkeypatch):
    monkeypatch.setattr(
        httpx, "request",
        lambda *a, **k: _FakeResp(503, content=b"upstream down", text="upstream down"),
    )
    with pytest.raises(ProviderError) as ei:
        _transport()("GET", "/api/run")
    assert ei.value.retryable is True
    assert ei.value.provider_key == "testprov"


def test_4xx_raises_non_retryable_with_truncated_body(monkeypatch):
    long_body = "x" * 500
    monkeypatch.setattr(
        httpx, "request",
        lambda *a, **k: _FakeResp(400, content=long_body.encode(), text=long_body),
    )
    with pytest.raises(ProviderError) as ei:
        _transport()("GET", "/api/run")
    assert ei.value.retryable is False
    assert ei.value.provider_key == "testprov"
    # Body is truncated to 200 chars in the message.
    assert ("x" * 200) in str(ei.value)
    assert ("x" * 201) not in str(ei.value)


def test_network_exception_raises_retryable_provider_error(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "request", boom)
    with pytest.raises(ProviderError) as ei:
        _transport()("GET", "/api/run")
    assert ei.value.retryable is True
    assert ei.value.provider_key == "testprov"


def test_empty_body_returns_empty_dict(monkeypatch):
    monkeypatch.setattr(
        httpx, "request",
        lambda *a, **k: _FakeResp(204, content=b"", text=""),
    )
    assert _transport()("POST", "/api/run/r/cancel") == {}


def test_non_json_200_returns_raw_text(monkeypatch):
    monkeypatch.setattr(
        httpx, "request",
        lambda *a, **k: _FakeResp(200, content=b"plain text", text="plain text", json_raises=True),
    )
    assert _transport()("GET", "/api/run") == {"raw_text": "plain text"}
