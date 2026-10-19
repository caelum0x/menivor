"""Paid engine clients besides Kling, all with the KlingClient interface the render worker drives:

  image_to_video(image, prompt, seconds, aspect_ratio, audio_b64=None, image_url=None) -> task id
  status(kind, task id) -> ("running", None) | ("done", {"id", "url"})   (raises EngineError on a failed task)
  lip_sync(...) -> task id                      only when ``lipsync == "separate"``
  spent_usd / cap_usd / ledger                  every submit is checked against the cap first, billed once accepted
  dry_run_requests(plan)                        what a paid run would send (no network)

``lipsync``: "native" = the engine animates the face from our audio in one task (Seedance reference audio,
InfiniteTalk); "separate" = a second lip-sync task; "none" = motion only, lips are not driven by our audio.
``needs_url``: the engine wants a public image URL (the worker uploads the frame and presigns it).

Transient failures (429, 5xx, network) raise ``EngineError(transient=True)`` and are retried by the worker
with backoff; balance / auth / cap failures raise ``EngineError(stop=True)`` and stop the render.
Endpoints and fields were checked against each provider's public docs on 2026-10-06 (sources inline);
none of them has been called live from this code yet.
"""

from __future__ import annotations

import base64
import math
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from . import engines as E
from .kling import KlingClient, KlingError, default_http

EngineError = KlingError  # one error type for every engine (stop / transient flags)

Http = Callable[[str, str, Mapping[str, str], Any], tuple[int, dict]]


@dataclass
class _Base:
    cap_usd: float = 0.0
    spent_usd: float = 0.0
    http: Http = default_http
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.time
    ledger: list[dict] = field(default_factory=list)

    name = "base"
    lipsync = "none"
    needs_url = False
    base_url = ""

    def _headers(self) -> dict[str, str]:
        raise NotImplementedError

    def _call(self, method: str, path: str, body: Any = None, *, url: str | None = None) -> dict:
        try:
            status, data = self.http(method, url or (self.base_url + path), self._headers(), body)
        except Exception as exc:  # noqa: BLE001 - network boundary
            raise EngineError(f"{self.name} unreachable: {type(exc).__name__}", transient=True) from exc
        data = data if isinstance(data, dict) else {}
        if status == 429 or status >= 500:
            raise EngineError(f"{self.name} busy ({status})", transient=True)
        if status == 402:
            raise EngineError(f"{self.name}: account credit exhausted", stop=True)
        if status in (401, 403):
            raise EngineError(f"{self.name} refused the key ({status})", stop=True)
        if status >= 400:
            raise EngineError(f"{self.name} error {status}: {str(data)[:200]}")
        return data

    def _check_cap(self, item: str, usd: float) -> None:
        if self.cap_usd and self.spent_usd + usd > self.cap_usd + 1e-9:
            raise EngineError(f"spend cap ${self.cap_usd:.2f} reached before {item} (${usd:.2f})", stop=True)

    def _charge(self, item: str, usd: float) -> None:
        self.spent_usd = round(self.spent_usd + usd, 4)
        self.ledger.append({"item": item, "usd": usd})

    def shot_usd(self, seconds: float) -> float:
        raise NotImplementedError

    def lip_sync(self, **_: Any) -> str:
        raise EngineError(f"{self.name} has no separate lip-sync task", stop=True)

    def dry_run_requests(self, plan: Mapping[str, Any]) -> list[dict]:
        return [{"shot": s["id"], "engine": self.name, "seconds": int(s["dur"]), "lipsync": self.lipsync,
                 "first_frame": (s.get("refs") or [None])[0], "usd": round(self.shot_usd(float(s["dur"])), 4)}
                for s in plan.get("shots") or []]


