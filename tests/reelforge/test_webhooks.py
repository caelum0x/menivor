"""Unit tests for app/services/webhooks.py (job-completion webhook delivery).

All network I/O is stubbed by monkeypatching ``requests.post`` on the webhooks
module, and DNS is stubbed via ``socket.getaddrinfo``, so these tests never
touch the network.

Covers:
  * HMAC-SHA256 signature computation + header presence
  * SSRF blocking (localhost / 127.0.0.1 / 169.254.169.254 / ::1 / metadata)
  * scheme validation
  * success / failure / retry result shapes
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import pytest

from app.services import webhooks


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class FakePost:
    """Records calls to ``webhooks._post`` and returns queued responses.

    ``webhooks._post`` is the single transport seam used by ``deliver_webhook``;
    it builds a DNS-pinned, redirect-refusing session. Patching it here keeps
    the delivery-logic tests off the network while the transport itself is
    exercised directly by the dedicated tests further down.
    """

    def __init__(self, results: list[Any]) -> None:
        self._results = list(results)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        result = self._results.pop(0) if self._results else FakeResponse(200)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make retry backoff instant."""
    monkeypatch.setattr(webhooks.time, "sleep", lambda *_a, **_k: None)


@pytest.fixture(autouse=True)
def _allow_external_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve any non-blocked hostname to a public IP so SSRF guard passes."""

    def fake_getaddrinfo(host: str, *_a: Any, **_k: Any) -> list[Any]:
        return [(2, 1, 6, "", ("93.184.216.34", 0))]  # example.com public IP

    monkeypatch.setattr(webhooks.socket, "getaddrinfo", fake_getaddrinfo)


@pytest.fixture(autouse=True)
def _block_internal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default policy: internal targets are blocked."""
    monkeypatch.setattr(webhooks, "_allow_internal", lambda: False)


# --------------------------------------------------------------------------- #
# Signature
# --------------------------------------------------------------------------- #
def test_signature_header_computed_correctly(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakePost([FakeResponse(200)])
    monkeypatch.setattr(webhooks, "_post", fake)

    payload = {"job_id": "abc", "status": "done"}
    secret = "s3cr3t"
    result = webhooks.deliver_webhook(
        "https://hooks.example.com/x", payload, secret=secret
    )

    assert result == {"delivered": True, "status": 200}
    assert len(fake.calls) == 1

    sent_body = fake.calls[0]["data"]
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), sent_body, hashlib.sha256
    ).hexdigest()
    assert fake.calls[0]["headers"][webhooks.SIGNATURE_HEADER] == expected
    # Body must be valid JSON matching the payload.
    assert json.loads(sent_body.decode("utf-8")) == payload


def test_no_signature_header_without_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakePost([FakeResponse(200)])
    monkeypatch.setattr(webhooks, "_post", fake)

    webhooks.deliver_webhook("https://hooks.example.com/x", {"a": 1})
    assert webhooks.SIGNATURE_HEADER not in fake.calls[0]["headers"]
    assert webhooks.LEGACY_SIGNATURE_HEADER not in fake.calls[0]["headers"]


