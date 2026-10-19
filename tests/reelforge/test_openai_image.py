"""OpenAI image adapter — real OpenAI Images API (Bearer, url or b64 result)."""

from __future__ import annotations

import pytest

from app.domains.gateway.openai_image import openai_generate_image
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


def _gen(session, model="gpt-image-1", **kw):
    return openai_generate_image(model, "a red panda", api_key="sk-secret", session=session,
                                 sleep=lambda s: None, **kw)


def test_hosted_url_returned_and_bearer_endpoint():
    sess = FakeSession([_Resp(200, {"data": [{"url": "https://oai/img.png"}]})])
    url = _gen(sess, model="dall-e-3")
    assert url == "https://oai/img.png"
    call = sess.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://api.openai.com/v1/images/generations"
    assert call["headers"]["Authorization"] == "Bearer sk-secret"
    assert call["json"]["model"] == "dall-e-3" and call["json"]["prompt"] == "a red panda"


def test_b64_becomes_data_url():
    sess = FakeSession([_Resp(200, {"data": [{"b64_json": "AAAABBBB"}]})])
    url = _gen(sess)
    assert url == "data:image/png;base64,AAAABBBB"


def test_prompt_required():
    with pytest.raises(KlingError) as ei:
        openai_generate_image("gpt-image-1", "", api_key="sk", session=FakeSession([]))
    assert ei.value.kind == "validation"


def test_missing_key_is_auth():
    with pytest.raises(KlingError) as ei:
        openai_generate_image("gpt-image-1", "x", api_key="", session=FakeSession([]))
    assert ei.value.kind == "auth"


def test_auth_error_maps():
    with pytest.raises(KlingError) as ei:
        _gen(FakeSession([_Resp(401, {"error": {"message": "bad key"}})]))
    assert ei.value.kind == "auth"


def test_bad_request_is_validation():
    with pytest.raises(KlingError) as ei:
        _gen(FakeSession([_Resp(400, {"error": {"message": "content policy"}})]))
    assert ei.value.kind == "validation"


def test_rate_limit_retries_then_succeeds():
    sess = FakeSession([_Resp(429, {}), _Resp(200, {"data": [{"url": "https://oai/ok.png"}]})])
    assert _gen(sess) == "https://oai/ok.png" and len(sess.calls) == 2


def test_empty_data_is_provider_error():
    with pytest.raises(KlingError) as ei:
        _gen(FakeSession([_Resp(200, {"data": []})]))
    assert ei.value.kind == "provider"