# --------------------------------------------------------------------------- Replicate: Seedance 2.5
@dataclass
class ReplicateSeedance(_Base):
    """Seedance on Replicate (replicate.com/bytedance/seedance-2.5): the first frame and our shot audio go in
    as reference image / reference audio, so the lips follow our voice in the same task (as EP03b did)."""

    token: str = ""
    model: str = "bytedance/seedance-2.5"
    resolution: str = "480p"
    name = "replicate"
    lipsync = "native"
    base_url = "https://api.replicate.com"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json", "Prefer": "respond-async"}

    def shot_usd(self, seconds: float) -> float:
        rate = E.REPLICATE["m25_480p"] if self.resolution == "480p" else 0.2312
        return round(int(math.ceil(seconds)) * rate, 4)

    def image_to_video(self, *, image: str, prompt: str, seconds: float, aspect_ratio: str = "9:16",
                       audio_b64: str | None = None, image_url: str | None = None) -> str:
        dur = int(min(max(math.ceil(seconds), 4), 15))
        usd = self.shot_usd(dur)
        self._check_cap(f"seedance {dur}s", usd)
        inputs: dict[str, Any] = {"prompt": prompt[:2500], "duration": dur, "resolution": self.resolution,
                                  "aspect_ratio": aspect_ratio, "generate_audio": True,
                                  "reference_images": [f"data:image/png;base64,{image}"]}
        if audio_b64:
            inputs["reference_audios"] = [f"data:audio/wav;base64,{audio_b64}"]
        data = self._call("POST", f"/v1/models/{self.model}/predictions", {"input": inputs})
        if not data.get("id"):
            raise EngineError("replicate returned no prediction id")
        self._charge(f"seedance {dur}s", usd)
        return str(data["id"])

    def status(self, kind: str, task_id: str) -> tuple[str, dict | None]:
        data = self._call("GET", f"/v1/predictions/{task_id}")
        state = data.get("status")
        if state == "succeeded":
            out = data.get("output")
            url = out[0] if isinstance(out, list) and out else out
            if not url:
                raise EngineError(f"replicate {task_id} finished without a video")
            return "done", {"id": task_id, "url": str(url)}
        if state in ("failed", "canceled"):
            raise EngineError(f"replicate {task_id} {state}: {str(data.get('error'))[:200]}")
        return "running", None


# --------------------------------------------------------------------------- Higgsfield: Kling via Higgsfield
@dataclass
class HiggsfieldKling(_Base):
    """Higgsfield Cloud API (docs.higgsfield.ai): POST https://api.higgsfield.ai/<endpoint> with
    ``Authorization: Key <id>:<secret>`` -> {request_id}; GET /requests/<id>/status -> completed + video.url.
    Needs a public image URL. Lip-sync runs as a separate request only when HIGGSFIELD_LIPSYNC_ENDPOINT is set
    (its path is not published in the docs we could read); otherwise the shot is motion only."""

    key_id: str = ""
    key_secret: str = ""
    endpoint: str = "kling-video/v2.6/pro/image-to-video"
    lipsync_endpoint: str = ""
    name = "higgsfield_kling"
    needs_url = True
    base_url = "https://api.higgsfield.ai"

    def __post_init__(self) -> None:
        self.lipsync = "separate" if self.lipsync_endpoint else "none"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Key {self.key_id}:{self.key_secret}", "Content-Type": "application/json"}

    def shot_usd(self, seconds: float) -> float:
        clip = 5 if seconds <= 5 else 10
        return round(clip * (E.HIGGSFIELD_KLING_PER_S + (E.HIGGSFIELD_LIPSYNC_PER_S if self.lipsync_endpoint else 0)), 4)

    def _request(self, path: str, body: dict, item: str, usd: float) -> str:
        self._check_cap(item, usd)
        data = self._call("POST", f"/{path.strip('/')}", body)
        rid = data.get("request_id")
        if not rid:
            raise EngineError("higgsfield returned no request id")
        self._charge(item, usd)
        return str(rid)

    def image_to_video(self, *, image: str, prompt: str, seconds: float, aspect_ratio: str = "9:16",
                       audio_b64: str | None = None, image_url: str | None = None) -> str:
        if not image_url:
            raise EngineError("higgsfield needs a public image URL", stop=True)
        clip = 5 if seconds <= 5 else 10
        return self._request(self.endpoint, {"prompt": prompt[:2500], "image_url": image_url, "duration": clip,
                                             "aspect_ratio": aspect_ratio},
                             f"higgsfield i2v {clip}s", round(clip * E.HIGGSFIELD_KLING_PER_S, 4))

    def lip_sync(self, *, seconds: int, video_url: str | None = None, audio_url: str | None = None,
                 **_: Any) -> str:
        if not (self.lipsync_endpoint and video_url and audio_url):
            raise EngineError("higgsfield lip-sync needs the endpoint, the video URL and a public audio URL", stop=True)
        return self._request(self.lipsync_endpoint, {"video_url": video_url, "audio_url": audio_url},
                             f"higgsfield lip-sync {seconds}s", round(seconds * E.HIGGSFIELD_LIPSYNC_PER_S, 4))

    def status(self, kind: str, task_id: str) -> tuple[str, dict | None]:
        data = self._call("GET", f"/requests/{task_id}/status")
        state = data.get("status")
        if state == "completed":
            url = (data.get("video") or {}).get("url")
            if not url:
                raise EngineError(f"higgsfield {task_id} completed without a video")
            return "done", {"id": task_id, "url": url}
        if state in ("failed", "nsfw", "canceled", "cancelled"):
            raise EngineError(f"higgsfield {task_id} {state}")
        return "running", None


