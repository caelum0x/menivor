"""P6 async-GPU render envelope + RunPod backend + webhook verification."""

from __future__ import annotations

import pytest

from app.services import render
from app.services.render import envelope as env
from app.services.render.backends.base import BackendError
from app.services.render.backends.runpod import RunPodBackend


class _Resp:
    def __init__(self, status_code=200, body=None, headers=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.headers = headers or {}

    def json(self):
        return self._body

    @property
    def text(self):
        return str(self._body)


class FakeTransport:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def request(self, method, url, *, headers=None, params=None, json=None):
        self.calls.append({"method": method, "url": url, "json": json})
        return self._responses.pop(0)


# --------------------------------------------------------------------------- #
# State machine
# --------------------------------------------------------------------------- #
def test_legal_and_illegal_transitions():
    job = env.RenderJob(id="j1", backend="runpod")
    assert job.state == env.IN_QUEUE
    running = env.transition(job, env.IN_PROGRESS, progress=0.3)
    assert running.state == env.IN_PROGRESS and running.progress == pytest.approx(0.3)
    done = env.transition(running, env.COMPLETED, output_refs=("r2://out.mp4",))
    assert done.is_done and done.progress == 1.0 and done.output_refs == ("r2://out.mp4",)
    # No moves out of a terminal state.
    with pytest.raises(env.EnvelopeError):
        env.transition(done, env.IN_PROGRESS)


def test_terminal_reentry_is_idempotent():
    done = env.transition(env.RenderJob(id="j", backend="b"), env.COMPLETED)
    assert env.transition(done, env.COMPLETED) is done  # duplicate webhook/poll


def test_progress_is_monotonic_while_running():
    job = env.transition(env.RenderJob(id="j", backend="b"), env.IN_PROGRESS, progress=0.6)
    # A later poll reporting lower progress never regresses.
    assert env.transition(job, env.IN_PROGRESS, progress=0.2).progress == pytest.approx(0.6)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("IN_QUEUE", env.IN_QUEUE), ("queued", env.IN_QUEUE),
        ("RUNNING", env.IN_PROGRESS), ("processing", env.IN_PROGRESS),
        ("succeeded", env.COMPLETED), ("COMPLETE", env.COMPLETED),
        ("error", env.FAILED), ("timed_out", env.FAILED),
        ("canceled", env.CANCELLED),
        ("something-weird", env.IN_PROGRESS),  # unknown => treat as running
    ],
)
def test_normalize_state(raw, expected):
    assert env.normalize_state(raw) == expected


# --------------------------------------------------------------------------- #
# RunPod backend (real API contract over a fake transport)
# --------------------------------------------------------------------------- #
def test_runpod_submit_then_poll_to_completed():
    backend = RunPodBackend(endpoint_id="ep1", api_key="key")
    submit_t = FakeTransport([_Resp(200, {"id": "rp-1", "status": "IN_QUEUE"})])
    job = backend.submit({"job_id": "job-9", "workflow_version": "wan_i2v@1"}, transport=submit_t)
    assert job.provider_ref == "rp-1"
    assert job.state == env.IN_QUEUE
    assert submit_t.calls[0]["url"] == "https://api.runpod.ai/v2/ep1/run"
    assert submit_t.calls[0]["json"] == {"input": {"job_id": "job-9", "workflow_version": "wan_i2v@1"}}

    poll_t = FakeTransport([
        _Resp(200, {"status": "IN_PROGRESS"}),
        _Resp(200, {"status": "COMPLETED", "output": {"video_url": "https://cdn/out.mp4"}}),
    ])
    job = backend.poll(job, transport=poll_t)
    assert job.state == env.IN_PROGRESS
    job = backend.poll(job, transport=poll_t)
    assert job.is_done and job.output_refs == ("https://cdn/out.mp4",)


def test_runpod_poll_failure_carries_error():
    backend = RunPodBackend(endpoint_id="ep1", api_key="key")
    job = env.RenderJob(id="j", backend="runpod", state=env.IN_PROGRESS, provider_ref="rp-2")
    t = FakeTransport([_Resp(200, {"status": "FAILED", "error": "cuda oom"})])
    out = backend.poll(job, transport=t)
    assert out.state == env.FAILED and "cuda oom" in out.error


def test_runpod_submit_http_error_raises():
    backend = RunPodBackend(endpoint_id="ep1", api_key="key")
    t = FakeTransport([_Resp(500, {"error": "boom"})])
    with pytest.raises(BackendError) as ei:
        backend.submit({"job_id": "x"}, transport=t)
    assert ei.value.retryable is True


def test_runpod_worker_comfyui_output_shapes():
    backend = RunPodBackend(endpoint_id="ep1", api_key="key")
    job = env.RenderJob(id="j", backend="runpod", state=env.IN_PROGRESS, provider_ref="rp")
    t = FakeTransport([_Resp(200, {"status": "COMPLETED", "output": {"videos": [{"url": "u1"}, {"url": "u2"}]}})])
    out = backend.poll(job, transport=t)
    assert out.output_refs == ("u1", "u2")


# --------------------------------------------------------------------------- #
# Client + webhook verification
# --------------------------------------------------------------------------- #
def test_backend_registry_has_runpod():
    assert "runpod" in render.available_backends()
    assert render.get_backend("runpod") is not None


def test_webhook_sign_and_verify_roundtrip():
    payload = b'{"status":"COMPLETED"}'
    sig = render.sign_webhook(payload, "secret")
    assert render.verify_webhook(payload, sig, "secret") is True
    assert render.verify_webhook(payload, sig, "wrong") is False
    assert render.verify_webhook(payload, "sha256=deadbeef", "secret") is False
    assert render.verify_webhook(payload, "", "secret") is False


def test_apply_webhook_advances_envelope():
    job = env.RenderJob(id="j", backend="runpod", state=env.IN_PROGRESS, provider_ref="rp")
    out = render.apply_webhook(job, "succeeded", output_refs=("u",))
    assert out.is_done and out.output_refs == ("u",)


def test_client_poll_terminal_is_noop():
    done = env.transition(env.RenderJob(id="j", backend="runpod"), env.COMPLETED)
    assert render.poll(done) is done  # no transport needed; short-circuits
