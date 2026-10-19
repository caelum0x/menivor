"""Unit tests for the AI B-roll generation provider (``app.services.broll_gen``).

No external I/O: the comfyui-deploy REST surface (create-run + poll) and the CDN
download are all served by an in-memory ``_FakeRequests`` double patched over the
module-level ``requests``, and ``time.sleep`` is stubbed so polling never blocks.
Mirrors the LatentSync provider tests (``test_phase3.py``) on the avatar side.

Pins the contract the build plan calls out:

* Registry — ``comfyui`` self-registers; ``get_broll_provider`` resolves it,
  falls back to the default on an unknown id, and raises only on an empty
  registry.
* ``generate_clip`` — t2v/i2v happy paths (queue -> poll ``success`` -> download
  -> temp mp4) returning ``{clip_path, duration, provider_job_id, clip_url}``.
* Graceful degradation — a disabled provider, empty prompt, missing i2v image,
  render failure, or timeout return ``None`` and never raise (a B-roll failure
  must never fail a reel job).
* Input assembly, output-url extraction, duration resolution, and the
  single-retry render loop.
"""

from __future__ import annotations

import time

import pytest

import app.services.broll_gen as broll_pkg
import app.services.broll_gen.base as broll_base
import app.services.broll_gen.comfyui_deploy as comfyui


# =========================================================================== #
# Fake HTTP doubles (comfyui-deploy create-run + poll + CDN download)
# =========================================================================== #
class _FakeResp:
    """Minimal ``requests.Response`` stand-in."""

    def __init__(
        self, *, json_body: dict | None = None, chunks=None, status_error: bool = False
    ) -> None:
        self._json = json_body or {}
        self._chunks = chunks or []
        self._status_error = status_error

    def raise_for_status(self) -> None:
        if self._status_error:
            raise RuntimeError("HTTP 500")

    def json(self) -> dict:
        return self._json

    def iter_content(self, chunk_size: int = 1 << 16):
        yield from self._chunks


