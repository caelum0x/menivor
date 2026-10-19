"""Config-driven async media adapter (video / music providers).

One tested implementation serves several async generation providers (Runway,
Luma, Kling, Veo, Suno) that share the same shape: POST a job → get an id → GET a
status until terminal → read an output URL + a duration for usage metering. Each
provider is a small :class:`AsyncMediaConfig` (paths, field names, state map,
body/URL builders); the differences live in data, not code.

Implements the ``ProviderAdapter`` contract (submit/poll/cancel/quote/catalog).
The HTTP ``request_fn`` is the injectable network seam — tests pass a fake and
assert the real request/response handling; adapter logic is never stubbed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable

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

# Provider status vocabularies → normalized run states.
_DEFAULT_STATE_MAP = {
    "queued": RUN_QUEUED, "pending": RUN_QUEUED, "starting": RUN_QUEUED, "created": RUN_QUEUED,
    "dispatched": RUN_QUEUED, "submitted": RUN_QUEUED,
    "running": RUN_RUNNING, "processing": RUN_RUNNING, "in_progress": RUN_RUNNING,
    "generating": RUN_RUNNING,
    "succeeded": RUN_COMPLETED, "success": RUN_COMPLETED, "completed": RUN_COMPLETED,
    "complete": RUN_COMPLETED, "finished": RUN_COMPLETED,
    "failed": RUN_FAILED, "error": RUN_FAILED, "canceled": RUN_FAILED, "cancelled": RUN_FAILED,
}


@dataclass(frozen=True)
class AsyncMediaConfig:
    """Static description of one async media provider's API shape."""

    provider_key: str
    base_url: str
    capability: str = "video"           # video | music
    submit_path: str = "/generate"
    poll_path_tmpl: str = "/status/{id}"  # {id} substituted with the run id
    id_field: str = "id"                # where the job id lives in the submit response
    state_field: str = "status"         # where the status lives in the poll response
    output_field: str = "output"        # where the result URL lives
    seconds_field: str = "duration"     # where the produced seconds live (usage)
    unit: str = "seconds"
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer "
    # Explicit env var holding this provider's API key. Empty -> the default
    # ``<PROVIDER_KEY>_API_KEY`` name. Lets providers that share a vendor
    # credential (e.g. all fal.ai models -> ``FAL_API_KEY``) declare it once.
    auth_env: str = ""
    state_map: dict = field(default_factory=lambda: dict(_DEFAULT_STATE_MAP))
    submit_body_fn: Callable[[dict, dict], dict] | None = None
    # Reference-only providers carry a license/territorial caveat (e.g.
    # HunyuanVideo's non-commercial terms + EU/UK/KR geo exclusion) and MUST NOT
    # become a live global route by default. Their config/catalog rows exist so
    # the protocol is documented and testable, but registry auto-discovery skips
    # them unless an explicit ``REELFORGE_ENABLE_<KEY>_REFERENCE`` flag is set.
    reference_only: bool = False


