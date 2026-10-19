"""Wave 4 SPEAK — open lipsync adapter (real submit/poll via a fake transport)
plus the pure license-class gate, deterministic provider selection, and the
bounded product-engine allowlist.

No network: a fake ``request_fn`` records calls and replays scripted responses,
so the adapter's real submit/poll/normalize logic is exercised while the HTTP
seam is stubbed (mirrors ``test_async_media_adapter.py`` / ``sadtalker`` tests).
"""

from __future__ import annotations

import pytest

from app.domains.routing.base import (
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_QUEUED,
    RUN_RUNNING,
    ProviderError,
    ProviderRun,
)
from app.domains.routing.providers._lipsync import (
    LIPSYNC_CONFIGS,
    LipsyncAdapter,
    build_lipsync_adapter,
)
from app.domains.speak import licensing as lic
from app.domains.speak import selection as sel
from app.domains.speak import workflows as wf


class FakeReq:
    """Fake request_fn recording calls and replaying scripted responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, method, path, *, json=None):
        self.calls.append({"method": method, "path": path, "json": json})
        return self._responses.pop(0)


# --------------------------------------------------------------------------- #
# Lipsync adapter — submit + poll to terminal (both seeded providers are configs)
# --------------------------------------------------------------------------- #
def test_musetalk_submit_then_poll_completed():
    req = FakeReq([
        {"run_id": "m-1", "status": "queued"},
        {"status": "processing"},
        {"status": "completed", "output_url": "https://cdn/talk.mp4", "seconds": 7},
    ])
    a = build_lipsync_adapter("musetalk", api_key="k", request_fn=req)
    assert a.provider_key == "musetalk"

    run = a.submit(
        {"image_url": "https://own/img.png", "audio_url": "https://own/a.wav"},
        {},
        "corr-1",
    )
    assert run.run_id == "m-1" and run.state == RUN_QUEUED
    # Real submit body: BOTH presigned inputs are forwarded, plus correlation id.
    assert req.calls[0]["method"] == "POST" and req.calls[0]["path"] == "/run"
    assert req.calls[0]["json"]["image_url"] == "https://own/img.png"
    assert req.calls[0]["json"]["audio_url"] == "https://own/a.wav"
    assert req.calls[0]["json"]["correlation_id"] == "corr-1"

    run = a.poll(run)
    assert run.state == RUN_RUNNING and not run.is_terminal

    run = a.poll(run)
    assert run.state == RUN_COMPLETED and run.is_terminal
    assert run.result_ref == "https://cdn/talk.mp4"
    assert run.usage and run.usage.unit == "seconds" and run.usage.quantity_units == 7
    assert run.progress == 100


def test_latentsync_is_a_config_not_a_bespoke_class():
    # Both open providers are configs in the one registry, disjoint from CHAR.
    assert set(LIPSYNC_CONFIGS) == {"musetalk", "latentsync"}
    a = build_lipsync_adapter("latentsync", request_fn=FakeReq([]))
    assert isinstance(a, LipsyncAdapter)
    assert a.provider_key == "latentsync"
    assert a.license_class == "source_available"


def test_submit_requires_both_image_and_audio():
    a = build_lipsync_adapter("musetalk", request_fn=FakeReq([{"run_id": "x"}]))
    with pytest.raises(ProviderError):
        a.submit({"image_url": "https://own/img.png"}, {}, "c")  # no audio_url
    with pytest.raises(ProviderError):
        a.submit({"audio_url": "https://own/a.wav"}, {}, "c")  # no image_url


def test_submit_without_run_id_raises():
    req = FakeReq([{"status": "queued"}])  # no run_id / id
    a = build_lipsync_adapter("musetalk", request_fn=req)
    with pytest.raises(ProviderError):
        a.submit(
            {"image_url": "https://i", "audio_url": "https://a"}, {}, "c"
        )


def test_poll_maps_failed_state_and_paths():
    req = FakeReq([{"status": "error", "message": "cuda oom"}])
    a = build_lipsync_adapter("latentsync", request_fn=req)
    out = a.poll(ProviderRun(provider_key="latentsync", run_id="r-1", state=RUN_RUNNING))
    assert out.state == RUN_FAILED and not out.result_ref
    assert req.calls[0] == {"method": "GET", "path": "/status/r-1", "json": None}


def test_poll_terminal_is_noop():
    a = build_lipsync_adapter("musetalk", request_fn=FakeReq([]))
    done = ProviderRun(provider_key="musetalk", run_id="m", state=RUN_COMPLETED)
    assert a.poll(done) is done


def test_normalize_usage_rounds_partial_second_up():
    a = build_lipsync_adapter("musetalk", request_fn=FakeReq([]))
    assert a.normalize_usage({"seconds": 4.2}).quantity_units == 5
    assert a.normalize_usage({"seconds": 4}).quantity_units == 4
    # Falls back to ``duration`` and tolerates junk.
    assert a.normalize_usage({"duration": 3}).quantity_units == 3
    assert a.normalize_usage({"seconds": "bad"}).quantity_units == 0


def test_cancel_best_effort():
    ok = build_lipsync_adapter("musetalk", request_fn=FakeReq([{}]))
    assert ok.cancel(ProviderRun(provider_key="musetalk", run_id="m")) is True

    def boom(method, path, *, json=None):
        raise ProviderError("no", provider_key="musetalk")

    bad = build_lipsync_adapter("musetalk", request_fn=boom)
    assert bad.cancel(ProviderRun(provider_key="musetalk", run_id="m")) is False


def test_catalog_shape():
    a = build_lipsync_adapter("musetalk", request_fn=FakeReq([]))
    listings = a.catalog()
    assert listings and listings[0].capability == "lipsync"
    assert listings[0].metering_unit == "seconds"


def test_unknown_provider_config_raises():
    with pytest.raises(ProviderError):
        build_lipsync_adapter("does-not-exist")


# --------------------------------------------------------------------------- #
# License-class gate (§8) — pure metadata, deterministic
# --------------------------------------------------------------------------- #
def test_open_providers_are_commercial_safe():
    assert lic.is_commercial_ok("musetalk") is True
    assert lic.license_class_for("musetalk") is lic.LicenseClass.OPEN_COMMERCIAL


def test_latentsync_is_non_commercial_until_mo12b_fork():
    # MO1: InsightFace dependency; paid output fails closed until the MO12b fork.
    assert lic.license_class_for("latentsync") is lic.LicenseClass.NON_COMMERCIAL
    assert lic.is_commercial_ok("latentsync") is False
    with pytest.raises(lic.LicenseClassError):
        lic.require_commercial_ok("latentsync")


def test_research_only_provider_blocked_for_paid():
    assert lic.is_commercial_ok("wav2lip") is False
    with pytest.raises(lic.LicenseClassError):
        lic.require_commercial_ok("wav2lip")


def test_unknown_provider_fails_closed():
    # An unreviewed provider can never back a paid render.
    assert lic.is_commercial_ok("mystery-net") is False
    with pytest.raises(lic.LicenseClassError):
        lic.require_commercial_ok("mystery-net")


def test_require_commercial_ok_passes_for_open():
    lic.require_commercial_ok("musetalk")  # no raise
    assert lic.commercial_provider_keys() == frozenset({"musetalk"})


# --------------------------------------------------------------------------- #
# Deterministic provider selection
# --------------------------------------------------------------------------- #
def test_selection_prefers_musetalk_when_available():
    out = sel.choose_lipsync_provider(
        {}, {}, commercial=True, available={"musetalk", "latentsync"}
    )
    assert out == "musetalk"


def test_selection_honors_availability():
    # Free/research path keeps LatentSync available.
    out = sel.choose_lipsync_provider(
        {}, {}, commercial=False, available={"latentsync"}
    )
    assert out == "latentsync"


def test_paid_selection_never_picks_latentsync_before_mo12b():
    with pytest.raises(sel.NoLipsyncProviderError):
        sel.choose_lipsync_provider({}, {}, commercial=True, available={"latentsync"})


def test_selection_is_deterministic():
    a = sel.choose_lipsync_provider({}, {}, commercial=True, available={"latentsync", "musetalk"})
    b = sel.choose_lipsync_provider({}, {}, commercial=True, available={"musetalk", "latentsync"})
    assert a == b == "musetalk"


def test_selection_commercial_excludes_research_only():
    # wav2lip is research-only: eligible for a free/draft render, never a paid one.
    order_paid = sel.candidate_order({"musetalk", "wav2lip"}, commercial=True)
    assert "wav2lip" not in order_paid and order_paid == ["musetalk"]
    order_free = sel.candidate_order({"wav2lip"}, commercial=False)
    assert order_free == ["wav2lip"]


def test_selection_raises_when_none_available_commercial():
    with pytest.raises(sel.NoLipsyncProviderError):
        sel.choose_lipsync_provider({}, {}, commercial=True, available={"wav2lip"})
    with pytest.raises(sel.NoLipsyncProviderError):
        sel.choose_lipsync_provider({}, {}, commercial=True, available=set())


# --------------------------------------------------------------------------- #
# Product allowlist gate (clients pick a bounded preset, never an arbitrary model)
# --------------------------------------------------------------------------- #
def test_require_approved_provider_rejects_arbitrary_selector():
    from app.models.exception import HttpException

    wf.require_approved_provider("", "rid")  # empty is allowed (resolved server-side)
    wf.require_approved_provider("musetalk", "rid")  # approved is fine
    with pytest.raises(HttpException):
        wf.require_approved_provider("comfyui-deployment-xyz", "rid")


def test_product_engine_capability_exposes_bounded_selectors():
    cap = wf.product_engine_capability()["speak"]
    keys = {p["provider"] for p in cap["providers"]}
    assert keys == {"musetalk", "latentsync"}
    by_key = {p["provider"]: p for p in cap["providers"]}
    assert by_key["musetalk"]["license_class"] == "open_commercial"
    assert by_key["latentsync"]["license_class"] == "non_commercial"
    assert cap["runtime"] == "gpu_worker"
