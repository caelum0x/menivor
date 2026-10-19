"""Luma adapter — real Luma Dream Machine REST protocol (Bearer + state poll)."""

from __future__ import annotations

import pytest

from app.domains.routing.providers.kling_fal import KlingError
from app.domains.routing.providers.luma_gen import LumaAdapter, LumaGeneration


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
    return LumaAdapter(api_key="lm-secret", session=session, sleep=lambda s: None, **kw)


def test_submit_uses_bearer_and_generations_endpoint():
    sess = FakeSession([_Resp(200, {"id": "gen-1", "state": "queued"})])
    gen = _adapter(sess).submit(prompt="a red panda", seconds=5, aspect_ratio="9:16")
    assert gen.generation_id == "gen-1" and gen.state == "queued"
    call = sess.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://api.lumalabs.ai/dream-machine/v1/generations"
    assert call["headers"]["Authorization"] == "Bearer lm-secret"
    assert call["json"]["model"] == "ray-2"
    assert call["json"]["duration"] == "5s" and call["json"]["aspect_ratio"] == "9:16"


def test_submit_image_sets_keyframe():
    sess = FakeSession([_Resp(200, {"id": "g", "state": "queued"})])
    _adapter(sess).submit(prompt="pan", image_url="https://img/first.png")
    assert sess.calls[0]["json"]["keyframes"]["frame0"]["url"] == "https://img/first.png"


def test_poll_dreaming_then_completed_extracts_video():
    sess = FakeSession([
        _Resp(200, {"state": "dreaming"}),
        _Resp(200, {"state": "completed", "assets": {"video": "https://cdn.luma/out.mp4"}}),
    ])
    a = _adapter(sess)
    g = LumaGeneration(generation_id="gen-1")
    a.poll(g); assert g.state == "dreaming" and not g.is_terminal
    a.poll(g)
    assert g.is_terminal and g.output_url == "https://cdn.luma/out.mp4"
    assert sess.calls[1]["method"] == "GET" and "generations/gen-1" in sess.calls[1]["url"]


def test_poll_failed_captures_reason():
    sess = FakeSession([_Resp(200, {"state": "failed", "failure_reason": "moderation"})])
    g = LumaGeneration(generation_id="g")
    _adapter(sess).poll(g)
    assert g.state == "failed" and "moderation" in g.failure


def test_prompt_or_image_required():
    with pytest.raises(KlingError) as ei:
        _adapter(FakeSession([])).submit(prompt="", image_url="")
    assert ei.value.kind == "validation"


def test_auth_error():
    with pytest.raises(KlingError) as ei:
        _adapter(FakeSession([_Resp(401, {"detail": "bad key"})])).submit(prompt="x")
    assert ei.value.kind == "auth"


def test_rate_limit_retries():
    sess = FakeSession([_Resp(429, {}), _Resp(200, {"id": "g2", "state": "queued"})])
    gen = _adapter(sess).submit(prompt="x")
    assert gen.generation_id == "g2" and len(sess.calls) == 2


def test_unknown_model_rejected():
    with pytest.raises(KlingError) as ei:
        LumaAdapter(api_key="k", model="ray-9")
    assert ei.value.kind == "validation"


def test_cost():
    assert _adapter(FakeSession([])).cost_micros(5) == 5 * 320_000
    flash = LumaAdapter(api_key="k", model="ray-flash-2", session=FakeSession([]))
    assert flash.cost_micros(5) == 5 * 120_000