class AsyncMediaAdapter:
    """Async video/music provider adapter parameterized by :class:`AsyncMediaConfig`."""

    def __init__(self, config: AsyncMediaConfig, *, api_key: str = "", request_fn: Any = None) -> None:
        self._cfg = config
        self._api_key = api_key or os.getenv(_env_var_for_config(config), "")
        headers = {config.auth_header: f"{config.auth_scheme}{self._api_key}".strip()}
        self._request = request_fn or build_json_transport(
            provider_key=config.provider_key, base_url=config.base_url, headers=headers
        )

    @property
    def provider_key(self) -> str:
        return self._cfg.provider_key

    def catalog(self) -> list[ModelListing]:
        return []  # operator-curated in the reviewed catalog

    def quote(self, request: Any, price_version: Any) -> QuoteResult:
        est = None
        if isinstance(request, dict):
            est = request.get("estimated_seconds") or request.get("estimated_quantity")
        return quote_from_price(price_version, est if est is not None else 5)

    # -- submit ------------------------------------------------------------- #
    def submit(self, request: Any, snapshot: dict, correlation_id: str) -> ProviderRun:
        req = request if isinstance(request, dict) else {}
        if self._cfg.submit_body_fn is not None:
            body = self._cfg.submit_body_fn(req, snapshot)
        else:
            body = {"model": str(snapshot.get("model_id", "")).split("/", 1)[-1], **req}
        payload = self._request("POST", self._cfg.submit_path, json=body)
        run_id = _dig(payload, self._cfg.id_field)
        if not run_id:
            raise ProviderError(
                f"{self.provider_key} submit returned no {self._cfg.id_field!r}: {payload}",
                provider_key=self.provider_key,
                retryable=False,
            )
        state = self._map_state(_dig(payload, self._cfg.state_field) or "queued")
        return ProviderRun(
            provider_key=self.provider_key, run_id=str(run_id), state=state, raw=payload
        )

    # -- poll --------------------------------------------------------------- #
    def poll(self, run: ProviderRun) -> ProviderRun:
        if run.is_terminal:
            return run
        path = self._cfg.poll_path_tmpl.format(id=run.run_id)
        payload = self._request("GET", path)
        state = self._map_state(_dig(payload, self._cfg.state_field) or "running")
        result_ref = ""
        usage = None
        if state == RUN_COMPLETED:
            result_ref = _first_url(_dig(payload, self._cfg.output_field))
            usage = self._usage(payload)
        return ProviderRun(
            provider_key=self.provider_key,
            run_id=run.run_id,
            state=state,
            progress=100 if state == RUN_COMPLETED else run.progress,
            result_ref=result_ref,
            usage=usage,
            raw=payload,
        )

    def cancel(self, run: ProviderRun) -> bool:
        return False  # most async media APIs bill on submit; cancel is a no-op

    # -- helpers ------------------------------------------------------------ #
    def _map_state(self, raw: Any) -> str:
        return self._cfg.state_map.get(str(raw or "").strip().lower(), RUN_RUNNING)

    def _usage(self, payload: dict) -> NormalizedUsage | None:
        seconds = _dig(payload, self._cfg.seconds_field)
        if seconds is None:
            return None
        try:
            qty = int(round(float(seconds)))
        except (TypeError, ValueError):
            return None
        return NormalizedUsage(unit=self._cfg.unit, quantity_units=qty, cost_micros=0, raw={})


def _dig(payload: Any, dotted: str) -> Any:
    """Read a (possibly dotted) field path from a nested dict."""
    if not isinstance(payload, dict) or not dotted:
        return None
    node: Any = payload
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node


def _first_url(value: Any) -> str:
    """Extract a single result URL from string / list / dict output shapes."""
    if not value:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        for item in value:
            url = _first_url(item)
            if url:
                return url
        return ""
    if isinstance(value, dict):
        for key in ("url", "video_url", "audio_url", "output_url", "download_url"):
            if value.get(key):
                return str(value[key])
    return ""


# --------------------------------------------------------------------------- #
# Seeded provider configs (real API shapes; keys resolved from env at build)
# --------------------------------------------------------------------------- #
def _kling_body(req: dict, snapshot: dict) -> dict:
    return {
        "model_name": str(snapshot.get("model_id", "kling-v2")).split("/", 1)[-1],
        "prompt": req.get("prompt", ""),
        "duration": str(req.get("seconds", 5)),
        "aspect_ratio": req.get("aspect_ratio", "9:16"),
        **({"image": req["image_url"]} if req.get("image_url") else {}),
    }


def _higgsfield_body(req: dict, snapshot: dict) -> dict:
    """Higgsfield generation body: prompt + camera/motion preset + optional i2v frame.

    ``seconds`` maps to the API's ``duration``; ``motion`` (or its ``camera`` alias)
    carries the camera/motion preset; the ``image_url`` init frame is emitted only
    for image-to-video so a text-to-video request stays a pure t2v call.
    """
    body: dict = {
        "model": str(snapshot.get("model_id", "")).split("/", 1)[-1],
        "prompt": req.get("prompt", ""),
        "duration": req.get("seconds", req.get("duration", 5)),
    }
    motion = req.get("motion") or req.get("camera")
    if motion:
        body["motion"] = motion
    if req.get("image_url"):
        body["image_url"] = req["image_url"]
    return body


