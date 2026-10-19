"""Runway adapter — real Runway REST protocol (auth+version headers, task poll)."""

from __future__ import annotations

import pytest

from app.domains.routing.providers.kling_fal import KlingError
from app.domains.routing.providers.runway_gen import RunwayAdapter, RunwayTask


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
    return RunwayAdapter(api_key="rw-secret", session=session, sleep=lambda s: None, **kw)


def test_submit_uses_runway_headers_and_endpoint():
    sess = FakeSession([_Resp(200, {"id": "task-1"})])
    task = _adapter(sess).submit(prompt="a dolly-in shot", image_url="https://img/first.png", seconds=5)
    assert task.task_id == "task-1"
    call = sess.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://api.dev.runwayml.com/v1/image_to_video"
    assert call["headers"]["Authorization"] == "Bearer rw-secret"
    assert call["headers"]["X-Runway-Version"] == "2024-11-06"
    assert call["json"]["model"] == "gen4_turbo" and call["json"]["promptImage"] == "https://img/first.png"


def test_poll_succeeded_extracts_output():
    sess = FakeSession([
        _Resp(200, {"status": "RUNNING"}),
        _Resp(200, {"status": "SUCCEEDED", "output": ["https://cdn.runway/out.mp4"]}),
    ])
    a = _adapter(sess)
    t = RunwayTask(task_id="t")
    a.poll(t); assert t.state == "RUNNING" and not t.is_terminal
    a.poll(t)
    assert t.is_terminal and t.output_url == "https://cdn.runway/out.mp4"


def test_poll_failed_captures_reason():
    sess = FakeSession([_Resp(200, {"status": "FAILED", "failure": "content moderation"})])
    t = RunwayTask(task_id="t")
    _adapter(sess).poll(t)
    assert t.state == "FAILED" and "content moderation" in t.failure


def test_image_required():
    with pytest.raises(KlingError) as ei:
        _adapter(FakeSession([])).submit(prompt="x", image_url="")
    assert ei.value.kind == "validation"


def test_auth_error():
    with pytest.raises(KlingError) as ei:
        _adapter(FakeSession([_Resp(401, {"error": "bad key"})])).submit(
            prompt="x", image_url="https://i/p.png")
    assert ei.value.kind == "auth"


def test_rate_limit_retries():
    sess = FakeSession([_Resp(429, {}), _Resp(200, {"id": "t2"})])
    task = _adapter(sess).submit(prompt="x", image_url="https://i/p.png")
    assert task.task_id == "t2" and len(sess.calls) == 2


def test_cost():
    assert _adapter(FakeSession([])).cost_micros(5) == 5 * 500_000
