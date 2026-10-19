"""Wave 1 — model-native camera-control provider (WanCameraAdapter).

Every test injects a fake ``request_fn`` (never touches the network) and asserts
the real submit/poll/quote/catalog logic. The adapter drives a ComfyUI-Deploy
Wan2.2-Fun camera-control graph: POST a run -> get an id -> GET status until
terminal -> read an output MP4 url + seconds of usage. Registration is gated on
the ComfyUI-Deploy / Wan camera credential being present in the env.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domains.routing.base import (
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_QUEUED,
    RUN_RUNNING,
    ModelListing,
    ProviderAdapter,
    ProviderError,
    ProviderRegistry,
    ProviderRun,
)
from app.domains.routing.providers import wan_camera as wc
from app.domains.routing.providers.registry import register_available_adapters
from app.domains.routing.providers.wan_camera import WanCameraAdapter


class FakeReq:
    """Fake request_fn recording calls and replaying scripted responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, method, path, *, json=None):
        self.calls.append({"method": method, "path": path, "json": json})
        return self._responses.pop(0)


# A request dict shaped exactly like ``motion.spec.to_wan_request`` output.
def _request(num_frames: int = 81) -> dict:
    return {
        "capability": "image_to_video",
        "prompt": "hero product shot. slow cinematic orbit around the subject",
        "negative_prompt": "blurry, low quality",
        "start_image_url": "https://cdn/start.png",
        "aspect_ratio": "9:16",
        "num_frames": num_frames,
        "estimated_seconds": max(1, round(num_frames / 16)),
        "camera": {
            "camera_pose": "ClockWise",
            "speed": 1.0,
            "width": 832,
            "height": 480,
            "length": num_frames,
            "fx": 0.5,
            "fy": 0.5,
            "cx": 0.5,
            "cy": 0.5,
            "pose_trajectory": [],
        },
    }


_SNAPSHOT = {"model_id": wc.WAN_CAMERA_MODEL_ID, "workflow_id": "dep-cam-1"}

# Pricing stub: 5000 micros/second, default 30s when unquantified.
PRICE_SEC = SimpleNamespace(
    id="pv", unit_price_micros=5000, min_charge_micros=0, flat_fee_micros=0,
    quote_rules={"default_units": 30},
)


# --------------------------------------------------------------------------- #
# Protocol conformance + module metadata
# --------------------------------------------------------------------------- #
def test_conforms_to_provider_adapter_protocol():
    a = WanCameraAdapter(api_key="k", base_url="https://comfy", request_fn=FakeReq([]))
    assert isinstance(a, ProviderAdapter)
    assert a.provider_key == "wan_camera"


def test_module_license_and_move_constants():
    assert wc.LICENSE_CLASS == "open_weights"
    assert wc.PAID_SAFE is True
    assert wc.WAN_CAMERA_MODEL_ID == "wan2.2-fun-a14b-control-camera"
    # The 9 Wan named camera moves.
    assert wc.WAN_NAMED_MOVES == frozenset(
        {"Static", "Pan Up", "Pan Down", "Pan Left", "Pan Right",
         "Zoom In", "Zoom Out", "Anti Clockwise", "ClockWise"}
    )


def test_catalog_single_listing():
    a = WanCameraAdapter(api_key="k", base_url="https://comfy", request_fn=FakeReq([]))
    listings = a.catalog()
    assert len(listings) == 1
    lst = listings[0]
    assert isinstance(lst, ModelListing)
    assert lst.provider_key == "wan_camera"
    assert lst.model_id == "wan2.2-fun-a14b-control-camera"
    assert lst.capability == "image_to_video"
    assert lst.metering_unit == "seconds"