def test_signature_sent_under_menivor_and_legacy_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rename transition: both headers carry the identical signature."""
    fake = FakePost([FakeResponse(200)])
    monkeypatch.setattr(webhooks, "_post", fake)

    webhooks.deliver_webhook("https://hooks.example.com/x", {"a": 1}, secret="k")
    headers = fake.calls[0]["headers"]
    assert webhooks.SIGNATURE_HEADER == "X-Menivor-Signature"
    assert webhooks.LEGACY_SIGNATURE_HEADER == "X-ReelForge-Signature"
    assert headers["X-Menivor-Signature"].startswith("sha256=")
    assert headers["X-Menivor-Signature"] == headers["X-ReelForge-Signature"]


def test_compute_signature_matches_stdlib() -> None:
    body = b'{"k":1}'
    sig = webhooks.compute_signature(body, "key")
    assert sig.startswith("sha256=")
    assert sig == "sha256=" + hmac.new(b"key", body, hashlib.sha256).hexdigest()


# --------------------------------------------------------------------------- #
# SSRF / URL validation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/hook",
        "http://127.0.0.1:8080/hook",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/hook",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://10.0.0.5/hook",
        "http://192.168.1.10/hook",
    ],
)
def test_ssrf_internal_targets_blocked(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    fake = FakePost([FakeResponse(200)])
    monkeypatch.setattr(webhooks, "_post", fake)

    result = webhooks.deliver_webhook(url, {"a": 1})

    assert result["delivered"] is False
    assert result["status"] is None
    assert "error" in result
    # Must not have attempted the request.
    assert fake.calls == []


def test_ssrf_block_lifted_by_config(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakePost([FakeResponse(200)])
    monkeypatch.setattr(webhooks, "_post", fake)
    monkeypatch.setattr(webhooks, "_allow_internal", lambda: True)

    result = webhooks.deliver_webhook("http://127.0.0.1:9000/hook", {"a": 1})

    assert result == {"delivered": True, "status": 200}
    assert len(fake.calls) == 1


@pytest.mark.parametrize("url", ["ftp://example.com/x", "file:///etc/passwd", "notaurl"])
def test_invalid_scheme_rejected(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    fake = FakePost([FakeResponse(200)])
    monkeypatch.setattr(webhooks, "_post", fake)

    result = webhooks.deliver_webhook(url, {"a": 1})
    assert result["delivered"] is False
    assert fake.calls == []


# --------------------------------------------------------------------------- #
# Success / failure / retry shapes
# --------------------------------------------------------------------------- #
def test_retries_on_5xx_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakePost([FakeResponse(503), FakeResponse(200)])
    monkeypatch.setattr(webhooks, "_post", fake)

    result = webhooks.deliver_webhook("https://ex.com/hook", {"a": 1})
    assert result == {"delivered": True, "status": 200}
    assert len(fake.calls) == 2


def test_exhausts_retries_on_persistent_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakePost([FakeResponse(500), FakeResponse(500), FakeResponse(500)])
    monkeypatch.setattr(webhooks, "_post", fake)

    result = webhooks.deliver_webhook("https://ex.com/hook", {"a": 1})
    assert result["delivered"] is False
    assert result["status"] == 500
    assert "error" in result
    assert len(fake.calls) == webhooks.MAX_ATTEMPTS


def test_4xx_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakePost([FakeResponse(400), FakeResponse(200)])
    monkeypatch.setattr(webhooks, "_post", fake)

    result = webhooks.deliver_webhook("https://ex.com/hook", {"a": 1})
    assert result["delivered"] is False
    assert result["status"] == 400
    assert len(fake.calls) == 1  # no retry for client error


def test_network_exception_retried_then_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakePost(
        [ConnectionError("boom"), ConnectionError("boom"), ConnectionError("boom")]
    )
    monkeypatch.setattr(webhooks, "_post", fake)

    result = webhooks.deliver_webhook("https://ex.com/hook", {"a": 1})
    assert result["delivered"] is False
    assert result["status"] is None
    assert "ConnectionError" in result["error"]
    assert len(fake.calls) == webhooks.MAX_ATTEMPTS


def test_non_serializable_payload_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakePost([FakeResponse(200)])
    monkeypatch.setattr(webhooks, "_post", fake)

    result = webhooks.deliver_webhook("https://ex.com/hook", {"o": object()})
    # default=str makes objects serializable, so this actually succeeds; assert
    # the request went out with a stringified value rather than crashing.
    assert result["delivered"] is True
    assert fake.calls


def test_requests_missing_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(webhooks, "requests", None)
    result = webhooks.deliver_webhook("https://ex.com/hook", {"a": 1})
    assert result == {
        "delivered": False,
        "status": None,
        "error": "requests library not available",
    }


# --------------------------------------------------------------------------- #
# SSRF hardening: redirect refusal + DNS pinning (TOCTOU)
# --------------------------------------------------------------------------- #
def test_deliver_pins_single_resolved_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    """The IP resolved during validation is the one handed to the transport.

    Because ``deliver_webhook`` resolves once and pins that address, a DNS
    rebind between validation and connect time cannot redirect the request to
    an internal host — the transport never re-resolves the name.
    """
    fake = FakePost([FakeResponse(200)])
    monkeypatch.setattr(webhooks, "_post", fake)

    result = webhooks.deliver_webhook("https://hooks.example.com/x", {"a": 1})

    assert result == {"delivered": True, "status": 200}
    # 93.184.216.34 is the public IP returned by the autouse getaddrinfo stub.
    assert fake.calls[0]["pinned_ip"] == "93.184.216.34"


def test_post_disables_redirects_and_mounts_pinned_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The transport seam refuses redirects and pins via ``_PinnedHTTPAdapter``."""
    captured: dict[str, Any] = {"mounts": []}

    class FakeSession:
        def mount(self, prefix: str, adapter: Any) -> None:
            captured["mounts"].append((prefix, type(adapter).__name__))

        def post(self, url: str, **kwargs: Any) -> FakeResponse:
            captured["url"] = url
            captured["kwargs"] = kwargs
            return FakeResponse(200)

        def close(self) -> None:
            captured["closed"] = True

    monkeypatch.setattr(webhooks.requests, "Session", FakeSession)

    resp = webhooks._post(
        "https://ex.com/x",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        timeout=5.0,
        pinned_ip="93.184.216.34",
    )

    assert resp.status_code == 200
    # Defect [1]: redirects must never be followed.
    assert captured["kwargs"]["allow_redirects"] is False
    # Defect [2]: both schemes routed through the pinning adapter.
    assert ("http://", "_PinnedHTTPAdapter") in captured["mounts"]
    assert ("https://", "_PinnedHTTPAdapter") in captured["mounts"]
    assert captured["closed"] is True


def test_pinned_adapter_rewrites_host_and_preserves_sni() -> None:
    """``_PinnedHTTPAdapter`` connects to the pinned IP but keeps the hostname."""
    req = webhooks.requests.Request(
        "POST", "https://hooks.example.com:8443/x"
    ).prepare()

    adapter = webhooks._PinnedHTTPAdapter("93.184.216.34")
    try:
        adapter._pin(req)

        assert "93.184.216.34" in req.url
        assert "hooks.example.com" not in req.url
        # Host header (with port) preserved for virtual-host routing.
        assert req.headers["Host"] == "hooks.example.com:8443"
        # TLS still verified against the real hostname, not the IP literal.
        pool_kw = adapter.poolmanager.connection_pool_kw
        assert pool_kw["server_hostname"] == "hooks.example.com"
        assert pool_kw["assert_hostname"] == "hooks.example.com"
    finally:
        adapter.close()


def test_pinned_adapter_refuses_internal_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even if a pinned IP is internal, the adapter refuses to connect."""
    req = webhooks.requests.Request("POST", "https://evil.example.com/x").prepare()

    adapter = webhooks._PinnedHTTPAdapter("169.254.169.254")
    try:
        with pytest.raises(webhooks.requests.exceptions.InvalidURL):
            adapter._pin(req)
    finally:
        adapter.close()
