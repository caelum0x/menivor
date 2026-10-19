"""Imagen image adapter — real Google :predict endpoint (key query param, base64)."""

from __future__ import annotations

import pytest

from app.domains.gateway.imagen_image import imagen_generate_image
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


def _gen(session, model="imagen-4.0-fast-generate-001", **kw):
    return imagen_generate_image(model, "a red panda", api_key="gk-secret", session=session,
                                 sleep=lambda s: None, **kw)


def test_predict_endpoint_key_query_and_data_url():
    sess = FakeSession([_Resp(200, {"predictions": [{"bytesBase64Encoded": "AAAA", "mimeType": "image/png"}]})])
    url = _gen(sess)
    assert url == "data:image/png;base64,AAAA"
    call = sess.calls[0]
    assert call["method"] == "POST"
    assert call["url"].startswith(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "imagen-4.0-fast-generate-001:predict")
    assert "key=gk-secret" in call["url"]
    assert call["json"]["instances"][0]["prompt"] == "a red panda"
    assert call["json"]["parameters"]["sampleCount"] == 1


def test_default_mime_when_absent():
    sess = FakeSession([_Resp(200, {"predictions": [{"bytesBase64Encoded": "BBBB"}]})])
    assert _gen(sess) == "data:image/png;base64,BBBB"


def test_no_predictions_is_provider_error():
    with pytest.raises(KlingError) as ei:
        _gen(FakeSession([_Resp(200, {"predictions": []})]))
    assert ei.value.kind == "provider"


def test_prompt_required():
    with pytest.raises(KlingError) as ei:
        imagen_generate_image("m", "", api_key="k", session=FakeSession([]))
    assert ei.value.kind == "validation"


def test_auth_error_maps():
    with pytest.raises(KlingError) as ei:
        _gen(FakeSession([_Resp(403, {"error": {"message": "API key invalid"}})]))
    assert ei.value.kind == "auth"


def test_bad_request_is_validation():
    with pytest.raises(KlingError) as ei:
        _gen(FakeSession([_Resp(400, {"error": {"message": "unsupported aspect ratio"}})]))
    assert ei.value.kind == "validation"


def test_rate_limit_retries_then_succeeds():
    sess = FakeSession([_Resp(429, {}),
                        _Resp(200, {"predictions": [{"bytesBase64Encoded": "CCCC"}]})])
    assert _gen(sess) == "data:image/png;base64,CCCC" and len(sess.calls) == 2