# --------------------------------------------------------------------------- #
# submit -> poll -> complete (happy path)
# --------------------------------------------------------------------------- #
def test_submit_then_poll_to_completion():
    submit_resp = {"run_id": "run-42"}
    poll_running = {"status": "running"}
    poll_done = {
        "status": "success",
        "outputs": [{"data": {"gifs": [{"url": "https://cdn/out.mp4"}]}}],
    }
    req = FakeReq([submit_resp, poll_running, poll_done])
    a = WanCameraAdapter(api_key="k", base_url="https://comfy", request_fn=req)

    run = a.submit(_request(), _SNAPSHOT, "job-1")
    assert run.run_id == "run-42"
    assert run.state == RUN_QUEUED
    # POST /api/run with a ComfyUI-Deploy body.
    assert req.calls[0]["method"] == "POST"
    assert req.calls[0]["path"] == "/api/run"
    body = req.calls[0]["json"]
    assert body["deployment_id"] == "dep-cam-1"
    inputs = body["inputs"]
    # WanCameraEmbedding node inputs come from request["camera"].
    assert inputs["camera_pose"] == "ClockWise"
    assert inputs["width"] == 832 and inputs["height"] == 480
    assert inputs["length"] == 81
    # Fun-Control sampler inputs from prompt / start_image / frames.
    assert inputs["prompt"].startswith("hero product shot")
    assert inputs["start_image_url"] == "https://cdn/start.png"
    assert inputs["num_frames"] == 81
    assert inputs["negative_prompt"] == "blurry, low quality"

    # First poll: still running, no result yet.
    run2 = a.poll(run)
    assert run2.state == RUN_RUNNING
    assert run2.result_ref == ""
    assert req.calls[1]["method"] == "GET"
    assert req.calls[1]["path"] == "/api/run?run_id=run-42"

    # Second poll: terminal success -> MP4 url + usage in seconds.
    run3 = a.poll(run2)
    assert run3.state == RUN_COMPLETED
    assert run3.result_ref == "https://cdn/out.mp4"
    assert run3.usage is not None
    assert run3.usage.unit == "seconds"
    # round(81 / 16) == 5
    assert run3.usage.quantity_units == 5


def test_poll_prefers_video_extension_output():
    poll_done = {
        "status": "success",
        "outputs": [
            {"data": {"images": [{"url": "https://cdn/preview.png"}]}},
            {"data": {"videos": [{"url": "https://cdn/final.mp4"}]}},
        ],
    }
    a = WanCameraAdapter(api_key="k", base_url="https://comfy", request_fn=FakeReq([poll_done]))
    run = ProviderRun(
        provider_key="wan_camera", run_id="r", state=RUN_RUNNING,
        raw={"num_frames": 49},
    )
    out = a.poll(run)
    assert out.state == RUN_COMPLETED
    assert out.result_ref == "https://cdn/final.mp4"
    assert out.usage.quantity_units == round(49 / 16)  # 3


# --------------------------------------------------------------------------- #
# failure / terminal-error paths
# --------------------------------------------------------------------------- #
def test_poll_failed_status_is_terminal_failure():
    a = WanCameraAdapter(
        api_key="k", base_url="https://comfy",
        request_fn=FakeReq([{"status": "failed", "error": "sampler OOM"}]),
    )
    run = ProviderRun(provider_key="wan_camera", run_id="r", state=RUN_RUNNING, raw={"num_frames": 81})
    out = a.poll(run)
    assert out.state == RUN_FAILED
    assert out.result_ref == ""
    assert out.usage is None


def test_submit_without_run_id_raises_provider_error():
    a = WanCameraAdapter(
        api_key="k", base_url="https://comfy", request_fn=FakeReq([{"status": "queued"}]),
    )
    with pytest.raises(ProviderError) as ei:
        a.submit(_request(), _SNAPSHOT, "job-1")
    assert ei.value.provider_key == "wan_camera"


def test_submit_requires_deployment_id():
    # No workflow_id in snapshot and no configured default -> ProviderError.
    a = WanCameraAdapter(api_key="k", base_url="https://comfy", request_fn=FakeReq([]))
    with pytest.raises(ProviderError):
        a.submit(_request(), {"model_id": wc.WAN_CAMERA_MODEL_ID}, "job-1")