# fal.ai queue vocabulary is UPPERCASE (IN_QUEUE / IN_PROGRESS / COMPLETED);
# ``_map_state`` lowercases before lookup, so only the non-default term is added.
_FAL_STATE_MAP = {**_DEFAULT_STATE_MAP, "in_queue": RUN_QUEUED}


PROVIDER_CONFIGS: dict[str, AsyncMediaConfig] = {
    "kling": AsyncMediaConfig(
        provider_key="kling", base_url="https://api.klingai.com", capability="video",
        submit_path="/v1/videos/text2video", poll_path_tmpl="/v1/videos/{id}",
        id_field="data.task_id", state_field="data.task_status",
        output_field="data.works", seconds_field="data.duration",
        submit_body_fn=_kling_body,
    ),
    "runway": AsyncMediaConfig(
        provider_key="runway", base_url="https://api.dev.runwayml.com", capability="video",
        submit_path="/v1/image_to_video", poll_path_tmpl="/v1/tasks/{id}",
        id_field="id", state_field="status", output_field="output", seconds_field="duration",
    ),
    "luma": AsyncMediaConfig(
        provider_key="luma", base_url="https://api.lumalabs.ai", capability="video",
        submit_path="/dream-machine/v1/generations", poll_path_tmpl="/dream-machine/v1/generations/{id}",
        id_field="id", state_field="state", output_field="assets.video", seconds_field="duration",
    ),
    "veo": AsyncMediaConfig(
        provider_key="veo", base_url="https://generativelanguage.googleapis.com", capability="video",
        submit_path="/v1beta/models/veo:predictLongRunning", poll_path_tmpl="/v1beta/operations/{id}",
        id_field="name", state_field="done", output_field="response.generateVideoResponse.video",
        seconds_field="response.duration",
        state_map={**_DEFAULT_STATE_MAP, "true": RUN_COMPLETED, "false": RUN_RUNNING},
    ),
    "suno": AsyncMediaConfig(
        provider_key="suno", base_url="https://api.suno.ai", capability="music",
        submit_path="/v1/generate", poll_path_tmpl="/v1/feed/{id}",
        id_field="id", state_field="status", output_field="audio_url", seconds_field="duration",
    ),
    # Higgsfield DoP — camera/motion-preset short-form video (managed API).
    "higgsfield": AsyncMediaConfig(
        provider_key="higgsfield", base_url="https://platform.higgsfield.ai", capability="video",
        submit_path="/v1/generations", poll_path_tmpl="/v1/generations/{id}",
        id_field="id", state_field="status", output_field="results", seconds_field="duration",
        submit_body_fn=_higgsfield_body,
    ),
    # LTX-Video via fal.ai — open-weights (Apache-2.0) fast video on the fal queue.
    # Shares the vendor credential with every other fal model (``FAL_API_KEY``) and
    # authenticates with fal's ``Authorization: Key <token>`` scheme.
    "ltx_fal": AsyncMediaConfig(
        provider_key="ltx_fal", base_url="https://queue.fal.run", capability="video",
        submit_path="/fal-ai/ltx-video", poll_path_tmpl="/fal-ai/ltx-video/requests/{id}",
        id_field="request_id", state_field="status", output_field="video", seconds_field="duration",
        auth_scheme="Key ", auth_env="FAL_API_KEY", state_map=dict(_FAL_STATE_MAP),
    ),
    # CogVideoX — open-weights (Apache-2.0) video; managed hosted endpoint.
    "cogvideox": AsyncMediaConfig(
        provider_key="cogvideox", base_url="https://api.cogvideox.ai", capability="video",
        submit_path="/v1/video/generations", poll_path_tmpl="/v1/video/generations/{id}",
        id_field="id", state_field="status", output_field="video_url", seconds_field="duration",
    ),
    # ---- Additional open-weights video fallbacks (all on the fal.ai queue) ---- #
    # Each shares the vendor credential (``FAL_API_KEY``) and fal's UPPERCASE
    # queue vocabulary + ``Authorization: Key <token>`` scheme, exactly like
    # ``ltx_fal``. They extend the license-clean fallback chain after CogVideoX.
    #
    # Stable Video Diffusion (SVD) — Stability's open image-to-video model on fal.
    # Stability AI Community License: commercial OK under the revenue cap.
    "svd": AsyncMediaConfig(
        provider_key="svd", base_url="https://queue.fal.run", capability="video",
        submit_path="/fal-ai/stable-video-diffusion",
        poll_path_tmpl="/fal-ai/stable-video-diffusion/requests/{id}",
        id_field="request_id", state_field="status", output_field="video", seconds_field="duration",
        auth_scheme="Key ", auth_env="FAL_API_KEY", state_map=dict(_FAL_STATE_MAP),
    ),
    # AnimateDiff — Apache-2.0 motion module over SD1.5, text-to-video on fal.
    "animatediff": AsyncMediaConfig(
        provider_key="animatediff", base_url="https://queue.fal.run", capability="video",
        submit_path="/fal-ai/fast-animatediff/text-to-video",
        poll_path_tmpl="/fal-ai/fast-animatediff/text-to-video/requests/{id}",
        id_field="request_id", state_field="status", output_field="video", seconds_field="duration",
        auth_scheme="Key ", auth_env="FAL_API_KEY", state_map=dict(_FAL_STATE_MAP),
    ),
    # Mochi-1 — Genmo's Apache-2.0 open-weights text-to-video on fal.
    "mochi": AsyncMediaConfig(
        provider_key="mochi", base_url="https://queue.fal.run", capability="video",
        submit_path="/fal-ai/mochi-v1",
        poll_path_tmpl="/fal-ai/mochi-v1/requests/{id}",
        id_field="request_id", state_field="status", output_field="video", seconds_field="duration",
        auth_scheme="Key ", auth_env="FAL_API_KEY", state_map=dict(_FAL_STATE_MAP),
    ),
    # HunyuanVideo — Tencent open weights, but NON-COMMERCIAL terms with a
    # territorial (EU/UK/KR) exclusion. REFERENCE-ONLY: never a default live
    # global route (registry skips it unless REELFORGE_ENABLE_HUNYUANVIDEO_REFERENCE
    # is set) and license-gated out for paying users.
    "hunyuanvideo": AsyncMediaConfig(
        provider_key="hunyuanvideo", base_url="https://queue.fal.run", capability="video",
        submit_path="/fal-ai/hunyuan-video",
        poll_path_tmpl="/fal-ai/hunyuan-video/requests/{id}",
        id_field="request_id", state_field="status", output_field="video", seconds_field="duration",
        auth_scheme="Key ", auth_env="FAL_API_KEY", state_map=dict(_FAL_STATE_MAP),
        reference_only=True,
    ),
}


