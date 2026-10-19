"""Replicate image adapter — real predictions API with Prefer: wait (sync)."""

from __future__ import annotations

import pytest

from app.domains.gateway.replicate_image import replicate_generate_image
from app.domains.routing.providers.kling_fal import KlingError


class _Resp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}
        self.headers = {}

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    def request(self, method, url, *, headers=None, json=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "json": json})
        return self._script.pop(0)


def _gen(session, model="black-forest-labs/flux-schnell", **kw):
    return replicate_generate_image(model, "a red panda", api_key="r8-secret", session=session,
                                    sleep=lambda s: None, **kw)


def test_prefer_wait_returns_output_inline():
    sess = FakeSession([_Resp(201, {"id": "p1", "status": "succeeded",
                                    "output": ["https://r8/out.png"]})])
    url = _gen(sess)
    assert url == "https://r8/out.png"
    call = sess.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://api.replicate.com/v1/models/black-forest-labs/flux-schnell/predictions"
    assert call["headers"]["Authorization"] == "Bearer r8-secret"
    assert call["headers"]["Prefer"] == "wait"
    assert call["json"]["input"]["prompt"] == "a red panda"


def test_output_string_supported():
    sess = FakeSession([_Resp(200, {"status": "succeeded", "output": "https://r8/single.png"})])
    assert _gen(sess) == "https://r8/single.png"


def test_polls_when_not_terminal_after_wait():
    sess = FakeSession([
        _Resp(201, {"id": "p1", "status": "processing",
                    "urls": {"get": "https://api.replicate.com/v1/predictions/p1"}}),
        _Resp(200, {"status": "processing", "urls": {"get": "https://api.replicate.com/v1/predictions/p1"}}),
        _Resp(200, {"status": "succeeded", "output": ["https://r8/late.png"]}),
    ])
    assert _gen(sess) == "https://r8/late.png"
    assert sess.calls[1]["method"] == "GET"


def test_failed_status_raises():
    sess = FakeSession([_Resp(201, {"status": "failed", "error": "NSFW"})])
    with pytest.raises(KlingError) as ei:
        _gen(sess)
    assert ei.value.kind == "provider"


def test_prompt_required():
    with pytest.raises(KlingError) as ei:
        replicate_generate_image("m", "", api_key="k", session=FakeSession([]))
    assert ei.value.kind == "validation"


def test_missing_key_is_auth():
    with pytest.raises(KlingError) as ei:
        replicate_generate_image("m", "x", api_key="", session=FakeSession([]))
    assert ei.value.kind == "auth"


def test_auth_error_maps():
    with pytest.raises(KlingError) as ei:
        _gen(FakeSession([_Resp(401, {"detail": "bad token"})]))
    assert ei.value.kind == "auth"
