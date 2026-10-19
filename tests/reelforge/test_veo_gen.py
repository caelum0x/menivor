"""Veo adapter — real Google Generative Language API protocol.

Exercises the real production code paths (submit → long-running operation →
poll → extract uri, error taxonomy, retries) with only the ``requests.Session``
faked. Verifies Veo's distinguishing traits: API-key query-param auth, the
``:predictLongRunning`` submit shape, and the LRO ``{done, response}`` poll.
"""

from __future__ import annotations

import pytest

from app.domains.routing.providers.kling_fal import KlingError
from app.domains.routing.providers.veo_gen import VeoAdapter, VeoOperation


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


def _adapter(session, **kw):
    return VeoAdapter(api_key="gk-secret", session=session, sleep=lambda s: None, **kw)


def test_submit_uses_predict_long_running_and_key_query():
    sess = FakeSession([_Resp(200, {"name": "models/veo-3.1/operations/abc"})])
    op = _adapter(sess).submit(prompt="a red panda surfing", seconds=8, aspect_ratio="9:16")
    assert op.name == "models/veo-3.1/operations/abc"
    call = sess.calls[0]
    assert call["method"] == "POST"
    assert call["url"].startswith(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "veo-3.1-generate-preview:predictLongRunning")
    # API key rides as a query param, not a header (Google style).
    assert "key=gk-secret" in call["url"]
    assert call["json"]["instances"][0]["prompt"] == "a red panda surfing"
    assert call["json"]["parameters"]["aspectRatio"] == "9:16"
    assert call["json"]["parameters"]["durationSeconds"] == 8


def test_submit_with_image_sets_image_uri():
    sess = FakeSession([_Resp(200, {"name": "models/veo-3.1/operations/x"})])
    _adapter(sess).submit(prompt="pan up", image_url="https://img/first.png")
    assert sess.calls[0]["json"]["instances"][0]["image"]["imageUri"] == "https://img/first.png"


def test_poll_pending_then_done_extracts_uri():
    sess = FakeSession([
        _Resp(200, {"done": False}),
        _Resp(200, {"done": True, "response": {"generateVideoResponse": {
            "generatedSamples": [{"video": {"uri": "https://cdn.g/out.mp4"}}]}}}),
    ])
    a = _adapter(sess)
    op = VeoOperation(name="models/veo-3.1/operations/abc")
    a.poll(op)
    assert not op.is_terminal
    a.poll(op)
    assert op.is_terminal and op.output_url == "https://cdn.g/out.mp4"
    # Poll GETs the operation by name with the key query param.
    assert sess.calls[1]["method"] == "GET"
    assert "operations/abc" in sess.calls[1]["url"] and "key=gk-secret" in sess.calls[1]["url"]


def test_poll_done_with_error_captured():
    sess = FakeSession([_Resp(200, {"done": True, "error": {"message": "safety blocked"}})])
    op = VeoOperation(name="models/veo-3.1/operations/e")
    _adapter(sess).poll(op)
    assert op.is_terminal and "safety blocked" in op.error and op.output_url == ""


def test_submit_requires_prompt_or_image():
    with pytest.raises(KlingError) as ei:
        _adapter(FakeSession([])).submit(prompt="", image_url="")
    assert ei.value.kind == "validation"


def test_auth_error_maps_kind():
    with pytest.raises(KlingError) as ei:
        _adapter(FakeSession([_Resp(403, {"error": {"message": "API key invalid"}})])).submit(
            prompt="x")
    assert ei.value.kind == "auth"


def test_bad_request_is_validation():
    with pytest.raises(KlingError) as ei:
        _adapter(FakeSession([_Resp(400, {"error": {"message": "durationSeconds too large"}})])).submit(
            prompt="x")
    assert ei.value.kind == "validation"


def test_rate_limit_retries_then_succeeds():
    sess = FakeSession([_Resp(429, {}), _Resp(200, {"name": "models/veo-3.1/operations/ok"})])
    op = _adapter(sess).submit(prompt="x")
    assert op.name == "models/veo-3.1/operations/ok" and len(sess.calls) == 2


def test_unknown_model_rejected():
    with pytest.raises(KlingError) as ei:
        VeoAdapter(api_key="k", model="veo-9")
    assert ei.value.kind == "validation"


def test_cost_uses_per_second_price():
    assert _adapter(FakeSession([])).cost_micros(8) == 8 * 400_000
    lite = VeoAdapter(api_key="k", model="veo-3.1-lite", session=FakeSession([]))
    assert lite.cost_micros(8) == 8 * 150_000