# --------------------------------------------------------------------------- MiniMax Hailuo
@dataclass
class MinimaxHailuo(_Base):
    """MiniMax video API (platform.minimax.io): POST /v1/video_generation {model, prompt, first_frame_image,
    duration 6|10, resolution} -> task_id; GET /v1/query/video_generation?task_id= -> Success + file_id;
    GET /v1/files/retrieve?file_id= -> file.download_url. Motion only: lips are not driven by our audio."""

    api_key: str = ""
    model: str = "MiniMax-Hailuo-02"
    resolution: str = "768P"
    name = "minimax_hailuo"
    base_url = "https://api.minimax.io"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def shot_usd(self, seconds: float) -> float:
        return round((6 if seconds <= 6 else 10) * E.HAILUO_PER_S, 4)

    def _ok(self, data: dict) -> dict:
        code = (data.get("base_resp") or {}).get("status_code", 0)
        if code in (1008,):  # insufficient balance
            raise EngineError("minimax balance exhausted", stop=True)
        if code in (1002, 1039):  # rate limits
            raise EngineError("minimax rate limited", transient=True)
        if code:
            raise EngineError(f"minimax error {code}: {(data.get('base_resp') or {}).get('status_msg', '')}")
        return data

    def image_to_video(self, *, image: str, prompt: str, seconds: float, aspect_ratio: str = "9:16",
                       audio_b64: str | None = None, image_url: str | None = None) -> str:
        dur = 6 if seconds <= 6 else 10
        usd = self.shot_usd(dur)
        self._check_cap(f"hailuo {dur}s", usd)
        data = self._ok(self._call("POST", "/v1/video_generation", {
            "model": self.model, "prompt": prompt[:2000], "first_frame_image": f"data:image/png;base64,{image}",
            "duration": dur, "resolution": self.resolution}))
        if not data.get("task_id"):
            raise EngineError("minimax returned no task id")
        self._charge(f"hailuo {dur}s", usd)
        return str(data["task_id"])

    def status(self, kind: str, task_id: str) -> tuple[str, dict | None]:
        data = self._ok(self._call("GET", f"/v1/query/video_generation?task_id={task_id}"))
        state = data.get("status")
        if state == "Success":
            got = self._ok(self._call("GET", f"/v1/files/retrieve?file_id={data.get('file_id')}"))
            url = (got.get("file") or {}).get("download_url")
            if not url:
                raise EngineError(f"minimax {task_id} has no download URL")
            return "done", {"id": task_id, "url": url}
        if state == "Fail":
            raise EngineError(f"minimax {task_id} failed")
        return "running", None


