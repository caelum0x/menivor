"""MiniMax (Hailuo) adapter — real REST protocol incl. two-step file retrieve."""

from __future__ import annotations

import pytest

from app.domains.routing.providers.kling_fal import KlingError
from app.domains.routing.providers.minimax_gen import MinimaxAdapter, MinimaxTask


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
    return MinimaxAdapter(api_key="mm-secret", session=session, sleep=lambda s: None, **kw)


def test_submit_uses_bearer_and_video_generation():
    sess = FakeSession([_Resp(200, {"task_id": "t-1", "base_resp": {"status_code": 0}})])
    task = _adapter(sess).submit(prompt="a red panda", seconds=6)
    assert task.task_id == "t-1"
    call = sess.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://api.minimaxi.chat/v1/video_generation"
    assert call["headers"]["Authorization"] == "Bearer mm-secret"
    assert call["json"]["model"] == "MiniMax-Hailuo-02" and call["json"]["duration"] == 6


def test_poll_success_does_two_step_file_retrieve():
    sess = FakeSession([
        _Resp(200, {"status": "Processing", "base_resp": {"status_code": 0}}),
        _Resp(200, {"status": "Success", "file_id": "f-9", "base_resp": {"status_code": 0}}),
        _Resp(200, {"file": {"download_url": "https://cdn.mm/out.mp4"}, "base_resp": {"status_code": 0}}),
    ])
    a = _adapter(sess)
    t = MinimaxTask(task_id="t-1")
    a.poll(t); assert t.status == "Processing" and not t.is_terminal
    a.poll(t)
    assert t.is_terminal and t.file_id == "f-9" and t.output_url == "https://cdn.mm/out.mp4"
    # The third call is the file-retrieve step.
    assert sess.calls[2]["url"] == "https://api.minimaxi.chat/v1/files/retrieve?file_id=f-9"


def test_poll_fail_captures_reason():
    sess = FakeSession([_Resp(200, {"status": "Fail",
                                    "base_resp": {"status_code": 0, "status_msg": "unsafe prompt"}})])
    t = MinimaxTask(task_id="t")
    _adapter(sess).poll(t)
    assert t.status == "Fail" and "unsafe prompt" in t.failure


def test_base_resp_error_raises_even_on_http_200():
    # MiniMax signals auth failure inside base_resp with HTTP 200.
    sess = FakeSession([_Resp(200, {"base_resp": {"status_code": 1004, "status_msg": "bad token"}})])
    with pytest.raises(KlingError) as ei:
        _adapter(sess).submit(prompt="x")
    assert ei.value.kind == "auth"


def test_base_resp_rate_limit_kind():
    sess = FakeSession([_Resp(200, {"base_resp": {"status_code": 1002, "status_msg": "rate"}})])
    with pytest.raises(KlingError) as ei:
        _adapter(sess).submit(prompt="x")
    assert ei.value.kind == "rate_limit"


def test_prompt_or_image_required():
    with pytest.raises(KlingError) as ei:
        _adapter(FakeSession([])).submit(prompt="", image_url="")
    assert ei.value.kind == "validation"


def test_unknown_model_rejected():
    with pytest.raises(KlingError) as ei:
        MinimaxAdapter(api_key="k", model="hailuo-99")
    assert ei.value.kind == "validation"


def test_cost():
    assert _adapter(FakeSession([])).cost_micros(6) == 6 * 81_700
