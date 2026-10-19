"""Local-ComfyUI camera-control provider (WanCameraLocalAdapter).

The routing-layer sibling of ``WanCameraAdapter`` (``wan_camera.py``): it exposes
the SAME ``provider_key = "wan_camera"`` and mirrors that adapter's exact
submit/poll/quote/catalog/normalize_usage envelope, so the routing / worker /
motion layers never learn the render is happening on a LOCAL ComfyUI server
instead of the hosted comfyui-deploy endpoint. It consumes the UNCHANGED
``to_wan_request`` dict.

Internally it delegates:

* network → :mod:`app.services.render.backends._comfyui_client` (the native
  ``/upload/image`` + ``/prompt`` + ``/history`` + ``/view`` seam)
* graph shaping → :mod:`app.services.render.backends._wan_camera_graph`

This is a one-directional ``providers → services`` import; ``services/render``
never imports ``providers``, so there is no cycle.

Flow:

* ``submit`` — upload the start image → ``POST /prompt`` → ``ProviderRun`` (queued,
  ``run_id = prompt_id``, ``raw`` carries num_frames).
* ``poll``   — ``GET /history``: empty → running (NOT failed); a terminal entry →
  completed/failed. On success ``result_ref`` is the ``/view`` URL.

License: Wan2.2-Fun ships open weights (Apache-2.0) — this route is paid-safe
(``LICENSE_CLASS = "open_weights"``, ``PAID_SAFE = True``) and needs NO cloud
credential (the $0-wallet path).
"""

from __future__ import annotations

import uuid
from typing import Any

from app.domains.routing.base import (
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_QUEUED,
    RUN_RUNNING,
    ModelListing,
    NormalizedUsage,
    ProviderError,
    ProviderRun,
    QuoteResult,
)
from app.domains.routing.providers._pricing import quote_from_price
from app.services.render.backends._comfyui_client import BackendError, ComfyUIClient
from app.services.render.backends._wan_camera_graph import build_graph, resolve_output

_PROVIDER_KEY = "wan_camera"
WAN_CAMERA_MODEL_ID = "wan2.2-fun-a14b-control-camera"

# Open weights (Apache-2.0) — safe for paying users.
LICENSE_CLASS = "open_weights"
PAID_SAFE = True

# Metering reference fps (mirrors the remote adapter): seconds = round(frames/16).
_METER_FPS = 16


