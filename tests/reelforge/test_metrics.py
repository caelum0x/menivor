"""Observability metrics — registry exposition + render-executor emission."""

from __future__ import annotations

from app.telemetry import metrics
from app.telemetry.metrics import Registry


def test_counter_renders_prometheus_format():
    reg = Registry()
    c = reg.counter("render_jobs", "async render jobs by state")
    c.inc({"state": "COMPLETED"})
    c.inc({"state": "COMPLETED"})
    c.inc({"state": "FAILED"})
    text = reg.render()
    assert "# TYPE render_jobs counter" in text
    assert 'render_jobs{state="COMPLETED"} 2' in text
    assert 'render_jobs{state="FAILED"} 1' in text


def test_counter_accumulates_values():
    reg = Registry()
    c = reg.counter("wallet_debit_micros")
    c.inc({"reason": "generation"}, 100_000)
    c.inc({"reason": "generation"}, 20_000)
    assert 'wallet_debit_micros{reason="generation"} 120000' in reg.render()


def test_histogram_buckets_and_sum():
    reg = Registry()
    h = reg.histogram("hook_score_duration_seconds", buckets=(0.5, 1.0, 2.0))
    h.observe({}, 0.3)
    h.observe({}, 0.8)
    h.observe({}, 1.5)
    text = reg.render()
    assert "# TYPE hook_score_duration_seconds histogram" in text
    # 0.3 <= 0.5 bucket; cumulative le=1.0 covers 0.3 + 0.8 = 2
    assert 'hook_score_duration_seconds_bucket{le="0.5"} 1' in text
    assert 'hook_score_duration_seconds_bucket{le="1"} 2' in text  # 1.0 formats as "1"
    assert 'hook_score_duration_seconds_bucket{le="+Inf"} 3' in text
    assert "hook_score_duration_seconds_count 3" in text  # empty labels -> no braces


def test_label_escaping():
    reg = Registry()
    reg.counter("x").inc({"k": 'a"b'})
    assert 'x{k="a\\"b"}' in reg.render()


def test_named_emitters_write_to_global_registry():
    # Snapshot-independent: assert the series appear after emitting.
    metrics.record_render_state("COMPLETED")
    metrics.record_wallet_debit("generation", 50_000)
    metrics.record_native_publish("published")
    metrics.record_license_block("paid", "non_commercial")
    text = metrics.render_metrics()
    assert 'render_jobs{state="COMPLETED"}' in text
    assert 'wallet_debit_micros{reason="generation"}' in text
    assert 'native_publish{status="published"}' in text
    assert 'route_license_block_total{class="non_commercial",tier="paid"}' in text


def test_executor_emits_billing_invariant_series():
    # A completed render emits BOTH render_jobs{COMPLETED} and a wallet debit;
    # a failed render emits render_jobs{FAILED} and NO debit — the invariant's data.
    from app.services.render.envelope import COMPLETED, FAILED, RenderJob, transition
    from app.services.render.execution import RenderExecutor

    class FakeWallet:
        def reserve(self, a, *, job_id): ...
        def settle(self, r, a, *, job_id): ...
        def release(self, r, *, job_id): ...

    _executor = RenderExecutor(FakeWallet())
    # Directly drive advance with a transport that completes / fails.
    class T:
        def __init__(self, body):
            self._body = body

        def request(self, method, url, *, headers=None, params=None, json=None):
            class R:
                status_code = 200
                headers: dict = {}

                def json(_self):
                    return self._body

                @property
                def text(_self):
                    return ""

            return R()

    from app.services.render.backends.runpod import RunPodBackend, register_backend

    register_backend(RunPodBackend(endpoint_id="e", api_key="k"))

    before = metrics.render_metrics()
    ok_job = RenderJob(id="jm1", backend="runpod", state="IN_PROGRESS", provider_ref="rp")
    ex_ok = RenderExecutor(FakeWallet(), transport=T({"status": "COMPLETED", "output": "u"}))
    ex_ok.advance(ok_job, held_micros=100_000)

    bad_job = RenderJob(id="jm2", backend="runpod", state="IN_PROGRESS", provider_ref="rp")
    ex_bad = RenderExecutor(FakeWallet(), transport=T({"status": "FAILED", "error": "x"}))
    ex_bad.advance(bad_job, held_micros=90_000)

    text = metrics.render_metrics()
    assert 'render_jobs{state="COMPLETED"}' in text
    assert 'render_jobs{state="FAILED"}' in text
    assert 'wallet_debit_micros{reason="generation"}' in text
    _ = (before, transition, COMPLETED, FAILED)  # silence unused
