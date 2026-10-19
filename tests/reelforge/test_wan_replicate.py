"""Wan 2.2 adapter — real Replicate prediction protocol (Bearer + status poll)."""

from __future__ import annotations

import pytest

from app.domains.routing.providers.kling_fal import KlingError
from app.domains.routing.providers.wan_replicate import WanAdapter, WanPrediction


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
    return WanAdapter(api_key="r8-secret", session=session, sleep=lambda s: None, **kw)


def test_submit_posts_to_official_model_predictions():
    sess = FakeSession([_Resp(201, {"id": "pred-1", "status": "starting",
                                    "urls": {"get": "https://api.replicate.com/v1/predictions/pred-1"}})])
    pred = _adapter(sess).submit(prompt="a red panda", seconds=5, aspect_ratio="9:16")
    assert pred.prediction_id == "pred-1" and pred.status == "starting"
    call = sess.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://api.replicate.com/v1/models/wan-video/wan-2.2-t2v-fast/predictions"
    assert call["headers"]["Authorization"] == "Bearer r8-secret"
    assert call["json"]["input"]["prompt"] == "a red panda"
    # 5s * 16fps = 80 frames, clamped up to the model's real floor of 81
    # (the Replicate wan-2.2 schema rejects num_frames < 81).
    assert call["json"]["input"]["num_frames"] == 81


def test_poll_reuses_get_url_and_extracts_output_string():
    sess = FakeSession([
        _Resp(200, {"status": "processing"}),
        _Resp(200, {"status": "succeeded", "output": "https://cdn.r8/out.mp4"}),
    ])
    a = _adapter(sess)
    p = WanPrediction(prediction_id="pred-1", get_url="https://api.replicate.com/v1/predictions/pred-1")
    a.poll(p); assert p.status == "processing" and not p.is_terminal
    a.poll(p)
    assert p.is_terminal and p.output_url == "https://cdn.r8/out.mp4"
    assert sess.calls[0]["url"] == "https://api.replicate.com/v1/predictions/pred-1"


def test_poll_output_list_takes_last():
    sess = FakeSession([_Resp(200, {"status": "succeeded",
                                    "output": ["https://cdn.r8/a.mp4", "https://cdn.r8/b.mp4"]})])
    p = WanPrediction(prediction_id="p")
    _adapter(sess).poll(p)
    assert p.output_url == "https://cdn.r8/b.mp4"


def test_poll_failed_captures_error():
    sess = FakeSession([_Resp(200, {"status": "failed", "error": "OOM on GPU"})])
    p = WanPrediction(prediction_id="p")
    _adapter(sess).poll(p)
    assert p.status == "failed" and "OOM" in p.failure


def test_auth_error():
    with pytest.raises(KlingError) as ei:
        _adapter(FakeSession([_Resp(401, {"detail": "invalid token"})])).submit(prompt="x")
    assert ei.value.kind == "auth"


def test_rate_limit_retries():
    sess = FakeSession([_Resp(429, {}), _Resp(201, {"id": "p2", "status": "starting"})])
    pred = _adapter(sess).submit(prompt="x")
    assert pred.prediction_id == "p2" and len(sess.calls) == 2


def test_prompt_or_image_required():
    with pytest.raises(KlingError) as ei:
        _adapter(FakeSession([])).submit(prompt="", image_url="")
    assert ei.value.kind == "validation"


def test_unknown_model_rejected():
    with pytest.raises(KlingError) as ei:
        WanAdapter(api_key="k", model="wan-99")
    assert ei.value.kind == "validation"


def test_accepts_direct_replicate_path():
    # The catalog routes arbitrary Replicate video models by owner/name path.
    sess = FakeSession([_Resp(201, {"id": "p9", "status": "starting"})])
    pred = _adapter(sess, model="tencent/hunyuan-video").submit(prompt="a neon city", seconds=6)
    assert pred.prediction_id == "p9"
    assert sess.calls[0]["url"] == "https://api.replicate.com/v1/models/tencent/hunyuan-video/predictions"


def test_cost():
    assert _adapter(FakeSession([])).cost_micros(5) == 5 * 60_000
