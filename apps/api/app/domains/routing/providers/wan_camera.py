"""Wan2.2-Fun model-native camera-control provider (WanCameraAdapter).

Path B of the Wave 1 motion engine: a *true 3D* camera move rendered by the
Wan2.2-Fun-A14B "Control-Camera" model, driven through a ComfyUI workflow
deployed as a serverless GPU endpoint via `comfyui-deploy
<https://github.com/BennyKok/comfyui-deploy>`_. It implements the shared
``ProviderAdapter`` contract (submit/poll/cancel/quote/catalog/normalize_usage)
exactly like the hosted async-media adapters, so the routing/worker layer never
learns Wan/ComfyUI specifics.

Shape (verified against comfyui-deploy's ``registerCreateRunRoute`` /
``registerGetOutputRoute`` + its ``workflow_run_status`` enum):

1. **submit** — ``POST {base}/api/run`` with a ComfyUI-Deploy body
   ``{"deployment_id": str, "inputs": {str: str | number}}`` and returns the
   ``run_id``. ``inputs`` feed the deployed graph's external-input nodes: the
   **WanCameraEmbedding** node reads the camera pose/intrinsics/trajectory from
   ``request["camera"]``; the **Fun-Control sampler** reads
   ``prompt`` / ``negative_prompt`` / ``start_image_url`` / ``num_frames``.
2. **poll** — ``GET {base}/api/run?run_id={id}`` until the run reaches a terminal
   ``status`` (``success`` | ``failed``; ``not-started`` / ``running`` /
   ``uploading`` are pending). On success the output MP4 url becomes
   ``result_ref`` and usage is metered in seconds (``round(num_frames / 16)``).

The camera-control *input* is the shared spec from ``domains/motion`` — the
worker builds the request dict via ``motion.spec.to_wan_request`` and hands it to
:meth:`submit`. This module imports ``CameraControlSpec`` / ``to_wan_request``
for typing + shape only (guarded so it imports cleanly before the motion domain
lands). The adapter itself operates purely on the request *dict*, so it never
needs the spec object at runtime.

All network I/O flows through the injected ``request_fn`` (``build_json_transport``)
— the single, fakeable seam. Every upstream failure is normalized to
:class:`ProviderError`; a raw HTTP/SDK error never escapes.

License: Wan2.2-Fun ships open weights (Apache-2.0), so this route is paid-safe
(``LICENSE_CLASS = "open_weights"``, ``PAID_SAFE = True``).
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

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
from app.domains.routing.providers._transport import build_json_transport

# The camera-control input contract is owned by the motion domain. Import for
# typing/shape only, guarded so this provider imports cleanly before motion
# lands (the adapter works on the request *dict*, never the spec object).
if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.domains.motion.spec import CameraControlSpec, to_wan_request
else:  # pragma: no cover - runtime best-effort re-export
    try:
        from app.domains.motion.spec import CameraControlSpec, to_wan_request
    except Exception:  # motion domain not yet present
        CameraControlSpec = None  # type: ignore[assignment,misc]
        to_wan_request = None  # type: ignore[assignment,misc]

# --------------------------------------------------------------------------- #
# Module constants
# --------------------------------------------------------------------------- #
_PROVIDER_KEY = "wan_camera"
_DEFAULT_BASE_URL = "https://api.comfydeploy.com"
WAN_CAMERA_MODEL_ID = "wan2.2-fun-a14b-control-camera"

# Open weights (Apache-2.0) — safe for paying users.
LICENSE_CLASS = "open_weights"
PAID_SAFE = True

# Wan's 9 named camera moves (WanCameraEmbedding). "Custom" uses pose_trajectory.
WAN_NAMED_MOVES = frozenset(
    {
        "Static",
        "Pan Up",
        "Pan Down",
        "Pan Left",
        "Pan Right",
        "Zoom In",
        "Zoom Out",
        "Anti Clockwise",
        "ClockWise",
    }
)

# Metering: the VAE produces one latent-visible frame per temporal step; usage is
# billed in seconds at this reference fps (fps-agnostic seconds estimate).
_METER_FPS = 16

# comfyui-deploy workflow_run_status enum (web/src/db/schema.ts).
_STATE_MAP = {
    "not-started": RUN_QUEUED,
    "queued": RUN_QUEUED,
    "pending": RUN_QUEUED,
    "running": RUN_RUNNING,
    "uploading": RUN_RUNNING,
    "processing": RUN_RUNNING,
    "success": RUN_COMPLETED,
    "succeeded": RUN_COMPLETED,
    "completed": RUN_COMPLETED,
    "failed": RUN_FAILED,
    "error": RUN_FAILED,
    "cancelled": RUN_FAILED,
    "canceled": RUN_FAILED,
}

# Output node data blobs (comfyui-deploy stores save-node outputs under these).
_OUTPUT_LIST_KEYS: tuple[str, ...] = ("videos", "gifs", "files", "images")
_OUTPUT_URL_KEYS: tuple[str, ...] = ("url", "video_url", "video", "output_url")
_VIDEO_EXTS: tuple[str, ...] = (".mp4", ".webm", ".mov")


class WanCameraAdapter:
    """ProviderAdapter for Wan2.2-Fun camera control via ComfyUI-Deploy."""

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str | None = None,
        workflow_id: str = "",
        request_fn: Any = None,
    ) -> None:
        self._api_key = api_key or os.getenv("COMFY_DEPLOY_TOKEN", "") or os.getenv(
            "WAN_CAMERA_API_KEY", ""
        )
        self._base_url = (
            base_url
            or os.getenv("WAN_CAMERA_BASE_URL", "")
            or os.getenv("COMFY_DEPLOY_BASE_URL", "")
            or _DEFAULT_BASE_URL
        )
        self._workflow_id = workflow_id or os.getenv("WAN_CAMERA_WORKFLOW_ID", "")
        self._request = request_fn or build_json_transport(
            provider_key=_PROVIDER_KEY,
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )

    @property
    def provider_key(self) -> str:
        return _PROVIDER_KEY

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
        deployment_id = str(
            (snapshot or {}).get("workflow_id")
            or (snapshot or {}).get("deployment_id")
            or self._workflow_id
            or ""
        )
        if not deployment_id:
            raise ProviderError(
                "wan_camera submit requires a deployment/workflow id "
                "(snapshot.workflow_id or WAN_CAMERA_WORKFLOW_ID)",
                provider_key=_PROVIDER_KEY,
                retryable=False,
            )
        if req.get("capability") == "image_to_video" and not req.get("start_image_url"):
            raise ProviderError(
                "wan_camera image_to_video requires a start_image_url",
                provider_key=_PROVIDER_KEY,
                retryable=False,
            )

        num_frames = int(req.get("num_frames", 0) or 0)
        body = {
            "deployment_id": deployment_id,
            "inputs": _build_inputs(req),
        }
        payload = self._request("POST", "/api/run", json=body)
        run_id = str((payload or {}).get("run_id", "") or (payload or {}).get("id", "") or "")
        if not run_id:
            raise ProviderError(
                f"wan_camera submit returned no run_id: {str(payload)[:200]}",
                provider_key=_PROVIDER_KEY,
                retryable=False,
            )
        # Carry num_frames so poll can meter usage without a second lookup.
        raw = dict(payload or {})
        raw["num_frames"] = num_frames
        return ProviderRun(
            provider_key=_PROVIDER_KEY,
            run_id=run_id,
            state=self._map_state((payload or {}).get("status") or "queued"),
            raw=raw,
        )

    # -- poll --------------------------------------------------------------- #
    def poll(self, run: ProviderRun) -> ProviderRun:
        if run.is_terminal:
            return run
        payload = self._request("GET", f"/api/run?run_id={run.run_id}")
        payload = payload or {}
        state = self._map_state(payload.get("status") or "running")
        # Carry the submit-time frame count forward across poll cycles so usage
        # can always be metered on the terminal poll (the status endpoint does
        # not echo the request's num_frames).
        prior_frames = run.raw.get("num_frames") if isinstance(run.raw, dict) else None
        raw = dict(payload)
        if prior_frames and not raw.get("num_frames"):
            raw["num_frames"] = prior_frames
        result_ref = ""
        usage = None
        if state == RUN_COMPLETED:
            result_ref = _extract_output_url(payload)
            usage = self.normalize_usage(raw)
        return ProviderRun(
            provider_key=_PROVIDER_KEY,
            run_id=run.run_id,
            state=state,
            progress=100 if state == RUN_COMPLETED else run.progress,
            result_ref=result_ref,
            usage=usage,
            raw=raw,
        )

    # -- cancel ------------------------------------------------------------- #
    def cancel(self, run: ProviderRun) -> bool:
        try:
            self._request("POST", f"/api/run/{run.run_id}/cancel")
            return True
        except Exception:  # best-effort — most GPU runs bill on submit
            return False

    # -- usage -------------------------------------------------------------- #
    def normalize_usage(self, payload: dict) -> NormalizedUsage:
        payload = payload or {}
        num_frames = _read_num_frames(payload)
        seconds = max(1, round(num_frames / _METER_FPS)) if num_frames > 0 else 0
        return NormalizedUsage(
            unit="seconds",
            quantity_units=seconds,
            cost_micros=0,
            raw=dict(payload),
        )

    # -- helpers ------------------------------------------------------------ #
    def _map_state(self, raw: Any) -> str:
        return _STATE_MAP.get(str(raw or "").strip().lower(), RUN_RUNNING)


# --------------------------------------------------------------------------- #
# Pure helpers (module-level so they stay unit-testable + side-effect free)
# --------------------------------------------------------------------------- #
def _build_inputs(req: dict) -> dict:
    """Flatten a ``to_wan_request`` dict into ComfyUI external-input values.

    WanCameraEmbedding node inputs come from ``req["camera"]`` (pose, speed,
    intrinsics, trajectory); the Fun-Control sampler inputs come from the
    top-level prompt / negative_prompt / start image / frame count. All values are
    ``str | number``; the ragged ``pose_trajectory`` is JSON-encoded so it can
    ride an ExternalText node.
    """
    camera = req.get("camera") if isinstance(req.get("camera"), dict) else {}
    inputs: dict[str, Any] = {}
    for key, value in camera.items():
        if key == "pose_trajectory":
            inputs[key] = json.dumps(value or [])
        elif isinstance(value, (str, int, float)):
            inputs[key] = value
        else:
            inputs[key] = json.dumps(value)
    # Fun-Control sampler inputs.
    inputs["prompt"] = str(req.get("prompt", "") or "")
    inputs["negative_prompt"] = str(req.get("negative_prompt", "") or "")
    inputs["start_image_url"] = str(req.get("start_image_url", "") or "")
    inputs["num_frames"] = int(req.get("num_frames", 0) or 0)
    # Wave-4 identity lock: copy the IPAdapter + LoRA conditioning values into the
    # external inputs so the deployed graph's real "IPAdapter Apply" + "LoraLoader"
    # nodes are fed. The presigned reference/weights URLs are supplied by the
    # training/render layer (never a raw client URL). Silent no-op when absent —
    # a workflow without those nodes is unaffected.
    _apply_identity_lock(inputs, req.get("identity_lock"))
    return inputs


# Keys the deployed IPAdapter + LoraLoader nodes read from the external inputs.
_IDENTITY_LOCK_KEYS: tuple[str, ...] = (
    "ip_reference_url",
    "ip_weight",
    "lora_url",
    "lora_weight",
)


def _apply_identity_lock(inputs: dict, identity_lock: Any) -> None:
    """Copy ``identity_lock.{ip_reference_url,ip_weight,lora_url,lora_weight}``.

    Only ``str | number`` values are copied (the ComfyUI external-input contract);
    empty/None values are dropped so a partial lock never overwrites a node with a
    blank.
    """
    if not isinstance(identity_lock, dict):
        return
    for key in _IDENTITY_LOCK_KEYS:
        value = identity_lock.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, (str, int, float)):
            inputs[key] = value


def _read_num_frames(payload: dict) -> int:
    """Read the frame count from a payload (carried from submit or an output)."""
    for key in ("num_frames", "length", "frames"):
        raw = payload.get(key)
        if raw:
            try:
                return int(raw)
            except (TypeError, ValueError):
                continue
    # Fall back to a duration-in-frames inside an output data blob.
    outputs = payload.get("outputs")
    if isinstance(outputs, list):
        for output in outputs:
            data = output.get("data") if isinstance(output, dict) else None
            if isinstance(data, dict):
                for key in ("num_frames", "length", "frames"):
                    raw = data.get(key)
                    if raw:
                        try:
                            return int(raw)
                        except (TypeError, ValueError):
                            continue
    return 0


def _extract_output_url(payload: dict) -> str:
    """Find the rendered MP4 url inside a run's ``outputs`` list.

    Prefers a real video extension; otherwise returns the first usable http url so
    an unexpected save-node shape still yields a clip.
    """
    outputs = payload.get("outputs")
    if not isinstance(outputs, list):
        # Some deployments expose a flat top-level url on success.
        for key in _OUTPUT_URL_KEYS:
            if _is_http_url(payload.get(key)):
                return str(payload[key])
        return ""

    first_url = ""
    for output in outputs:
        data = output.get("data") if isinstance(output, dict) else None
        if not isinstance(data, dict):
            continue
        for url in _iter_data_urls(data):
            if url.lower().split("?", 1)[0].endswith(_VIDEO_EXTS):
                return url
            if not first_url:
                first_url = url
    return first_url


def _iter_data_urls(data: dict):
    for key in _OUTPUT_LIST_KEYS:
        items = data.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and _is_http_url(item.get("url")):
                    yield item["url"]
                elif _is_http_url(item):
                    yield item
    for key in _OUTPUT_URL_KEYS:
        if _is_http_url(data.get(key)):
            yield data[key]


def _is_http_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))
