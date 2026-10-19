"""P8 async-media adapter (real submit/poll) + license-class routing gate."""

from __future__ import annotations

from datetime import date

import pytest

from app.domains.routing import license_class as lic
from app.domains.routing.base import (
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_QUEUED,
    RUN_RUNNING,
    ProviderError,
)
from app.domains.routing.providers.async_media import (
    AsyncMediaConfig,
    build_async_media_adapter,
)


class FakeReq:
    """Fake request_fn recording calls and replaying scripted responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, method, path, *, json=None):
        self.calls.append({"method": method, "path": path, "json": json})
        return self._responses.pop(0)


# --------------------------------------------------------------------------- #
# Async-media adapter — submit + poll to terminal
# --------------------------------------------------------------------------- #
def test_kling_submit_then_poll_completed():
    req = FakeReq([
        {"data": {"task_id": "t-1", "task_status": "submitted"}},
        {"data": {"task_status": "processing"}},
        {"data": {"task_status": "succeed", "works": [{"url": "https://cdn/k.mp4"}], "duration": 5}},
    ])
    a = build_async_media_adapter("kling", api_key="k", request_fn=req)
    run = a.submit({"prompt": "a cat", "seconds": 5}, {"model_id": "kling/kling-v2"}, "corr")
    assert run.run_id == "t-1" and run.state == RUN_QUEUED
    # Real submit body shape.
    assert req.calls[0]["method"] == "POST"
    assert req.calls[0]["json"]["prompt"] == "a cat"
    assert req.calls[0]["json"]["duration"] == "5"

    run = a.poll(run)
    assert run.state == RUN_RUNNING
    # 'succeed' isn't in the default map -> treated as running (safe). Poll again
    # with a mapped terminal status:
    req2 = FakeReq([{"data": {"task_status": "completed", "works": [{"url": "https://cdn/k.mp4"}], "duration": 5}}])
    a2 = build_async_media_adapter("kling", api_key="k", request_fn=req2)
    from app.domains.routing.base import ProviderRun

    done = a2.poll(ProviderRun(provider_key="kling", run_id="t-1", state=RUN_RUNNING))
    assert done.state == RUN_COMPLETED
    assert done.result_ref == "https://cdn/k.mp4"
    assert done.usage and done.usage.quantity_units == 5 and done.usage.unit == "seconds"


def test_runway_poll_paths_and_failure():
    req = FakeReq([{"id": "r-9", "status": "PENDING"}])
    a = build_async_media_adapter("runway", api_key="k", request_fn=req)
    run = a.submit({"prompt_image": "https://img"}, {"model_id": "runway/gen4"}, "c")
    assert run.run_id == "r-9" and run.state == RUN_QUEUED

    req2 = FakeReq([{"status": "FAILED"}])
    a2 = build_async_media_adapter("runway", api_key="k", request_fn=req2)
    from app.domains.routing.base import ProviderRun

    out = a2.poll(ProviderRun(provider_key="runway", run_id="r-9", state=RUN_RUNNING))
    assert out.state == RUN_FAILED
    assert req2.calls[0] == {"method": "GET", "path": "/v1/tasks/r-9", "json": None}


def test_submit_without_job_id_raises():
    req = FakeReq([{"data": {}}])  # no task_id
    a = build_async_media_adapter("kling", api_key="k", request_fn=req)
    with pytest.raises(ProviderError):
        a.submit({"prompt": "x"}, {"model_id": "kling/v2"}, "c")


def test_poll_terminal_is_noop():
    from app.domains.routing.base import ProviderRun

    a = build_async_media_adapter("suno", api_key="k", request_fn=FakeReq([]))
    done = ProviderRun(provider_key="suno", run_id="s", state=RUN_COMPLETED)
    assert a.poll(done) is done


def test_veo_boolean_done_state_map():
    from app.domains.routing.base import ProviderRun

    req = FakeReq([{"done": "true", "response": {"generateVideoResponse": {"video": {"url": "https://v/o.mp4"}},
                                                 "duration": 8}}])
    a = build_async_media_adapter("veo", api_key="k", request_fn=req)
    out = a.poll(ProviderRun(provider_key="veo", run_id="op-1", state=RUN_RUNNING))
    assert out.state == RUN_COMPLETED and out.result_ref == "https://v/o.mp4"


def test_unknown_provider_config_raises():
    with pytest.raises(ProviderError):
        build_async_media_adapter("does-not-exist")


def test_music_capability_config():
    cfg = AsyncMediaConfig(provider_key="x", base_url="https://x", capability="music")
    assert cfg.capability == "music"


# --------------------------------------------------------------------------- #
# License class + sunset routing gate
# --------------------------------------------------------------------------- #
def test_nc_weights_blocked_for_paid_only():
    assert lic.is_paid_safe("kling") is True
    assert lic.is_paid_safe("hunyuanvideo") is False   # NC
    assert lic.is_paid_safe("xtts") is False           # NC
    assert lic.is_paid_safe("wav2lip") is False        # research-only
    # A free/draft render may still use them.
    today = date(2026, 8, 18)
    assert lic.is_route_allowed("xtts", paid=False, on=today) is True
    assert lic.is_route_allowed("xtts", paid=True, on=today) is False


def test_sora_sunset_blocks_after_date():
    before = date(2026, 9, 1)
    after = date(2026, 10, 1)
    assert lic.is_sunset("sora2", on=before) is False
    assert lic.is_sunset("sora2", on=after) is True
    assert lic.is_route_allowed("sora2", paid=True, on=after) is False
    status = lic.sunset_status("sora2", on=before)
    assert status["replacement"] == "veo" and status["days_left"] == 23


def test_assert_route_allowed_messages():
    today = date(2026, 8, 18)
    with pytest.raises(lic.LicenseError):
        lic.assert_route_allowed("hunyuanvideo", paid=True, on=today)
    with pytest.raises(lic.LicenseError):
        lic.assert_route_allowed("sora2", paid=True, on=date(2026, 12, 1))
    # Permissive model is fine.
    lic.assert_route_allowed("kokoro", paid=True, on=today)


def test_unknown_model_assumed_commercial():
    assert lic.is_paid_safe("some-new-hosted-api") is True
