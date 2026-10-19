"""LocalComfyUIBackend — submit -> poll -> complete against a fake ComfyUIClient.

No live server / GPU: a canned :class:`FakeClient` returns scripted upload /
prompt / history / view results so the RenderBackend verb logic (envelope state
transitions, pending-vs-terminal history semantics, output-URL resolution) is
verified in isolation. Also asserts the backend registers into the render
backend registry alongside runpod.
"""

from __future__ import annotations

import pytest

from app.services.render.backends.base import BackendError, get_backend
from app.services.render.backends.local_comfyui import LocalComfyUIBackend
from app.services.render.envelope import COMPLETED, FAILED, IN_PROGRESS, IN_QUEUE, RenderJob


class FakeClient:
    """Scripted ComfyUIClient stand-in (records calls, replays history)."""

    def __init__(self, *, histories=None, prompt_id="p-1", raise_on_submit=None, view_bytes=b"MP4"):
        self.histories = list(histories or [])
        self.view_bytes = view_bytes
        self.fetched = []
        self.prompt_id = prompt_id
        self.raise_on_submit = raise_on_submit
        self.uploaded = []
        self.submitted = []
        self.interrupted = False
        self.cleared = None

    def download_bytes(self, url):
        return b"IMG"

    def upload_image(self, filename, data, *, image_type="input", subfolder="", overwrite=True):
        self.uploaded.append(filename)
        return {"name": filename, "subfolder": "", "type": image_type}

    def submit_prompt(self, graph, client_id=None):
        if self.raise_on_submit is not None:
            raise self.raise_on_submit
        self.submitted.append({"graph": graph, "client_id": client_id})
        return {"prompt_id": self.prompt_id, "number": 1, "node_errors": {}}

    def get_history(self, prompt_id):
        return self.histories.pop(0) if self.histories else {}

    def view_url(self, filename, subfolder="", image_type="output"):
        return f"http://gpu:8188/view?filename={filename}&subfolder={subfolder}&type={image_type}"

    def fetch_view(self, filename, subfolder="", image_type="output"):
        self.fetched.append((filename, subfolder, image_type))
        if self.view_bytes is None:
            raise BackendError("local_comfyui", "fetch_view failed: unreachable", retryable=True)
        return self.view_bytes

    def interrupt(self):
        self.interrupted = True

    def clear_queued(self, prompt_id):
        self.cleared = prompt_id

    @staticmethod
    def new_client_id():
        return "cid-test"


def _spec(num_frames=81):
    return {
        "job_id": "job-9",
        "capability": "image_to_video",
        "prompt": "hero shot",
        "negative_prompt": "blurry",
        "start_image_url": "https://cdn/start.png",
        "num_frames": num_frames,
        "camera": {
            "camera_pose": "ClockWise", "speed": 1, "width": 832, "height": 480,
            "length": num_frames, "fx": 0.5, "fy": 0.5, "cx": 0.5, "cy": 0.5,
        },
    }


def test_backend_registered_in_render_registry():
    import app.services.render  # noqa: F401 - triggers registration

    b = get_backend("local_comfyui")
    assert b is not None
    assert b.name == "local_comfyui"


def test_submit_uploads_image_and_returns_in_queue_job():
    client = FakeClient(prompt_id="p-42")
    backend = LocalComfyUIBackend(client=client)
    job = backend.submit(_spec())
    assert job.state == IN_QUEUE
    assert job.provider_ref == "p-42"
    assert job.backend == "local_comfyui"
    assert job.meta["num_frames"] == 81
    assert job.meta["output_node"] == "106"
    # Start image was downloaded + uploaded, and the graph got the uploaded name.
    assert client.uploaded
    submitted_graph = client.submitted[0]["graph"]
    assert submitted_graph["100"]["inputs"]["image"] == client.uploaded[0]
    # Pose translated ClockWise -> CW before injection.
    assert submitted_graph["131"]["inputs"]["camera_pose1"] == "CW"


_DONE_HISTORY = {
    "status": {"status_str": "success", "completed": True},
    "outputs": {"106": {"gifs": [{"filename": "Fun_1.mp4", "subfolder": "", "type": "output"}]}},
}


@pytest.fixture
def rehosted(monkeypatch):
    """Capture R2 re-hosting of completed outputs (no network)."""
    import app.services.render.outputs as outputs

    uploads = []

    def _fake_rehost(job_id, data, filename, content_type=None):
        uploads.append((job_id, data, filename))
        return f"renders/{job_id}/{filename}"

    monkeypatch.setattr(outputs, "rehost_bytes", _fake_rehost)
    return uploads