# --------------------------------------------------------------------------- RunPod: Wan 2.2 + InfiniteTalk
@dataclass
class RunpodWan(_Base):
    """Our own RunPod serverless worker (infra/render-workers: wan22-i2v + infinitetalk). Contract:
    POST https://api.runpod.ai/v2/<endpoint>/run {input: {task: "infinitetalk", image_base64, audio_base64,
    prompt, seconds, aspect_ratio}} -> {id}; GET /v2/<endpoint>/status/<id> -> COMPLETED + output.video_url
    and executionTime (ms). Billed by GPU time: the cap is checked against the estimate before submit and
    the measured GPU seconds are booked when the job completes."""

    api_key: str = ""
    endpoint_id: str = ""
    gpu_usd_per_h: float = E.RUNPOD_H100_PER_H
    name = "runpod_wan"
    lipsync = "native"
    base_url = "https://api.runpod.ai"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def shot_usd(self, seconds: float) -> float:
        return round(seconds * E.RUNPOD_GPU_MIN_PER_OUTPUT_S / 60 * self.gpu_usd_per_h, 4)

    def image_to_video(self, *, image: str, prompt: str, seconds: float, aspect_ratio: str = "9:16",
                       audio_b64: str | None = None, image_url: str | None = None) -> str:
        if not audio_b64:
            raise EngineError("infinitetalk needs the shot audio", stop=True)
        est = self.shot_usd(seconds)
        self._check_cap(f"wan+infinitetalk {seconds:.0f}s", est)
        data = self._call("POST", f"/v2/{self.endpoint_id}/run", {"input": {
            "task": "infinitetalk", "image_base64": image, "audio_base64": audio_b64, "prompt": prompt[:2000],
            "seconds": float(seconds), "aspect_ratio": aspect_ratio}})
        if not data.get("id"):
            raise EngineError("runpod returned no job id")
        return str(data["id"])

    def status(self, kind: str, task_id: str) -> tuple[str, dict | None]:
        data = self._call("GET", f"/v2/{self.endpoint_id}/status/{task_id}")
        state = data.get("status")
        if state == "COMPLETED":
            url = (data.get("output") or {}).get("video_url")
            if not url:
                raise EngineError(f"runpod {task_id} completed without output.video_url")
            gpu_s = float(data.get("executionTime") or 0) / 1000.0
            self._charge(f"runpod {task_id} {gpu_s:.0f} GPU-s", round(gpu_s / 3600 * self.gpu_usd_per_h, 4))
            return "done", {"id": task_id, "url": url}
        if state in ("FAILED", "CANCELLED", "TIMED_OUT"):
            raise EngineError(f"runpod {task_id} {state.lower()}: {str(data.get('error'))[:200]}")
        return "running", None


def client_for(engine: str, *, cap_usd: float, spent_usd: float, env: Mapping[str, str] | None = None,
               **kw: Any) -> Any:
    """The paid client for an approved engine, from env keys (EngineError(stop) when keys are missing)."""
    env = os.environ if env is None else env
    common = {"cap_usd": cap_usd, "spent_usd": spent_usd, **kw}
    if engine == "kling":
        return KlingClient.from_env(env, **common)
    if not E.configured(engine, env):
        raise EngineError(f"{engine}: keys are not set on this worker", stop=True)
    if engine == "replicate":
        return ReplicateSeedance(token=env["REPLICATE_API_TOKEN"], **common)
    if engine == "higgsfield_kling":
        return HiggsfieldKling(key_id=env["HIGGSFIELD_API_KEY"], key_secret=env["HIGGSFIELD_API_SECRET"],
                               endpoint=env.get("HIGGSFIELD_I2V_ENDPOINT") or HiggsfieldKling.endpoint,
                               lipsync_endpoint=env.get("HIGGSFIELD_LIPSYNC_ENDPOINT") or "", **common)
    if engine == "minimax_hailuo":
        return MinimaxHailuo(api_key=env["MINIMAX_API_KEY"], **common)
    if engine == "runpod_wan":
        return RunpodWan(api_key=env["RUNPOD_API_KEY"], endpoint_id=env["RUNPOD_WAN_ENDPOINT_ID"], **common)
    raise EngineError(f"unknown engine {engine}", stop=True)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()
