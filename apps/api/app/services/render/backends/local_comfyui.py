"""Native-ComfyUI render backend (the ``$0-wallet`` local generation path).

``LocalComfyUIBackend`` is the :class:`RenderBackend`-protocol sibling of
``runpod.py``, but it speaks the *native* ComfyUI API (``/prompt`` + ``/history``
+ ``/view``) against a LOCAL/LAN ComfyUI server instead of a hosted async-GPU
queue. The external model checkouts (ComfyUI, Wan2.2-Fun-A14B Control-Camera,
VideoX-Fun) become usable locally through this backend; the remote comfyui-deploy
/ RunPod paths are untouched (this is additive + opt-in).

Verbs:

* ``submit`` — download the start image (if a URL) → ``upload_image`` → build the
  Wan camera graph → ``submit_prompt`` → :class:`RenderJob` (IN_QUEUE,
  ``provider_ref = prompt_id``, ``meta`` carries num_frames + output_node).
* ``poll``   — ``get_history``; an empty ``{}`` keeps the job IN_PROGRESS
  (queued/running is NOT a failure); a recorded entry reads ``status.status_str``
  (``success`` → COMPLETED with ``output_refs=[view_url]``; ``error`` /
  ``completed=false`` → FAILED).
* ``cancel`` — ``POST /interrupt`` then ``POST /queue {delete:[prompt_id]}``.
* ``warm``   — best-effort ``GET /object_info`` (optionally asserts the Wan custom
  nodes are installed).

Network is the injected :class:`ComfyTransport`; config (url/timeout/poll) is
resolved lazily from ``config.comfyui_local`` and never hardcoded.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.services.render.backends._comfyui_client import (
    ComfyTransport,
    ComfyUIClient,
    RequestsComfyTransport,
)
from app.services.render.backends._wan_camera_graph import (
    build_graph,
    resolve_output,
    snap_length,
)
from app.services.render.backends.base import (
    BackendError,
    RenderBackend,
    Transport,
    register_backend,
)
from app.services.render.envelope import (
    COMPLETED,
    FAILED,
    IN_PROGRESS,
    IN_QUEUE,
    RenderJob,
    transition,
)

# The three Wan camera custom nodes a warm check can assert are installed.
_REQUIRED_NODES: tuple[str, ...] = (
    "FunTextBox",
    "CameraCombineFromChaoJie",
    "CameraTrajectoryFromChaoJie",
    "Wan2_2FunV2VSampler",
)


class _JsonTransportAdapter:
    """Adapts a JSON-only render :class:`Transport` to the :class:`ComfyTransport`
    seam.

    The render layer (``job_client``) always injects a plain ``Transport`` (whose
    only verb is ``request``), so without this adapter ``_client_for`` would drop
    the injected transport and build a live ``RequestsComfyTransport``, letting
    real network calls escape the injectable seam. JSON and raw-bytes GETs
    delegate straight to ``Transport.request``; the native ComfyUI *multipart*
    image upload has no JSON equivalent, so it fails loudly with a clear
    :class:`BackendError` only when an upload is actually attempted.
    """

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def request_json(self, method, url, *, headers=None, params=None, json=None):
        return self._transport.request(
            method, url, headers=headers, params=params, json=json
        )

    def request_bytes(self, method, url, *, headers=None, params=None):
        return self._transport.request(method, url, headers=headers, params=params)

    def request_multipart(self, url, *, files, data=None, headers=None):
        raise BackendError(
            "local_comfyui",
            "multipart image upload requires a native ComfyTransport; the injected "
            "JSON-only render transport cannot perform POST /upload/image",
        )


class LocalComfyUIBackend(RenderBackend):
    name = "local_comfyui"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        client: ComfyUIClient | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self._base_url = base_url
        self._client = client
        self._timeout_s = timeout_s

    # -- config (lazy so import never requires config) ---------------------- #
    def _cfg(self) -> tuple[str, float]:
        base_url = self._base_url
        timeout = self._timeout_s
        if not base_url or timeout is None:
            from app.config import config

            section = getattr(config, "comfyui_local", {}) or {}
            base_url = base_url or str(section.get("url", "") or "")
            timeout = timeout if timeout is not None else float(section.get("timeout_s", 1800) or 1800)
        if not base_url:
            raise BackendError(self.name, "comfyui_local.url not configured")
        return base_url, float(timeout)

    def _client_for(self, transport: Transport | ComfyTransport | None) -> ComfyUIClient:
        if self._client is not None:
            return self._client
        base_url, timeout = self._cfg()
        ctransport: ComfyTransport | None = None
        if transport is not None:
            if hasattr(transport, "request_multipart"):
                ctransport = transport  # a full ComfyTransport was injected
            else:
                # A JSON-only render Transport was injected. Adapt it to the
                # ComfyTransport seam so the injected (possibly fake) transport is
                # actually used, instead of silently falling back to a live call.
                ctransport = _JsonTransportAdapter(transport)
        return ComfyUIClient(
            base_url, transport=ctransport or RequestsComfyTransport(timeout), timeout_s=timeout
        )

    # -- verbs -------------------------------------------------------------- #
    def submit(self, spec: dict, *, transport: Transport = None) -> RenderJob:  # type: ignore[assignment]
        client = self._client_for(transport)
        req = spec if isinstance(spec, dict) else {}

        image_ref = self._prepare_image(client, req)
        graph = build_graph(req, image_ref)
        client_id = ComfyUIClient.new_client_id()
        body = client.submit_prompt(graph, client_id)
        prompt_id = str(body.get("prompt_id") or "")

        camera = req.get("camera") if isinstance(req.get("camera"), dict) else {}
        num_frames = snap_length(camera.get("length") or req.get("num_frames") or 81)
        job = RenderJob(
            id=str(req.get("job_id") or prompt_id),
            backend=self.name,
            workflow_version=str(req.get("workflow_version", "") or "wan22_fun_control_camera"),
            state=IN_QUEUE,
            provider_ref=prompt_id,
            attempts=1,
            meta={"num_frames": num_frames, "output_node": "106", "client_id": client_id},
        )
        return job

    def poll(self, job: RenderJob, *, transport: Transport = None) -> RenderJob:  # type: ignore[assignment]
        if job.is_terminal:
            return job
        client = self._client_for(transport)
        entry = client.get_history(job.provider_ref)
        # Empty {} => queued/running (NOT failure). Keep the job in flight.
        if not entry:
            return transition(job, IN_PROGRESS)

        status = entry.get("status") if isinstance(entry.get("status"), dict) else {}
        status_str = str(status.get("status_str", "") or "").lower()
        completed = status.get("completed")
        outputs = entry.get("outputs") if isinstance(entry.get("outputs"), dict) else {}

        if status_str == "success" or (completed is True and status_str != "error"):
            ref = resolve_output(outputs)
            if ref is None:
                # Recorded as done but the save-node output is not visible yet.
                return transition(job, IN_PROGRESS)
            url = client.view_url(ref["filename"], ref["subfolder"], ref["type"])
            return transition(
                job, COMPLETED, progress=1.0,
                output_refs=(self._durable_ref(client, job, ref, url),),
            )

        if status_str == "error" or completed is False:
            messages = status.get("messages")
            return transition(job, FAILED, error=_first_error(messages) or "comfyui execution failed")

        # Recorded but neither clearly done nor failed -> still running.
        return transition(job, IN_PROGRESS)

    def cancel(self, job: RenderJob, *, transport: Transport = None) -> RenderJob:  # type: ignore[assignment]
        if job.is_terminal:
            return job
        client = self._client_for(transport)
        try:
            client.interrupt()
            client.clear_queued(job.provider_ref)
        except BackendError:
            pass  # best-effort — most local runs are free, so a failed cancel is benign
        return transition(job, "CANCELLED")

    def warm(self, model: str, *, transport: Transport = None) -> bool:  # type: ignore[assignment]
        client = self._client_for(transport)
        try:
            info = client.object_info()
        except BackendError:
            return False
        if not isinstance(info, dict) or not info:
            return False
        # Assert the Wan camera custom nodes are installed on the server.
        return all(node in info for node in _REQUIRED_NODES)

    # -- helpers ------------------------------------------------------------ #
    @staticmethod
    def _durable_ref(client: ComfyUIClient, job: RenderJob, ref: dict, view_url: str) -> str:
        """Copy the ComfyUI output into R2 so browsers get a playable key.

        The ``/view`` URL lives on the render host's LAN and is unreachable from a
        browser, so on completion the bytes are fetched and re-hosted to a private
        R2 key. Best-effort: when R2 is not configured (dev) the raw view URL is
        kept so a same-LAN client can still open it.
        """
        try:
            data = client.fetch_view(ref["filename"], ref["subfolder"], ref["type"])
        except BackendError:
            return view_url
        from app.services.render.outputs import rehost_bytes

        return rehost_bytes(job.id, data, str(ref.get("filename") or "output.mp4")) or view_url

    def _prepare_image(self, client: ComfyUIClient, req: dict) -> dict | None:
        url = str(req.get("start_image_url") or "")
        if not url.startswith(("http://", "https://")):
            return None
        data = client.download_bytes(url)
        filename = f"reelforge_start_{uuid.uuid4().hex}.png"
        return client.upload_image(filename, data, image_type="input")


def _first_error(messages: Any) -> str:
    """Pull a human message out of ComfyUI's ``status.messages`` list of tuples."""
    if isinstance(messages, list):
        for msg in messages:
            if isinstance(msg, (list, tuple)) and len(msg) >= 2 and isinstance(msg[1], dict):
                text = msg[1].get("exception_message") or msg[1].get("error")
                if text:
                    return str(text)
    return ""


register_backend(LocalComfyUIBackend())
