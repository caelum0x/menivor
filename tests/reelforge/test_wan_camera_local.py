"""WanCameraLocalAdapter — the local-ComfyUI sibling of WanCameraAdapter.

Mirrors the remote adapter's exact envelope (RUN_QUEUED/RUN_RUNNING/
RUN_COMPLETED, result_ref = /view URL, usage seconds = round(num_frames/16)).
A fake ComfyUIClient is injected — no live server / GPU. Also covers the
registry opt-in branch: local is selected only when WAN_CAMERA_BACKEND=local +
COMFYUI_LOCAL_URL; otherwise the remote path is preserved verbatim.
"""

from __future__ import annotations

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
from app.domains.routing.providers.registry import build_adapter, register_available_adapters
from app.domains.routing.providers.wan_camera_local import WanCameraLocalAdapter


class FakeClient:
    def __init__(self, *, histories=None, prompt_id="p-1", raise_on_submit=None):
        self.histories = list(histories or [])
        self.prompt_id = prompt_id
        self.raise_on_submit = raise_on_submit
        self.uploaded = []
        self.submitted = []
        self.interrupted = False

    def download_bytes(self, url):
        return b"IMG"

    def upload_image(self, filename, data, *, image_type="input", subfolder="", overwrite=True):
        self.uploaded.append(filename)
        return {"name": filename, "subfolder": "", "type": image_type}

    def submit_prompt(self, graph, client_id=None):
        if self.raise_on_submit is not None:
            raise self.raise_on_submit
        self.submitted.append({"graph": graph, "client_id": client_id})
        return {"prompt_id": self.prompt_id}

    def get_history(self, prompt_id):
        return self.histories.pop(0) if self.histories else {}

    def view_url(self, filename, subfolder="", image_type="output"):
        return f"http://gpu/view?filename={filename}&subfolder={subfolder}&type={image_type}"

    def interrupt(self):
        self.interrupted = True

    def clear_queued(self, prompt_id):
        pass

    @staticmethod
    def new_client_id():
        return "cid"


def _request(num_frames=81):
    return {
        "capability": "image_to_video",
        "prompt": "hero product shot",
        "negative_prompt": "blurry, low quality",
        "start_image_url": "https://cdn/start.png",
        "num_frames": num_frames,
        "estimated_seconds": max(1, round(num_frames / 16)),
        "camera": {
            "camera_pose": "ClockWise", "speed": 1.0, "width": 832, "height": 480,
            "length": num_frames, "fx": 0.5, "fy": 0.5, "cx": 0.5, "cy": 0.5,
        },
    }


def test_conforms_to_provider_adapter_protocol():
    a = WanCameraLocalAdapter(client=FakeClient())
    assert isinstance(a, ProviderAdapter)
    assert a.provider_key == "wan_camera"


def test_catalog_matches_remote_shape():
    a = WanCameraLocalAdapter(client=FakeClient())
    listings = a.catalog()
    assert len(listings) == 1
    lst = listings[0]
    assert isinstance(lst, ModelListing)
    assert lst.provider_key == "wan_camera"
    assert lst.model_id == "wan2.2-fun-a14b-control-camera"
    assert lst.capability == "image_to_video"
    assert lst.metering_unit == "seconds"


def test_submit_then_poll_to_completion():
    done = {
        "status": {"status_str": "success", "completed": True},
        "outputs": {"106": {"videos": [{"filename": "out.mp4", "subfolder": "", "type": "output"}]}},
    }
    client = FakeClient(prompt_id="run-42", histories=[{}, done])
    a = WanCameraLocalAdapter(client=client)

    run = a.submit(_request(), {}, "job-1")
    assert run.run_id == "run-42"
    assert run.state == RUN_QUEUED
    assert client.uploaded  # start image uploaded

    run2 = a.poll(run)
    assert run2.state == RUN_RUNNING  # empty history => running, NOT failed
    assert run2.result_ref == ""

    run3 = a.poll(run2)
    assert run3.state == RUN_COMPLETED
    assert run3.result_ref == "http://gpu/view?filename=out.mp4&subfolder=&type=output"
    assert run3.usage is not None
    assert run3.usage.unit == "seconds"
    assert run3.usage.quantity_units == round(81 / 16)  # 5