def test_submit_poll_to_completion_happy_path(rehosted):
    running = {}  # empty history => still queued/running
    client = FakeClient(histories=[running, _DONE_HISTORY])
    backend = LocalComfyUIBackend(client=client)

    job = backend.submit(_spec())
    assert job.state == IN_QUEUE

    job = backend.poll(job)
    assert job.state == IN_PROGRESS  # empty history is pending, NOT failure
    assert job.output_refs == ()

    job = backend.poll(job)
    assert job.state == COMPLETED
    # The LAN-only /view output is fetched and re-hosted to a private R2 key so
    # a browser can play it.
    assert client.fetched == [("Fun_1.mp4", "", "output")]
    assert rehosted == [(job.id, b"MP4", "Fun_1.mp4")]
    assert job.output_refs == (f"renders/{job.id}/Fun_1.mp4",)


def test_completion_keeps_view_url_when_output_fetch_fails(rehosted):
    client = FakeClient(histories=[_DONE_HISTORY], view_bytes=None)
    backend = LocalComfyUIBackend(client=client)
    job = RenderJob(id="j", backend="local_comfyui", state=IN_PROGRESS, provider_ref="p-1")

    out = backend.poll(job)

    assert out.state == COMPLETED
    assert rehosted == []
    assert out.output_refs == (
        "http://gpu:8188/view?filename=Fun_1.mp4&subfolder=&type=output",
    )


def test_poll_error_status_is_failure():
    err = {
        "status": {
            "status_str": "error",
            "completed": False,
            "messages": [["execution_error", {"exception_message": "sampler OOM"}]],
        },
        "outputs": {},
    }
    client = FakeClient(histories=[err])
    backend = LocalComfyUIBackend(client=client)
    job = RenderJob(id="j", backend="local_comfyui", state=IN_PROGRESS, provider_ref="p-1")
    out = backend.poll(job)
    assert out.state == FAILED
    assert "OOM" in out.error


def test_submit_prompt_validation_error_propagates_as_backend_error():
    boom = BackendError("local_comfyui", "prompt validation failed: node_errors={...}", retryable=False)
    client = FakeClient(raise_on_submit=boom)
    backend = LocalComfyUIBackend(client=client)
    with pytest.raises(BackendError) as ei:
        backend.submit(_spec())
    assert ei.value.retryable is False


def test_poll_terminal_job_is_noop():
    backend = LocalComfyUIBackend(client=FakeClient())
    done = RenderJob(id="j", backend="local_comfyui", state=COMPLETED, provider_ref="p")
    assert backend.poll(done) is done


def test_cancel_interrupts_and_clears_queue():
    client = FakeClient()
    backend = LocalComfyUIBackend(client=client)
    job = RenderJob(id="j", backend="local_comfyui", state=IN_PROGRESS, provider_ref="p-1")
    out = backend.cancel(job)
    assert out.state == "CANCELLED"
    assert client.interrupted is True
    assert client.cleared == "p-1"


class _JsonTransport:
    """A JSON-only render Transport (the exact seam job_client injects)."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def request(self, method, url, *, headers=None, params=None, json=None):
        self.calls.append((method, url))
        return self._responses.pop(0)


class _Resp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self.headers = {}
        self._body = body

    def json(self):
        return self._body

    @property
    def text(self):
        return str(self._body)


def test_injected_json_transport_is_used_not_a_live_call(rehosted):
    """A plain JSON-only Transport injected by job_client must actually be used
    (adapted to the ComfyTransport seam) instead of being dropped for a live call."""
    poll_resp = _Resp(
        200,
        {
            "p-1": {
                "status": {"status_str": "success", "completed": True},
                "outputs": {"106": {"gifs": [{"filename": "Fun_1.mp4", "subfolder": "", "type": "output"}]}},
            }
        },
    )
    transport = _JsonTransport([poll_resp])
    # No client injected: _client_for must wrap the transport (base_url provided
    # so no config lookup / no live RequestsComfyTransport is built).
    backend = LocalComfyUIBackend(base_url="http://gpu:8188", timeout_s=5)
    job = RenderJob(id="j", backend="local_comfyui", state=IN_PROGRESS, provider_ref="p-1")

    out = backend.poll(job, transport=transport)

    assert out.state == COMPLETED
    # History poll, then the output fetch for re-hosting, both on the injected
    # transport (never a live call).
    assert transport.calls[0] == ("GET", "http://gpu:8188/history/p-1")
    assert transport.calls[1:] == [
        ("GET", "http://gpu:8188/view?filename=Fun_1.mp4&subfolder=&type=output")
    ]


def test_warm_asserts_required_nodes_present():
    class WarmClient(FakeClient):
        def __init__(self, info):
            super().__init__()
            self._info = info

        def object_info(self):
            return self._info

    present = {
        "FunTextBox": {}, "CameraCombineFromChaoJie": {},
        "CameraTrajectoryFromChaoJie": {}, "Wan2_2FunV2VSampler": {},
    }
    backend = LocalComfyUIBackend(client=WarmClient(present))
    assert backend.warm("wan") is True

    backend_missing = LocalComfyUIBackend(client=WarmClient({"FunTextBox": {}}))
    assert backend_missing.warm("wan") is False
