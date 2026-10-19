"""Suno adapter — real Suno API v1 (Bearer, generate → record-info poll, code envelope)."""

from __future__ import annotations

import pytest

from app.domains.routing.providers.kling_fal import KlingError
from app.domains.routing.providers.suno_gen import SunoAdapter, SunoTask


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
    return SunoAdapter(api_key="sn-secret", session=session, sleep=lambda s: None, **kw)


def test_submit_uses_bearer_and_generate_endpoint():
    sess = FakeSession([_Resp(200, {"code": 200, "data": {"taskId": "t-1"}})])
    task = _adapter(sess).submit(prompt="lofi beat to study", instrumental=True)
    assert task.task_id == "t-1"
    call = sess.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://api.sunoapi.org/api/v1/generate"
    assert call["headers"]["Authorization"] == "Bearer sn-secret"
    assert call["json"]["model"] == "V4" and call["json"]["instrumental"] is True


def test_poll_success_extracts_audio_url():
    sess = FakeSession([
        _Resp(200, {"code": 200, "data": {"status": "PENDING"}}),
        _Resp(200, {"code": 200, "data": {"status": "SUCCESS", "response": {
            "sunoData": [{"audioUrl": "https://cdn.suno/song.mp3"}]}}}),
    ])
    a = _adapter(sess)
    t = SunoTask(task_id="t-1")
    a.poll(t); assert t.status == "PENDING" and not t.is_terminal
    a.poll(t)
    assert t.is_terminal and t.output_url == "https://cdn.suno/song.mp3"
    assert "record-info?taskId=t-1" in sess.calls[1]["url"]


def test_poll_failed_status_captures_reason():
    sess = FakeSession([_Resp(200, {"code": 200, "data": {
        "status": "SENSITIVE_WORD_ERROR", "errorMessage": "blocked lyrics"}})])
    t = SunoTask(task_id="t")
    _adapter(sess).poll(t)
    assert t.is_terminal and "blocked lyrics" in t.failure


def test_code_envelope_error_on_http_200():
    # Suno signals errors inside the {code,msg} envelope even on HTTP 200.
    sess = FakeSession([_Resp(200, {"code": 429, "msg": "rate limited"})])
    with pytest.raises(KlingError) as ei:
        _adapter(sess).submit(prompt="x")
    assert ei.value.kind == "rate_limit"


def test_prompt_required():
    with pytest.raises(KlingError) as ei:
        _adapter(FakeSession([])).submit(prompt="")
    assert ei.value.kind == "validation"


def test_auth_error_http():
    with pytest.raises(KlingError) as ei:
        _adapter(FakeSession([_Resp(401, {})])).submit(prompt="x")
    assert ei.value.kind == "auth"


def test_unknown_model_rejected():
    with pytest.raises(KlingError) as ei:
        SunoAdapter(api_key="k", model="suno-v9")
    assert ei.value.kind == "validation"


def test_cost():
    assert _adapter(FakeSession([])).cost_micros() == 80_000
    assert SunoAdapter(api_key="k", model="suno-v4.5", session=FakeSession([])).cost_micros() == 100_000
