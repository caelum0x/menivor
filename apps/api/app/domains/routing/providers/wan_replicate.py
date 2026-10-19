"""Wan 2.2 (open weights) video generation — a REAL adapter over Replicate.

The sixth real backend and a sixth distinct protocol: Replicate's **prediction**
lifecycle (``starting → processing → succeeded/failed``) against an official model
endpoint. Imports ``requests``; runs live with a real ``REPLICATE_API_TOKEN``
(``Bearer``). Wan is open-weight, so this is the hosted "no-GPU-needed" tier;
a self-hosted deployment would swap ``_BASE`` for the internal endpoint and keep
the same shape.

Real flow:
  1. **submit**  ``POST /v1/models/{owner}/{name}/predictions`` (Bearer)
                 body ``{input:{prompt, aspect_ratio, num_frames…}}``
                 → ``{"id", "status":"starting", "urls":{"get"}}``.
  2. **poll**    ``GET /v1/predictions/{id}`` →
                 ``{status: starting|processing|succeeded|failed|canceled,
                    output: url|[url], error}``.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.domains.routing.providers.kling_fal import (
    ACCEPTANCE_DEFINITE_NO,
    ACCEPTANCE_UNKNOWN,
    KlingError as ProviderCallError,
)

_BASE = "https://api.replicate.com/v1"

# public model key -> Replicate "owner/name" official-model path
WAN_MODELS = {
    "wan22-t2v": "wan-video/wan-2.2-t2v-fast",
    "wan22-i2v": "wan-video/wan-2.2-i2v-fast",
}
_PRICE_MICROS_PER_SECOND = {"wan22-t2v": 60_000, "wan22-i2v": 60_000}

# Wan 2.2 hosted models render at 16 fps and only accept num_frames in the
# closed range [81, 121] (see the Replicate model input schema; 81 frames ≈ 5s
# and gives the best results). Requesting fewer/more is rejected upstream with
# "num_frames: Must be greater than or equal to 81".
_WAN_FPS = 16
_WAN_MIN_FRAMES = 81
_WAN_MAX_FRAMES = 121


def _wan_num_frames(seconds: int) -> int:
    """Map a requested duration (seconds) to a valid Wan ``num_frames`` count.

    Frames are computed at the model's native 16 fps, then clamped into the
    upstream-accepted [81, 121] window so a short request (e.g. 5s → 80) never
    trips the provider's minimum-frame validation.
    """
    frames = int(max(1, seconds)) * _WAN_FPS
    return min(_WAN_MAX_FRAMES, max(_WAN_MIN_FRAMES, frames))


_ACTIVE = {"starting", "processing"}

# Only the official ``wan-video/*`` models accept the Wan-specific input schema
# (``num_frames`` in [81,121], ``aspect_ratio``, ``lora_weights``). Other
# Replicate video models routed through this adapter (e.g. ``lightricks/ltx-video``,
# ``tencent/hunyuan-video``) have entirely different input schemas — they use
# ``length`` / ``video_length`` and their own resolution controls, and Replicate
# ignores unknown input keys — so sending Wan params to them is wrong. For those
# we send only the portable ``prompt`` (+ ``image`` for i2v) and let the model's
# native defaults drive duration/resolution.
_WAN_OWNER_PREFIX = "wan-video/"


def _is_wan_model(model_path: str) -> bool:
    return model_path.startswith(_WAN_OWNER_PREFIX)


# Per-model input schemas for the non-Wan Replicate video models the Very ___ Time
# template routes to (read from GET /v1/models/{owner}/{name} on 2026-10-05).
SEEDANCE_2 = "bytedance/seedance-2.0"
SEEDANCE_1_LITE = "bytedance/seedance-1-lite"
KLING_21 = "kwaivgi/kling-v2.1"
_SEEDANCE_RATIOS = {"16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "9:21"}
_SEEDANCE_2_RESOLUTIONS = {"480p", "720p", "1080p", "4k"}
_SEEDANCE_1_RESOLUTIONS = {"480p", "720p", "1080p"}
_SEEDANCE_2_MAX_REFS = 9
_SEEDANCE_1_MAX_REFS = 4
_KLING_DURATIONS = (5, 10)


def _clamp_int(value: Any, low: int, high: int) -> int:
    return max(low, min(high, int(round(float(value or low)))))


def _seedance_input(model_path: str, *, prompt: str, seconds: int, aspect_ratio: str, image_url: str,
                    image_urls: Sequence[str], resolution: str, generate_audio: bool | None,
                    seed: int | None) -> dict:
    """Seedance 2.0 / 1-lite on Replicate.

    ``image`` (first frame) and ``reference_images`` cannot be combined: with
    references every image (first frame first) goes into ``reference_images``.
    """
    v2 = model_path == SEEDANCE_2
    refs = [u for u in image_urls if u]
    if refs and image_url and image_url not in refs:
        refs = [image_url, *refs]
    inp: dict = {"prompt": prompt}
    if refs:
        cap = _SEEDANCE_2_MAX_REFS if v2 else _SEEDANCE_1_MAX_REFS
        if len(refs) > cap:
            raise ProviderCallError(f"{model_path} takes at most {cap} reference images", kind="validation")
        inp["reference_images"] = refs
    elif image_url:
        inp["image"] = image_url
    inp["duration"] = _clamp_int(seconds, 4, 15 if v2 else 12)
    if aspect_ratio in _SEEDANCE_RATIOS:
        inp["aspect_ratio"] = aspect_ratio
    allowed = _SEEDANCE_2_RESOLUTIONS if v2 else _SEEDANCE_1_RESOLUTIONS
    inp["resolution"] = resolution if resolution in allowed else "720p"
    if v2:
        inp["generate_audio"] = True if generate_audio is None else bool(generate_audio)
    if seed is not None:
        inp["seed"] = int(seed)
    return inp


def _kling_input(*, prompt: str, seconds: int, image_url: str, image_urls: Sequence[str]) -> dict:
    """Kling v2.1 on Replicate: a start image is required; duration is 5 or 10."""
    start = image_url or next((u for u in image_urls if u), "")
    if not start:
        raise ProviderCallError("kling-v2.1 needs a start image", kind="validation")
    duration = min(_KLING_DURATIONS, key=lambda d: (abs(d - int(seconds or 5)), d))
    return {"prompt": prompt, "start_image": start, "duration": duration, "mode": "standard"}


def _build_input(
    *,
    model_path: str = "wan-video/wan-2.2-t2v-fast",
    prompt: str,
    seconds: int = 5,
    aspect_ratio: str = "9:16",
    image_url: str = "",
    lora_url: str = "",
    lora_scale: float = 0.0,
    image_urls: Sequence[str] = (),
    resolution: str = "",
    generate_audio: bool | None = None,
    seed: int | None = None,
) -> dict:
    """Build the Replicate ``input`` dict for a prediction (pure, testable).

    For official ``wan-video/*`` models this emits the full Wan schema. Wave-4
    identity approximation (§7): the PRIMARY face reference maps to
    ``input['image']`` (the i2v init-frame — hosted t2v has no IP-Adapter, so
    ``wan_camera`` is the true identity route). When the selected Wan model
    exposes LoRA inputs, the trained LoRA's presigned/public URL is passed as
    ``lora_weights`` with an optional ``lora_scale``.

    For any OTHER Replicate video model (ltx-video, hunyuan-video, …) the Wan
    schema does not apply, so only the portable ``prompt`` (and ``image`` when an
    init frame is supplied) are sent; the model's own defaults govern the rest.
    """
    if model_path in (SEEDANCE_2, SEEDANCE_1_LITE):
        return _seedance_input(model_path, prompt=prompt, seconds=seconds, aspect_ratio=aspect_ratio,
                               image_url=image_url, image_urls=image_urls, resolution=resolution,
                               generate_audio=generate_audio, seed=seed)
    if model_path == KLING_21:
        return _kling_input(prompt=prompt, seconds=seconds, image_url=image_url, image_urls=image_urls)
    if image_urls:
        raise ProviderCallError(f"{model_path} does not take reference images", kind="validation")
    if not _is_wan_model(model_path):
        inp: dict = {}
        if prompt:
            inp["prompt"] = prompt
        if image_url:
            inp["image"] = image_url
        return inp
    inp = {
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "num_frames": _wan_num_frames(seconds),
    }
    if image_url:
        inp["image"] = image_url
    if lora_url:
        inp["lora_weights"] = lora_url
        if lora_scale and lora_scale > 0:
            inp["lora_scale"] = float(lora_scale)
    return inp


@dataclass
class WanPrediction:
    prediction_id: str
    status: str = "starting"
    output_url: str = ""
    failure: str = ""
    get_url: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.status in ("succeeded", "failed", "canceled")


class WanAdapter:
    provider_key = "wan"

    def __init__(
        self,
        *,
        api_key: str = "",
        model: str = "wan22-t2v",
        session: Any = None,
        timeout_s: float = 60.0,
        max_retries: int = 4,
        sleep=time.sleep,
    ) -> None:
        self._api_key = api_key or os.getenv("REPLICATE_API_TOKEN", "")
        # Accept a WAN_MODELS alias or a direct Replicate ``owner/name`` path, so
        # the catalog can route any real Replicate video model.
        if model in WAN_MODELS:
            self._model_key = model
            self._model_path = WAN_MODELS[model]
        elif "/" in model:
            self._model_key = model
            self._model_path = model
        else:
            raise ProviderCallError(f"unknown Wan model {model!r}", kind="validation")
        self._session = session
        self._timeout = timeout_s
        self._max_retries = max_retries
        self._sleep = sleep
        # Resolved lazily for community models that need version-pinned submits.
        self._version = ""

    def _sess(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
        return self._session

    def _headers(self) -> dict:
        if not self._api_key:
            raise ProviderCallError("REPLICATE_API_TOKEN not configured", kind="auth")
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _call(self, method: str, url: str, *, json: dict | None = None) -> dict:
        import requests

        is_submit = method.upper() == "POST"
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self._sess().request(
                    method,
                    url,
                    headers=self._headers(),
                    json=json,
                    timeout=self._timeout,
                )
            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            ) as exc:
                if not is_submit and attempt <= self._max_retries:
                    self._sleep(min(20.0, 2 ** (attempt - 1)))
                    continue
                raise ProviderCallError(
                    f"replicate network error: {exc}",
                    kind="transient",
                    retryable=True,
                    acceptance=(
                        ACCEPTANCE_UNKNOWN if is_submit else ACCEPTANCE_DEFINITE_NO
                    ),
                ) from exc
            status = resp.status_code
            body = self._json(resp)
            if 200 <= status < 300:
                return body
            detail = (
                str(
                    (body.get("detail") or body.get("title"))
                    if isinstance(body, dict)
                    else ""
                )
                or f"HTTP {status}"
            )
            if status in (401, 403):
                raise ProviderCallError(
                    f"replicate auth failed: {detail}", kind="auth", status=status
                )
            if status in (400, 422):
                raise ProviderCallError(
                    f"replicate rejected request: {detail}",
                    kind="validation",
                    status=status,
                )
            if status == 429:
                if attempt <= self._max_retries:
                    self._sleep(min(30.0, 2**attempt))
                    continue
                raise ProviderCallError(
                    "replicate rate limit",
                    kind="rate_limit",
                    retryable=True,
                    status=429,
                )
            if status == 408 or status >= 500:
                if not is_submit and attempt <= self._max_retries:
                    self._sleep(min(20.0, 2 ** (attempt - 1)))
                    continue
                raise ProviderCallError(
                    f"replicate server error: {detail}",
                    kind="transient",
                    retryable=True,
                    status=status,
                    acceptance=(
                        ACCEPTANCE_UNKNOWN if is_submit else ACCEPTANCE_DEFINITE_NO
                    ),
                )
            raise ProviderCallError(
                f"replicate unexpected status {status}: {detail}",
                kind="provider",
                status=status,
            )

    @staticmethod
    def _json(resp) -> dict:
        try:
            body = resp.json()
        except Exception:
            return {}
        return body if isinstance(body, dict) else {"data": body}

    def submit(
        self,
        *,
        prompt: str,
        seconds: int = 5,
        aspect_ratio: str = "9:16",
        image_url: str = "",
        lora_url: str = "",
        lora_scale: float = 0.0,
        image_urls: Sequence[str] = (),
        resolution: str = "",
        generate_audio: bool | None = None,
        seed: int | None = None,
    ) -> WanPrediction:
        if not prompt and not image_url and not image_urls:
            raise ProviderCallError("a prompt or image is required", kind="validation")
        inp = _build_input(
            model_path=self._model_path,
            prompt=prompt,
            seconds=seconds,
            aspect_ratio=aspect_ratio,
            image_url=image_url,
            lora_url=lora_url,
            lora_scale=lora_scale,
            image_urls=tuple(image_urls or ()),
            resolution=resolution,
            generate_audio=generate_audio,
            seed=seed,
        )
        payload = self._submit_prediction(inp)
        pid = str(payload.get("id") or "")
        if not pid:
            raise ProviderCallError(
                f"replicate submit returned no id: {payload}",
                kind="provider",
                acceptance=ACCEPTANCE_UNKNOWN,
            )
        return WanPrediction(
            prediction_id=pid,
            status=str(payload.get("status") or "starting"),
            get_url=str((payload.get("urls") or {}).get("get") or ""),
        )

    def _submit_prediction(self, inp: dict) -> dict:
        """Create a Replicate prediction, transparently handling model kind.

        Official models (``wan-video/*``) are served by the official-model route
        ``POST /v1/models/{owner}/{name}/predictions``. Community models
        (``lightricks/ltx-video``, ``tencent/hunyuan-video``, …) are NOT exposed
        on that route — it returns 404 — so we resolve the model's latest version
        and submit via the version-pinned ``POST /v1/predictions`` instead. Both
        return the same ``{id,status,urls.get}`` shape the poller expects.
        """
        official_url = f"{_BASE}/models/{self._model_path}/predictions"
        try:
            return self._call("POST", official_url, json={"input": inp})
        except ProviderCallError as exc:
            if getattr(exc, "status", 0) != 404:
                raise
        version = self._resolve_version()
        return self._call(
            "POST", f"{_BASE}/predictions", json={"version": version, "input": inp}
        )

    def _resolve_version(self) -> str:
        if self._version:
            return self._version
        meta = self._call("GET", f"{_BASE}/models/{self._model_path}")
        version = str((meta.get("latest_version") or {}).get("id") or "")
        if not version:
            raise ProviderCallError(
                f"replicate model {self._model_path!r} has no resolvable version",
                kind="provider",
            )
        self._version = version
        return version

    def poll(self, pred: WanPrediction) -> WanPrediction:
        if pred.is_terminal:
            return pred
        url = pred.get_url or f"{_BASE}/predictions/{pred.prediction_id}"
        payload = self._call("GET", url)
        pred.raw = payload
        pred.status = str(payload.get("status") or pred.status)
        if pred.status == "succeeded":
            pred.output_url = self._extract_output(payload.get("output"))
            if not pred.output_url:
                raise ProviderCallError(
                    f"replicate succeeded but no output: {payload}", kind="provider"
                )
        elif pred.status in ("failed", "canceled"):
            pred.failure = str(payload.get("error") or f"replicate {pred.status}")
        return pred

    @staticmethod
    def _extract_output(output: Any) -> str:
        # Replicate returns either a single url string or a list of urls.
        if isinstance(output, str):
            return output
        if isinstance(output, list) and output:
            last = output[-1]
            return str(last) if isinstance(last, str) else ""
        return ""

    def cancel(self, pred: WanPrediction) -> bool:
        """Best-effort real cancellation via ``POST /predictions/{id}/cancel``.

        Replicate cancels a running/queued prediction with a POST to its
        ``/cancel`` sub-resource. Returns ``True`` when the provider
        acknowledges (2xx) or the prediction is already gone (404); ``False``
        for a terminal prediction or any transport/HTTP failure. Never raises.
        """
        if pred.is_terminal:
            return False
        try:
            resp = self._sess().request(
                "POST",
                f"{_BASE}/predictions/{pred.prediction_id}/cancel",
                headers=self._headers(),
                timeout=self._timeout,
            )
        except Exception:
            return False
        return 200 <= resp.status_code < 300 or resp.status_code == 404

    def cost_micros(self, seconds: int) -> int:
        rate = _PRICE_MICROS_PER_SECOND.get(self._model_key, 60_000)
        return int(max(1, int(seconds))) * rate