def test_poll_error_status_is_terminal_failure():
    err = {"status": {"status_str": "error", "completed": False}, "outputs": {}}
    a = WanCameraLocalAdapter(client=FakeClient(histories=[err]))
    run = ProviderRun(provider_key="wan_camera", run_id="r", state=RUN_RUNNING, raw={"num_frames": 81})
    out = a.poll(run)
    assert out.state == RUN_FAILED
    assert out.result_ref == ""
    assert out.usage is None


def test_image_to_video_requires_start_image():
    req = _request()
    req["start_image_url"] = ""
    a = WanCameraLocalAdapter(client=FakeClient())
    with pytest.raises(ProviderError):
        a.submit(req, {}, "job-1")


def test_submit_without_prompt_id_raises():
    class NoId(FakeClient):
        def submit_prompt(self, graph, client_id=None):
            return {}

    a = WanCameraLocalAdapter(client=NoId())
    with pytest.raises(ProviderError):
        a.submit(_request(), {}, "job-1")


def test_poll_terminal_run_is_noop():
    a = WanCameraLocalAdapter(client=FakeClient())
    done = ProviderRun(provider_key="wan_camera", run_id="r", state=RUN_COMPLETED)
    assert a.poll(done) is done


def test_cancel_best_effort_true():
    client = FakeClient()
    a = WanCameraLocalAdapter(client=client)
    run = ProviderRun(provider_key="wan_camera", run_id="r", state=RUN_RUNNING)
    assert a.cancel(run) is True
    assert client.interrupted is True


# --------------------------------------------------------------------------- #
# registry opt-in branch — local vs remote selection
# --------------------------------------------------------------------------- #
def test_registry_selects_local_when_backend_local_and_url_set():
    reg = ProviderRegistry()
    keys = register_available_adapters(
        reg, env={"WAN_CAMERA_BACKEND": "local", "COMFYUI_LOCAL_URL": "http://gpu:8188"}
    )
    assert "wan_camera" in keys
    adapter = reg.get("wan_camera")
    assert isinstance(adapter, WanCameraLocalAdapter)


def test_registry_local_needs_url_else_falls_back_to_remote():
    reg = ProviderRegistry()
    # backend=local but no URL -> local skipped; remote path runs with the token.
    keys = register_available_adapters(
        reg, env={"WAN_CAMERA_BACKEND": "local", "COMFY_DEPLOY_TOKEN": "t"}
    )
    assert "wan_camera" in keys
    from app.domains.routing.providers.wan_camera import WanCameraAdapter

    assert isinstance(reg.get("wan_camera"), WanCameraAdapter)


def test_registry_default_preserves_remote_path():
    reg = ProviderRegistry()
    keys = register_available_adapters(reg, env={"COMFY_DEPLOY_TOKEN": "t"})
    assert "wan_camera" in keys
    from app.domains.routing.providers.wan_camera import WanCameraAdapter

    assert isinstance(reg.get("wan_camera"), WanCameraAdapter)


def test_registry_local_not_registered_without_url_or_token():
    reg = ProviderRegistry()
    keys = register_available_adapters(reg, env={"WAN_CAMERA_BACKEND": "local"})
    assert "wan_camera" not in keys


def test_build_adapter_returns_local_when_selected(monkeypatch):
    monkeypatch.setenv("WAN_CAMERA_BACKEND", "local")
    monkeypatch.setenv("COMFYUI_LOCAL_URL", "http://gpu:8188")
    a = build_adapter("wan_camera", "")
    assert isinstance(a, WanCameraLocalAdapter)


def test_build_adapter_returns_remote_by_default(monkeypatch):
    monkeypatch.delenv("WAN_CAMERA_BACKEND", raising=False)
    monkeypatch.delenv("COMFYUI_LOCAL_URL", raising=False)
    from app.domains.routing.providers.wan_camera import WanCameraAdapter

    a = build_adapter("wan_camera", "k")
    assert isinstance(a, WanCameraAdapter)
