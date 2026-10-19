"""Kling/fal.ai adapter — real queue protocol, retry, error taxonomy, download.

The requests.Session is faked (the socket is swapped) but the fal.ai queue protocol,
polling loop, retry/backoff, error mapping and streaming download are the real
production code paths.
"""

from __future__ import annotations

import pytest

from app.domains.routing.providers.kling_fal import KlingError, KlingFalAdapter


class _Resp:
    def __init__(self, status_code=200, body=None, headers=None, content=b""):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.headers = headers or {}
        self._content = content

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body

    @property
    def text(self):
        return str(self._body)

    def iter_content(self, chunk_size=1024):
        yield self._content

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeSession:
    """Records requests + replays a scripted response queue (keyed by URL substr)."""

    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    def request(self, method, url, *, headers=None, json=None, timeout=None):
        self.calls.append(
            {"method": method, "url": url, "headers": headers, "json": json}
        )
        return self._script.pop(0)

    def get(self, url, *, stream=False, timeout=None):
        self.calls.append({"method": "GET", "url": url, "stream": stream})
        return self._script.pop(0)


def _adapter(session, **kw):
    return KlingFalAdapter(
        api_key="fal-key",
        session=session,
        sleep=lambda s: None,
        poll_interval_s=0.0,
        **kw,
    )


def test_accepts_direct_fal_path_model_ref():
    # The catalog routes arbitrary fal video models by passing a full fal-ai/… path.
    sess = FakeSession([_Resp(200, {"request_id": "req-9"})])
    job = _adapter(sess, model="fal-ai/hunyuan-video").submit(
        prompt="a neon city", seconds=6
    )
    assert job.request_id == "req-9"
    assert sess.calls[0]["url"] == "https://queue.fal.run/fal-ai/hunyuan-video"


def test_rejects_non_fal_unknown_model():
    with pytest.raises(KlingError) as ei:
        KlingFalAdapter(api_key="k", model="not-a-real-model")
    assert ei.value.kind == "validation"


def test_submit_builds_real_fal_request():
    sess = FakeSession(
        [
            _Resp(
                200,
                {
                    "request_id": "req-1",
                    "status_url": "https://queue.fal.run/x/requests/req-1/status",
                    "response_url": "https://queue.fal.run/x/requests/req-1",
                },
            )
        ]
    )
    job = _adapter(sess).submit(
        prompt="a red panda astronaut", seconds=5, aspect_ratio="9:16"
    )
    assert job.request_id == "req-1"
    call = sess.calls[0]
    # Real fal.ai queue submit: POST to queue.fal.run/{model} with Key auth.
    assert call["method"] == "POST"
    assert (
        call["url"]
        == "https://queue.fal.run/fal-ai/kling-video/v1.6/standard/text-to-video"
    )
    assert call["headers"]["Authorization"] == "Key fal-key"
    assert call["json"] == {
        "prompt": "a red panda astronaut",
        "duration": "5",
        "aspect_ratio": "9:16",
    }


def test_poll_to_completed_fetches_result():
    sess = FakeSession(
        [
            _Resp(200, {"status": "IN_QUEUE", "queue_position": 3}),
            _Resp(200, {"status": "IN_PROGRESS"}),
            _Resp(200, {"status": "COMPLETED"}),
            _Resp(
                200, {"video": {"url": "https://cdn.fal/out.mp4", "file_size": 1234}}
            ),
        ]
    )
    from app.domains.routing.providers.kling_fal import KlingJob

    a = _adapter(sess)
    job = KlingJob(
        request_id="r", status_url="https://q/status", response_url="https://q/result"
    )
    a.poll(job)
    assert job.state == "IN_QUEUE" and job.queue_position == 3
    a.poll(job)
    assert job.state == "IN_PROGRESS"
    a.poll(job)
    assert job.is_terminal and job.video_url == "https://cdn.fal/out.mp4"


@pytest.mark.parametrize(
    ("upstream_state", "expected_state"),
    [("FAILED", "FAILED"), ("CANCELED", "CANCELLED")],
)
def test_poll_preserves_terminal_failure_and_message(upstream_state, expected_state):
    sess = FakeSession(
        [_Resp(200, {"status": upstream_state, "error": {"message": "moderated"}})]
    )
    from app.domains.routing.providers.kling_fal import KlingJob

    job = KlingJob(request_id="r", status_url="https://q/status", response_url="unused")
    _adapter(sess).poll(job)

    assert job.state == expected_state
    assert job.is_terminal is True
    assert job.failure == "moderated"
    assert len(sess.calls) == 1


def test_auth_error_is_fatal():
    sess = FakeSession([_Resp(401, {"detail": "invalid key"})])
    with pytest.raises(KlingError) as ei:
        _adapter(sess).submit(prompt="x")
    assert ei.value.kind == "auth" and ei.value.retryable is False


def test_validation_422_is_fatal_content_policy():
    sess = FakeSession([_Resp(422, {"detail": "content policy violation"})])
    with pytest.raises(KlingError) as ei:
        _adapter(sess).submit(prompt="x")
    assert ei.value.kind == "validation" and ei.value.status == 422


def test_rate_limit_retries_then_succeeds():
    sess = FakeSession(
        [
            _Resp(429, {}, headers={"Retry-After": "0"}),  # rate limited once
            _Resp(200, {"request_id": "req-2", "status_url": "s", "response_url": "r"}),
        ]
    )
    job = _adapter(sess).submit(prompt="x")
    assert job.request_id == "req-2"
    assert len(sess.calls) == 2  # retried after the 429


def test_submit_5xx_is_ambiguous_and_never_blindly_retried():
    sess = FakeSession([_Resp(500, {}), _Resp(200, {"request_id": "duplicate"})])
    with pytest.raises(KlingError) as ei:
        _adapter(sess, max_retries=2).submit(prompt="x")
    assert ei.value.kind == "transient" and ei.value.retryable is True
    assert ei.value.may_have_been_accepted is True
    assert len(sess.calls) == 1


def test_download_streams_to_disk(tmp_path):
    from app.domains.routing.providers.kling_fal import KlingJob

    sess = FakeSession([_Resp(200, content=b"FAKE-MP4-BYTES")])
    a = _adapter(sess)
    job = KlingJob(
        request_id="r",
        status_url="s",
        response_url="r",
        output={"video": {"url": "https://cdn.fal/out.mp4"}},
    )
    dest = tmp_path / "out.mp4"
    a.download(job, str(dest))
    assert dest.read_bytes() == b"FAKE-MP4-BYTES"


def test_generate_end_to_end(tmp_path):
    sess = FakeSession(
        [
            _Resp(
                200,
                {
                    "request_id": "r1",
                    "status_url": "https://q/status",
                    "response_url": "https://q/result",
                },
            ),
            _Resp(200, {"status": "COMPLETED"}),
            _Resp(200, {"video": {"url": "https://cdn.fal/out.mp4"}}),
            _Resp(200, content=b"MP4"),
        ]
    )
    res = _adapter(sess).generate(
        prompt="a cat", seconds=5, dest_path=str(tmp_path / "v.mp4")
    )
    assert res["video_url"] == "https://cdn.fal/out.mp4"
    assert res["cost_micros"] == 5 * 84_000  # 5s @ $0.084/s
    assert (tmp_path / "v.mp4").read_bytes() == b"MP4"


def test_missing_key_raises_auth():
    a = KlingFalAdapter(api_key="", session=FakeSession([]))
    with pytest.raises(KlingError) as ei:
        a.submit(prompt="x")
    assert ei.value.kind == "auth"
