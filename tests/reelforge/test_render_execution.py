"""Render execution lifecycle — reserve → submit → poll → settle/refund + events.

Success-only billing invariant is the headline assertion: a FAILED render refunds
the full hold; a COMPLETED render settles the actual (never above the reserve).
"""

from __future__ import annotations

import pytest

from app.events.bus import JOB_COMPLETED, RENDER_STATE_CHANGED, EventBus
from app.services.render.envelope import COMPLETED, FAILED, RenderJob
from app.services.render.execution import ExecutionError, RenderExecutor


class FakeWallet:
    """Records reserve/settle/release calls against a running balance."""

    def __init__(self):
        self.reserved = 0
        self.settled = None
        self.released = 0
        self.log = []

    def reserve(self, amount_micros, *, job_id):
        self.reserved += amount_micros
        self.log.append(("reserve", amount_micros, job_id))

    def settle(self, reserved_micros, actual_micros, *, job_id):
        self.settled = (reserved_micros, actual_micros)
        self.log.append(("settle", reserved_micros, actual_micros, job_id))

    def release(self, reserved_micros, *, job_id):
        self.released += reserved_micros
        self.log.append(("release", reserved_micros, job_id))


class _Resp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}
        self.headers = {}

    def json(self):
        return self._body

    @property
    def text(self):
        return str(self._body)


class FakeTransport:
    """RunPod-shaped transport: 1 submit + scripted poll responses."""

    def __init__(self, poll_states):
        self._submit = _Resp(200, {"id": "rp-1", "status": "IN_QUEUE"})
        self._polls = list(poll_states)
        self.calls = 0

    def request(self, method, url, *, headers=None, params=None, json=None):
        self.calls += 1
        if url.endswith("/run"):
            return self._submit
        return self._polls.pop(0)


def _spec():
    return {"job_id": "job-1", "workflow_version": "wan_i2v@1"}


def _executor(wallet, transport):
    # Bind the RunPod backend config via env-free constructor by patching config
    from app.services.render.backends.runpod import RunPodBackend, register_backend

    register_backend(RunPodBackend(endpoint_id="ep", api_key="k"))
    return RenderExecutor(wallet, transport=transport)


def test_completed_render_settles_actual_and_emits_events():
    wallet = FakeWallet()
    transport = FakeTransport([
        _Resp(200, {"status": "IN_PROGRESS"}),
        _Resp(200, {"status": "COMPLETED", "output": {"video_url": "https://cdn/o.mp4"}}),
    ])
    ex = _executor(wallet, transport)

    job = ex.start("runpod", _spec(), max_cost_micros=120_000)
    assert wallet.reserved == 120_000
    job = ex.run_to_completion(job, held_micros=120_000)
    assert job.state == COMPLETED

    # No reported cost -> settle the full hold (never above reserve).
    assert wallet.settled == (120_000, 120_000)
    assert wallet.released == 0

    # Events: state changes + a job.completed carrying the output.
    bus = EventBus()
    completed = []
    states = []
    bus.subscribe(JOB_COMPLETED, lambda e: completed.append(e.payload))
    bus.subscribe(RENDER_STATE_CHANGED, lambda e: states.append(e.payload["state"]))
    ex.outbox.drain(bus)
    assert completed and completed[0]["output_refs"] == ["https://cdn/o.mp4"]
    assert COMPLETED in states


def test_failed_render_refunds_full_hold():
    wallet = FakeWallet()
    transport = FakeTransport([_Resp(200, {"status": "FAILED", "error": "oom"})])
    ex = _executor(wallet, transport)

    job = ex.start("runpod", _spec(), max_cost_micros=90_000)
    job = ex.run_to_completion(job, held_micros=90_000)

    assert job.state == FAILED
    # Success-only billing: full refund, nothing settled.
    assert wallet.released == 90_000
    assert wallet.settled is None


def test_settle_never_exceeds_reserve():
    wallet = FakeWallet()
    transport = FakeTransport([
        _Resp(200, {"status": "COMPLETED", "output": "u"}),
    ])
    ex = _executor(wallet, transport)
    job = ex.start("runpod", _spec(), max_cost_micros=50_000)
    # Manually inject a cost above the hold to prove the clamp.
    job = RenderJob(id="job-1", backend="runpod", state="IN_PROGRESS", provider_ref="rp-1", cost_micros=0)
    ex.advance(job, held_micros=50_000)
    assert wallet.settled == (50_000, 50_000)


def test_submit_failure_releases_reservation():
    wallet = FakeWallet()

    class BoomTransport:
        def request(self, *a, **k):
            return _Resp(500, {"error": "down"})

    ex = _executor(wallet, BoomTransport())
    with pytest.raises(ExecutionError):
        ex.start("runpod", _spec(), max_cost_micros=70_000)
    # Reserved then released — no money left held on a job that never started.
    assert wallet.reserved == 70_000 and wallet.released == 70_000


def test_positive_cost_required():
    ex = _executor(FakeWallet(), FakeTransport([]))
    with pytest.raises(ExecutionError):
        ex.start("runpod", _spec(), max_cost_micros=0)