def test_poll_terminal_run_is_noop():
    a = WanCameraAdapter(api_key="k", base_url="https://comfy", request_fn=FakeReq([]))
    done = ProviderRun(provider_key="wan_camera", run_id="r", state=RUN_COMPLETED)
    assert a.poll(done) is done


def test_image_to_video_requires_start_image():
    req = _request()
    req["start_image_url"] = ""
    a = WanCameraAdapter(api_key="k", base_url="https://comfy", request_fn=FakeReq([]))
    with pytest.raises(ProviderError):
        a.submit(req, _SNAPSHOT, "job-1")


# --------------------------------------------------------------------------- #
# quote correctness
# --------------------------------------------------------------------------- #
def test_quote_uses_estimated_seconds():
    a = WanCameraAdapter(api_key="k", base_url="https://comfy", request_fn=FakeReq([]))
    # estimated_seconds for 81 frames == round(81/16) == 5 -> 5 * 5000 micros.
    q = a.quote(_request(), PRICE_SEC)
    assert q.max_cost_micros == 5 * 5000
    assert q.price_version_id == "pv"


def test_quote_falls_back_to_default_units():
    a = WanCameraAdapter(api_key="k", base_url="https://comfy", request_fn=FakeReq([]))
    # No estimate in the request -> price rule default of 30 units.
    q = a.quote({}, PRICE_SEC)
    assert q.max_cost_micros == 30 * 5000


# --------------------------------------------------------------------------- #
# cancel is best-effort
# --------------------------------------------------------------------------- #
def test_cancel_is_best_effort_false_on_error():
    a = WanCameraAdapter(
        api_key="k", base_url="https://comfy",
        request_fn=FakeReq([]),  # empty -> pop from empty list raises -> swallowed
    )
    run = ProviderRun(provider_key="wan_camera", run_id="r", state=RUN_RUNNING)
    assert a.cancel(run) is False


def test_cancel_success_posts_cancel_and_returns_true():
    req = FakeReq([{}])  # any successful (non-raising) response
    a = WanCameraAdapter(api_key="k", base_url="https://comfy", request_fn=req)
    run = ProviderRun(provider_key="wan_camera", run_id="r", state=RUN_RUNNING)
    assert a.cancel(run) is True
    assert req.calls[0] == {
        "method": "POST",
        "path": "/api/run/r/cancel",
        "json": None,
    }


# --------------------------------------------------------------------------- #
# registry population — credential-gated
# --------------------------------------------------------------------------- #
def test_registers_with_comfy_deploy_token():
    reg = ProviderRegistry()
    keys = register_available_adapters(reg, env={"COMFY_DEPLOY_TOKEN": "t"})
    assert "wan_camera" in keys
    assert reg.has("wan_camera")


def test_registers_with_wan_camera_api_key():
    reg = ProviderRegistry()
    keys = register_available_adapters(reg, env={"WAN_CAMERA_API_KEY": "k"})
    assert "wan_camera" in keys
    assert reg.has("wan_camera")


def test_not_registered_without_credential():
    reg = ProviderRegistry()
    keys = register_available_adapters(reg, env={"ELEVENLABS_API_KEY": "e"})
    assert "wan_camera" not in keys
    assert not reg.has("wan_camera")


def test_build_adapter_by_key():
    from app.domains.routing.providers.registry import build_adapter

    a = build_adapter("wan_camera", "k")
    assert a is not None
    assert a.provider_key == "wan_camera"


# --------------------------------------------------------------------------- #
# license-class metadata (Wan open-weights = paid-safe)
# --------------------------------------------------------------------------- #
def test_license_class_paid_safe():
    from app.domains.routing import license_class as lic

    assert lic.is_paid_safe("wan_camera") is True
    lic.assert_route_allowed("wan_camera", paid=True, on=__import__("datetime").date(2026, 8, 19))