def _env_var_for_config(config: AsyncMediaConfig) -> str:
    """Env var name holding ``config``'s API key (explicit ``auth_env`` or default)."""
    if config.auth_env:
        return config.auth_env
    return f"{config.provider_key.upper().replace('-', '_')}_API_KEY"


def env_var_for(provider_key: str) -> str:
    """Env var name holding ``provider_key``'s API key.

    Honours a config's explicit shared ``auth_env`` (e.g. ``ltx_fal -> FAL_API_KEY``)
    and otherwise derives the default ``<PROVIDER_KEY>_API_KEY``. Unknown providers
    still get the derived default so registry discovery has a name to probe.
    """
    key = str(provider_key or "").strip().lower()
    cfg = PROVIDER_CONFIGS.get(key)
    if cfg is not None:
        return _env_var_for_config(cfg)
    return f"{key.upper().replace('-', '_')}_API_KEY"


def build_async_media_adapter(provider_key: str, *, api_key: str = "", request_fn: Any = None) -> AsyncMediaAdapter:
    """Build a seeded async-media adapter by provider key."""
    cfg = PROVIDER_CONFIGS.get(str(provider_key or "").strip().lower())
    if cfg is None:
        raise ProviderError(
            f"no async-media config for {provider_key!r}", provider_key=str(provider_key), retryable=False
        )
    return AsyncMediaAdapter(cfg, api_key=api_key, request_fn=request_fn)
