"""Unit tests for the channel-runner Celery beat tasks (beat-safety contract).

The two periodic tasks must NEVER raise out of their body (a bad tick can't be
allowed to crash the shared beat scheduler) — any failure degrades to a logged
ZEROED summary dict. They are also idempotent on a duplicate tick. The tasks are
invoked directly (synchronously) with their wiring impls monkeypatched, so no
broker / DB / stories layer is required.
"""

from __future__ import annotations

import pytest

from app.workers import tasks_series
from app.workers.tasks_series import (
    _EMPTY_RUN_SUMMARY,
    _EMPTY_SCHEDULE_SUMMARY,
    run_series_task,
    schedule_series_publishes_task,
)


def test_run_series_task_never_raises_on_service_exception(monkeypatch):
    def _boom(payload):
        raise RuntimeError("stories layer blew up")

    monkeypatch.setattr(tasks_series, "_run_series_impl", _boom)

    # Must not raise; returns a zeroed summary so the beat tick survives.
    result = run_series_task({"channels": [{"channel_id": "c"}]})
    assert result == _EMPTY_RUN_SUMMARY
    assert all(v == 0 for v in result.values())


def test_schedule_task_never_raises_on_service_exception(monkeypatch):
    def _boom(payload):
        raise RuntimeError("scheduler exploded")

    monkeypatch.setattr(tasks_series, "_schedule_series_impl", _boom)

    result = schedule_series_publishes_task({"channels": [{"channel_id": "c"}]})
    assert result == _EMPTY_SCHEDULE_SUMMARY
    assert all(v == 0 for v in result.values())


def test_run_series_task_returns_impl_summary_on_success(monkeypatch):
    monkeypatch.setattr(
        tasks_series,
        "_run_series_impl",
        lambda payload: {"channels": 1, "rendered": 3, "skipped_duplicates": 2,
                         "paced_out": 1, "enqueue_failures": 0},
    )
    result = run_series_task({"channels": [{"channel_id": "c"}]})
    assert result["rendered"] == 3
    assert result["skipped_duplicates"] == 2


def test_run_series_task_is_idempotent_on_duplicate_tick(monkeypatch):
    """A duplicate tick must not double-render — the dedupe seam makes re-runs safe.

    The impl is dedupe-aware: it renders on the first call and skips (as
    duplicates) on the second, mirroring ``spec_hash`` cross-run dedupe.
    """
    state = {"rendered_hashes": set()}
    all_hashes = {"h1", "h2", "h3"}

    def _dedup_impl(payload):
        fresh = all_hashes - state["rendered_hashes"]
        state["rendered_hashes"] |= fresh
        return {
            "channels": 1,
            "rendered": len(fresh),
            "skipped_duplicates": len(all_hashes) - len(fresh),
            "paced_out": 0,
            "enqueue_failures": 0,
        }

    monkeypatch.setattr(tasks_series, "_run_series_impl", _dedup_impl)

    first = run_series_task({})
    second = run_series_task({})  # duplicate tick

    assert first["rendered"] == 3
    assert first["skipped_duplicates"] == 0
    assert second["rendered"] == 0          # nothing re-rendered
    assert second["skipped_duplicates"] == 3


def test_connection_error_propagates_for_autoretry(monkeypatch):
    """A transient ConnectionError is NOT swallowed — Celery autoretry owns it."""
    def _conn_boom(payload):
        raise ConnectionError("broker unreachable")

    monkeypatch.setattr(tasks_series, "_run_series_impl", _conn_boom)
    with pytest.raises(ConnectionError):
        run_series_task({})

    monkeypatch.setattr(tasks_series, "_schedule_series_impl", _conn_boom)
    with pytest.raises(ConnectionError):
        schedule_series_publishes_task({})


def test_empty_payload_is_a_zeroed_no_op(monkeypatch):
    """No channels configured -> a clean zeroed summary, no work attempted."""
    # Use the real impls (they load channels from the payload; empty -> no-op).
    assert run_series_task({}) == _EMPTY_RUN_SUMMARY
    assert schedule_series_publishes_task({}) == _EMPTY_SCHEDULE_SUMMARY
    assert run_series_task(None) == _EMPTY_RUN_SUMMARY


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