class _FakeRequests:
    """Routes ``post``/``get`` by URL to emulate a comfyui-deploy endpoint.

    ``POST {base}/api/run`` queues and returns ``{"run_id": ...}``; the first
    ``GET {base}/api/run`` returns ``pending_statuses`` in order, then a terminal
    ``success`` body carrying ``outputs``; any other ``GET`` is the CDN video
    download and yields fake mp4 bytes. ``calls`` records ``(method, url)`` for
    assertions.
    """

    def __init__(
        self,
        *,
        outputs=None,
        pending_statuses=None,
        run_id: str = "run-abc",
        final_status: str = "success",
        error: str | None = None,
    ) -> None:
        self.outputs = outputs if outputs is not None else [
            {"data": {"videos": [{"url": "https://cdn.example.com/clip.mp4"}]}}
        ]
        self._pending = list(pending_statuses or [])
        self.run_id = run_id
        self.final_status = final_status
        self.error = error
        self.calls: list[tuple[str, str]] = []
        self.posted_bodies: list[dict] = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url))
        assert url.endswith("/api/run")
        self.posted_bodies.append(kwargs.get("json") or {})
        return _FakeResp(json_body={"run_id": self.run_id})

    def get(self, url, **kwargs):
        self.calls.append(("GET", url))
        if url.endswith("/api/run"):
            if self._pending:
                status = self._pending.pop(0)
                return _FakeResp(json_body={"status": status, "run_id": self.run_id})
            body: dict = {"status": self.final_status, "run_id": self.run_id}
            if self.final_status == comfyui._STATUS_SUCCESS:
                body["outputs"] = self.outputs
            if self.error is not None:
                body["error"] = self.error
            return _FakeResp(json_body=body)
        # Otherwise it is the CDN download of the rendered clip.
        return _FakeResp(chunks=[b"fake-mp4-bytes"])


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Never actually sleep between polls."""
    monkeypatch.setattr(time, "sleep", lambda _s: None)


def _enabled_provider(monkeypatch, fake: _FakeRequests) -> comfyui.ComfyUIProvider:
    """A comfyui provider wired with dummy creds + the fake HTTP layer."""
    monkeypatch.setattr(comfyui, "requests", fake)
    provider = comfyui.ComfyUIProvider()
    provider._api_key = "k"
    provider._base_url = "https://cd.example.com"
    provider._deployment_t2v = "dep-t2v"
    provider._deployment_i2v = "dep-i2v"
    provider._client.api_key = "k"
    provider._client.base_url = "https://cd.example.com"
    return provider


# =========================================================================== #
# 1. Registry
# =========================================================================== #
def test_comfyui_registered_in_broll_providers():
    assert "comfyui" in broll_base.BROLL_GEN_PROVIDERS
    assert "comfyui" in broll_pkg.BROLL_GEN_PROVIDERS  # same dict, re-exported


def test_get_broll_provider_resolves_comfyui():
    provider = broll_base.get_broll_provider("comfyui")
    assert provider is broll_base.BROLL_GEN_PROVIDERS["comfyui"]
    assert provider.name == "comfyui"
    assert isinstance(provider, broll_base.BrollGenProvider)


def test_get_broll_provider_unknown_id_falls_back_to_default():
    provider = broll_base.get_broll_provider("does-not-exist")
    assert provider is broll_base.BROLL_GEN_PROVIDERS["comfyui"]


def test_get_broll_provider_empty_registry_raises(monkeypatch):
    monkeypatch.setattr(broll_base, "BROLL_GEN_PROVIDERS", {})
    monkeypatch.setattr(broll_base, "_providers_loaded", True)  # skip re-import
    with pytest.raises(KeyError):
        broll_base.get_broll_provider("comfyui")


def test_register_provider_without_name_is_ignored(monkeypatch):
    monkeypatch.setattr(broll_base, "BROLL_GEN_PROVIDERS", {})

    class _Nameless:
        name = ""

    broll_base.register_broll_provider(_Nameless())
    assert broll_base.BROLL_GEN_PROVIDERS == {}


def test_register_provider_is_idempotent_overwrite(monkeypatch):
    monkeypatch.setattr(broll_base, "BROLL_GEN_PROVIDERS", {})

    class _P:
        def __init__(self, tag):
            self.name = "comfyui"
            self.tag = tag

    first, second = _P("a"), _P("b")
    broll_base.register_broll_provider(first)
    broll_base.register_broll_provider(second)
    assert broll_base.BROLL_GEN_PROVIDERS["comfyui"] is second


# =========================================================================== #
# 2. is_enabled
# =========================================================================== #
def test_is_enabled_requires_key_url_and_deployment(monkeypatch):
    provider = _enabled_provider(monkeypatch, _FakeRequests())
    assert provider.is_enabled() is True

    provider._api_key = ""
    assert provider.is_enabled() is False


def test_is_enabled_false_without_deployment(monkeypatch):
    provider = _enabled_provider(monkeypatch, _FakeRequests())
    provider._deployment_t2v = ""
    assert provider.is_enabled() is False


def test_list_workflows_is_empty():
    assert broll_base.get_broll_provider("comfyui").list_workflows() == []


# =========================================================================== #
# 3. generate_clip — happy paths
# =========================================================================== #
def test_generate_clip_t2v_happy_path(monkeypatch):
    fake = _FakeRequests()
    provider = _enabled_provider(monkeypatch, fake)

    result = provider.generate_clip("neon city street", duration_s=5.0)

    assert result is not None
    assert result["clip_url"] == "https://cdn.example.com/clip.mp4"
    assert result["provider_job_id"] == "run-abc"
    assert result["duration"] == 5.0
    assert result["clip_path"].endswith(".mp4")

    # Queued to the t2v deployment and then polled.
    assert ("POST", "https://cd.example.com/api/run") in fake.calls
    body = fake.posted_bodies[0]
    assert body["deployment_id"] == "dep-t2v"
    assert body["inputs"]["prompt"] == "neon city street"
    # frames = round(5.0 * 16) = 80
    assert body["inputs"]["length"] == 80


def test_generate_clip_i2v_uses_i2v_deployment_and_image(monkeypatch):
    fake = _FakeRequests()
    provider = _enabled_provider(monkeypatch, fake)

    result = provider.generate_clip(
        "pan across the mountains",
        mode="i2v",
        image_url="https://r2.example.com/ref.png",
        duration_s=3.0,
    )

    assert result is not None
    body = fake.posted_bodies[0]
    assert body["deployment_id"] == "dep-i2v"
    assert body["inputs"]["image"] == "https://r2.example.com/ref.png"


def test_generate_clip_rejects_unapproved_workflow_id(monkeypatch):
    fake = _FakeRequests()
    provider = _enabled_provider(monkeypatch, fake)

    provider.generate_clip("x", workflow_id="custom-dep")
    assert fake.posted_bodies[0]["deployment_id"] == "dep-t2v"


def test_generate_clip_polls_through_pending_states(monkeypatch):
    fake = _FakeRequests(pending_statuses=["not-started", "running", "uploading"])
    provider = _enabled_provider(monkeypatch, fake)

    result = provider.generate_clip("slow render")
    assert result is not None
    # 3 pending polls + 1 terminal poll.
    get_polls = [c for c in fake.calls if c == ("GET", "https://cd.example.com/api/run")]
    assert len(get_polls) == 4


def test_generate_clip_prefers_worker_reported_duration(monkeypatch):
    fake = _FakeRequests(
        outputs=[
            {
                "data": {
                    "videos": [{"url": "https://cdn.example.com/clip.mp4"}],
                    "duration": 6.5,
                }
            }
        ]
    )
    provider = _enabled_provider(monkeypatch, fake)

    result = provider.generate_clip("x", duration_s=5.0)
    assert result["duration"] == 6.5


# =========================================================================== #
# 4. generate_clip — graceful degradation (returns None, never raises)
# =========================================================================== #
def test_generate_clip_disabled_returns_none(monkeypatch):
    provider = _enabled_provider(monkeypatch, _FakeRequests())
    provider._api_key = ""  # now disabled
    assert provider.generate_clip("x") is None


def test_generate_clip_empty_prompt_returns_none(monkeypatch):
    provider = _enabled_provider(monkeypatch, _FakeRequests())
    assert provider.generate_clip("   ") is None


def test_generate_clip_i2v_without_image_returns_none(monkeypatch):
    provider = _enabled_provider(monkeypatch, _FakeRequests())
    assert provider.generate_clip("x", mode="i2v") is None


def test_generate_clip_no_deployment_for_mode_returns_none(monkeypatch):
    provider = _enabled_provider(monkeypatch, _FakeRequests())
    provider._deployment_i2v = ""
    # i2v with an image but no i2v deployment and no explicit workflow_id.
    provider._deployment_t2v = "dep-t2v"  # keep enabled
    # Force resolve to i2v-empty by clearing both the i2v default and t2v fallback
    # path: _resolve_deployment('i2v', None) -> _deployment_i2v == "".
    result = provider.generate_clip(
        "x", mode="i2v", image_url="https://r2/x.png"
    )
    assert result is None


def test_generate_clip_render_failure_returns_none(monkeypatch):
    fake = _FakeRequests(final_status="failed", error="oom")
    provider = _enabled_provider(monkeypatch, fake)
    assert provider.generate_clip("x") is None


def test_generate_clip_retries_once_then_succeeds(monkeypatch):
    """A first ``failed`` render is retried; the second attempt succeeds."""
    calls = {"n": 0}
    good = _FakeRequests()

    def flaky_run(deployment_id, inputs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise comfyui.ComfyDeployError("transient")
        return "run-2"

    provider = _enabled_provider(monkeypatch, good)
    monkeypatch.setattr(provider._client, "run", flaky_run)
    monkeypatch.setattr(
        provider._client,
        "wait",
        lambda run_id, timeout=0.0: {
            "run_id": run_id,
            "outputs": good.outputs,
        },
    )

    result = provider.generate_clip("x")
    assert result is not None
    assert result["provider_job_id"] == "run-2"
    assert calls["n"] == 2


def test_generate_clip_timeout_returns_none_without_retry(monkeypatch):
    attempts = {"n": 0}

    def timeout_run(deployment_id, inputs):
        attempts["n"] += 1
        return "run-x"

    provider = _enabled_provider(monkeypatch, _FakeRequests())
    monkeypatch.setattr(provider._client, "run", timeout_run)

    def boom(run_id, timeout=0.0):
        raise TimeoutError("30 min cap")

    monkeypatch.setattr(provider._client, "wait", boom)

    assert provider.generate_clip("x") is None
    assert attempts["n"] == 1  # a full timeout is NOT retried


def test_generate_clip_no_output_url_returns_none(monkeypatch):
    fake = _FakeRequests(outputs=[{"data": {"text": "no media here"}}])
    provider = _enabled_provider(monkeypatch, fake)
    assert provider.generate_clip("x") is None


def test_generate_clip_download_failure_returns_none(monkeypatch):
    fake = _FakeRequests()
    provider = _enabled_provider(monkeypatch, fake)
    monkeypatch.setattr(
        comfyui.ComfyUIProvider, "_download_to_temp", staticmethod(lambda url, rid: None)
    )
    assert provider.generate_clip("x") is None


# =========================================================================== #
# 5. _build_inputs
# =========================================================================== #
def test_build_inputs_derives_frames_and_merges_extra():
    inputs = comfyui.ComfyUIProvider._build_inputs(
        prompt="p",
        mode="t2v",
        image_url=None,
        width=1080,
        height=1920,
        duration_s=4.0,
        seed=7,
        extra_inputs={"motion_strength": 0.8, "length": 999},
    )
    assert inputs["prompt"] == "p"
    assert inputs["width"] == 1080
    assert inputs["height"] == 1920
    assert inputs["seed"] == 7
    assert inputs["motion_strength"] == 0.8
    # extra_inputs is merged last and wins over the derived frame count.
    assert inputs["length"] == 999


def test_build_inputs_omits_seed_and_image_by_default():
    inputs = comfyui.ComfyUIProvider._build_inputs(
        prompt="p",
        mode="t2v",
        image_url="https://x/y.png",  # ignored in t2v
        width=1080,
        height=1920,
        duration_s=5.0,
        seed=None,
        extra_inputs=None,
    )
    assert "seed" not in inputs
    assert "image" not in inputs
    assert inputs["length"] == 80


# =========================================================================== #
# 6. _extract_output_url / _resolve_duration
# =========================================================================== #
@pytest.mark.parametrize(
    "outputs,expected",
    [
        (
            [{"data": {"videos": [{"url": "https://cdn/x.mp4"}]}}],
            "https://cdn/x.mp4",
        ),
        (
            [{"data": {"files": [{"url": "https://cdn/x.webm"}]}}],
            "https://cdn/x.webm",
        ),
        (
            [{"data": {"video_url": "https://cdn/flat.mov"}}],
            "https://cdn/flat.mov",
        ),
        # A non-video url is accepted as a fallback when no video is present.
        (
            [{"data": {"images": [{"url": "https://cdn/frame.png"}]}}],
            "https://cdn/frame.png",
        ),
        # A real video is preferred over an earlier non-video url.
        (
            [
                {"data": {"images": [{"url": "https://cdn/frame.png"}]}},
                {"data": {"videos": [{"url": "https://cdn/real.mp4"}]}},
            ],
            "https://cdn/real.mp4",
        ),
        ([], None),
        ("not-a-list", None),
        ([{"data": {"nope": 1}}], None),
    ],
)
def test_extract_output_url(outputs, expected):
    assert comfyui.ComfyUIProvider._extract_output_url({"outputs": outputs}) == expected


def test_extract_output_url_ignores_non_http_values():
    run = {"outputs": [{"data": {"url": "/local/path.mp4"}}]}
    assert comfyui.ComfyUIProvider._extract_output_url(run) is None


def test_extract_output_url_handles_url_with_query_string():
    run = {"outputs": [{"data": {"videos": [{"url": "https://cdn/x.mp4?sig=abc"}]}}]}
    assert (
        comfyui.ComfyUIProvider._extract_output_url(run) == "https://cdn/x.mp4?sig=abc"
    )


def test_resolve_duration_falls_back_to_requested():
    run = {"outputs": [{"data": {"videos": [{"url": "https://cdn/x.mp4"}]}}]}
    assert comfyui.ComfyUIProvider._resolve_duration(run, 5.0) == 5.0


def test_resolve_duration_ignores_non_positive_worker_value():
    run = {"outputs": [{"data": {"duration": 0}}]}
    assert comfyui.ComfyUIProvider._resolve_duration(run, 4.0) == 4.0


# =========================================================================== #
# 7. ComfyDeployClient (create-run + poll internals)
# =========================================================================== #
def test_client_run_returns_run_id(monkeypatch):
    fake = _FakeRequests(run_id="run-77")
    monkeypatch.setattr(comfyui, "requests", fake)
    client = comfyui.ComfyDeployClient(api_key="k", base_url="https://cd.example.com")
    assert client.run("dep-1", {"prompt": "p"}) == "run-77"


def test_client_run_requires_deployment_id():
    client = comfyui.ComfyDeployClient(api_key="k", base_url="https://cd.example.com")
    with pytest.raises(comfyui.ComfyDeployError):
        client.run("", {"prompt": "p"})


def test_client_run_missing_run_id_raises(monkeypatch):
    class _NoRunId(_FakeRequests):
        def post(self, url, **kwargs):
            self.calls.append(("POST", url))
            return _FakeResp(json_body={})  # no run_id

    monkeypatch.setattr(comfyui, "requests", _NoRunId())
    client = comfyui.ComfyDeployClient(api_key="k", base_url="https://cd.example.com")
    with pytest.raises(comfyui.ComfyDeployError):
        client.run("dep-1", {"prompt": "p"})


def test_client_run_url_requires_base_url():
    client = comfyui.ComfyDeployClient(api_key="k", base_url="")
    with pytest.raises(comfyui.ComfyDeployError):
        client.run("dep-1", {"prompt": "p"})


def test_client_wait_success_returns_body(monkeypatch):
    fake = _FakeRequests(pending_statuses=["running"])
    monkeypatch.setattr(comfyui, "requests", fake)
    client = comfyui.ComfyDeployClient(api_key="k", base_url="https://cd.example.com")
    body = client.wait("run-abc", interval=0.0, timeout=10.0)
    assert body["status"] == "success"


def test_client_wait_failed_raises(monkeypatch):
    fake = _FakeRequests(final_status="failed", error="cuda oom")
    monkeypatch.setattr(comfyui, "requests", fake)
    client = comfyui.ComfyDeployClient(api_key="k", base_url="https://cd.example.com")
    with pytest.raises(comfyui.ComfyDeployError):
        client.wait("run-abc", interval=0.0, timeout=10.0)


def test_client_wait_times_out(monkeypatch):
    """A run that never leaves 'running' raises TimeoutError at the deadline."""
    clock = {"t": 0.0}

    def fake_monotonic():
        clock["t"] += 5.0
        return clock["t"]

    monkeypatch.setattr(time, "monotonic", fake_monotonic)

    class _AlwaysRunning(_FakeRequests):
        def get(self, url, **kwargs):
            self.calls.append(("GET", url))
            return _FakeResp(json_body={"status": "running"})

    monkeypatch.setattr(comfyui, "requests", _AlwaysRunning())
    client = comfyui.ComfyDeployClient(api_key="k", base_url="https://cd.example.com")
    with pytest.raises(TimeoutError):
        client.wait("run-abc", interval=0.0, timeout=3.0)


def test_client_wait_tolerates_transient_poll_errors(monkeypatch):
    """A transient HTTP error during polling is retried until success."""
    state = {"n": 0}

    class _Flaky(_FakeRequests):
        def get(self, url, **kwargs):
            self.calls.append(("GET", url))
            state["n"] += 1
            if state["n"] == 1:
                return _FakeResp(status_error=True)  # raise_for_status -> boom
            return _FakeResp(json_body={"status": "success", "outputs": self.outputs})

    monkeypatch.setattr(comfyui, "requests", _Flaky())
    client = comfyui.ComfyDeployClient(api_key="k", base_url="https://cd.example.com")
    body = client.wait("run-abc", interval=0.0, timeout=30.0)
    assert body["status"] == "success"
    assert state["n"] == 2


# =========================================================================== #
# 8. _comfyui_config defensive read
# =========================================================================== #
def test_comfyui_config_handles_missing_section(monkeypatch):
    monkeypatch.setattr(comfyui.config, "comfyui", None, raising=False)
    assert comfyui._comfyui_config() == {}


def test_comfyui_config_handles_non_mapping(monkeypatch):
    monkeypatch.setattr(comfyui.config, "comfyui", 12345, raising=False)
    assert comfyui._comfyui_config() == {}