class WanCameraLocalAdapter:
    """ProviderAdapter for Wan2.2-Fun camera control via a LOCAL ComfyUI server."""

    def __init__(
        self,
        *,
        base_url: str = "",
        client: ComfyUIClient | None = None,
    ) -> None:
        self._base_url = base_url
        self._client = client

    @property
    def provider_key(self) -> str:
        return _PROVIDER_KEY

    def _get_client(self) -> ComfyUIClient:
        if self._client is None:
            if not self._base_url:
                raise ProviderError(
                    "wan_camera local backend requires a ComfyUI base_url (COMFYUI_LOCAL_URL)",
                    provider_key=_PROVIDER_KEY,
                    retryable=False,
                )
            self._client = ComfyUIClient(self._base_url)
        return self._client

    # -- catalog ------------------------------------------------------------ #
    def catalog(self) -> list[ModelListing]:
        return [
            ModelListing(
                provider_key=_PROVIDER_KEY,
                model_id=WAN_CAMERA_MODEL_ID,
                capability="image_to_video",
                metering_unit="seconds",
                latency_band="slow",
            )
        ]

    # -- quote -------------------------------------------------------------- #
    def quote(self, request: Any, price_version: Any) -> QuoteResult:
        est = None
        if isinstance(request, dict):
            est = request.get("estimated_seconds") or request.get("estimated_quantity")
        return quote_from_price(price_version, est)

    # -- submit ------------------------------------------------------------- #
    def submit(self, request: Any, snapshot: dict, correlation_id: str) -> ProviderRun:
        req = request if isinstance(request, dict) else {}
        if req.get("capability") == "image_to_video" and not req.get("start_image_url"):
            raise ProviderError(
                "wan_camera image_to_video requires a start_image_url",
                provider_key=_PROVIDER_KEY,
                retryable=False,
            )
        client = self._get_client()
        try:
            image_ref = self._upload_start_image(client, req)
            graph = build_graph(req, image_ref)
            body = client.submit_prompt(graph, ComfyUIClient.new_client_id())
        except BackendError as exc:
            raise ProviderError(
                str(exc), provider_key=_PROVIDER_KEY, retryable=exc.retryable
            ) from exc
        prompt_id = str(body.get("prompt_id") or "")
        if not prompt_id:
            raise ProviderError(
                f"wan_camera submit returned no prompt_id: {str(body)[:200]}",
                provider_key=_PROVIDER_KEY,
                retryable=False,
            )
        num_frames = int(req.get("num_frames", 0) or 0)
        return ProviderRun(
            provider_key=_PROVIDER_KEY,
            run_id=prompt_id,
            state=RUN_QUEUED,
            raw={"num_frames": num_frames, "prompt_id": prompt_id},
        )

    # -- poll --------------------------------------------------------------- #
    def poll(self, run: ProviderRun) -> ProviderRun:
        if run.is_terminal:
            return run
        client = self._get_client()
        try:
            entry = client.get_history(run.run_id)
        except BackendError as exc:
            raise ProviderError(
                str(exc), provider_key=_PROVIDER_KEY, retryable=exc.retryable
            ) from exc

        prior_frames = run.raw.get("num_frames") if isinstance(run.raw, dict) else None
        raw = {"num_frames": prior_frames} if prior_frames else {}

        # Empty {} => queued/running (NOT failed).
        if not entry:
            return ProviderRun(
                provider_key=_PROVIDER_KEY,
                run_id=run.run_id,
                state=RUN_RUNNING,
                progress=run.progress,
                raw=raw,
            )

        status = entry.get("status") if isinstance(entry.get("status"), dict) else {}
        status_str = str(status.get("status_str", "") or "").lower()
        completed = status.get("completed")
        outputs = entry.get("outputs") if isinstance(entry.get("outputs"), dict) else {}

        if status_str == "success" or (completed is True and status_str != "error"):
            ref = resolve_output(outputs)
            if ref is None:
                return ProviderRun(
                    provider_key=_PROVIDER_KEY, run_id=run.run_id,
                    state=RUN_RUNNING, progress=run.progress, raw=raw,
                )
            result_ref = client.view_url(ref["filename"], ref["subfolder"], ref["type"])
            return ProviderRun(
                provider_key=_PROVIDER_KEY,
                run_id=run.run_id,
                state=RUN_COMPLETED,
                progress=100,
                result_ref=result_ref,
                usage=self.normalize_usage(raw),
                raw=raw,
            )

        if status_str == "error" or completed is False:
            return ProviderRun(
                provider_key=_PROVIDER_KEY, run_id=run.run_id, state=RUN_FAILED, raw=raw
            )

        return ProviderRun(
            provider_key=_PROVIDER_KEY, run_id=run.run_id,
            state=RUN_RUNNING, progress=run.progress, raw=raw,
        )

    # -- cancel ------------------------------------------------------------- #
    def cancel(self, run: ProviderRun) -> bool:
        try:
            client = self._get_client()
            client.interrupt()
            client.clear_queued(run.run_id)
            return True
        except Exception:  # best-effort — local runs are free
            return False

    # -- usage -------------------------------------------------------------- #
    def normalize_usage(self, payload: dict) -> NormalizedUsage:
        payload = payload or {}
        num_frames = int(payload.get("num_frames", 0) or 0)
        seconds = max(1, round(num_frames / _METER_FPS)) if num_frames > 0 else 0
        return NormalizedUsage(
            unit="seconds",
            quantity_units=seconds,
            cost_micros=0,
            raw=dict(payload),
        )

    # -- helpers ------------------------------------------------------------ #
    def _upload_start_image(self, client: ComfyUIClient, req: dict) -> dict | None:
        url = str(req.get("start_image_url") or "")
        if not url.startswith(("http://", "https://")):
            return None
        data = client.download_bytes(url)
        filename = f"reelforge_start_{uuid.uuid4().hex}.png"
        return client.upload_image(filename, data, image_type="input")
