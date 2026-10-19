"""Lip-sync engines for translation: Kling lip-sync (official API, by video URL) or InfiniteTalk
on our RunPod serverless worker. Both are seams with an HTTP layer tests replace; both respect a cap."""

from __future__ import annotations

import base64
import json
import math
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.domains.adclone import engines as E
from app.domains.adclone.kling import KlingClient, lipsync_cost

ENGINES = ("kling", "infinitetalk")
TTS_USD_PER_1K_CHARS_ENV = "ELEVENLABS_USD_PER_1K_CHARS"
DEFAULT_TTS_USD_PER_1K = 0.30  # ESTIMATE: ElevenLabs Creator overage list price; confirm in the console
CHARS_PER_SECOND = 15


class LipsyncError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def tts_usd(chars: int, env: Mapping[str, str] | None = None) -> float:
    e = os.environ if env is None else env
    try:
        rate = float(e.get(TTS_USD_PER_1K_CHARS_ENV) or DEFAULT_TTS_USD_PER_1K)
    except ValueError:
        rate = DEFAULT_TTS_USD_PER_1K
    return round(max(0, chars) / 1000 * rate, 4)


def lipsync_usd(engine: str, seconds: float) -> float:
    if engine == "infinitetalk":
        return round(seconds * E.RUNPOD_GPU_MIN_PER_OUTPUT_S / 60 * E.RUNPOD_H100_PER_H, 4)
    return lipsync_cost(int(math.ceil(seconds)))


def configured(engine: str, env: Mapping[str, str] | None = None) -> bool:
    e = os.environ if env is None else env
    if engine == "infinitetalk":
        return bool(e.get("RUNPOD_API_KEY") and e.get("RUNPOD_INFINITETALK_ENDPOINT"))
    return bool(e.get("KLING_API_KEY") or (e.get("KLING_ACCESS_KEY") and e.get("KLING_SECRET_KEY")))


def _http(method: str, url: str, headers: Mapping[str, str], body: Any) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers=dict(headers))
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - fixed https base URL
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {}


@dataclass
class InfiniteTalkDubber:
    """RunPod InfiniteTalk adapter (worker: ``infra/render-workers/infinitetalk/handler.py``).

    ``POST /v2/<endpoint>/run {input: {task: "infinitetalk_dub", video_url, audio_base64, seconds}}``,
    then ``GET /v2/<endpoint>/status/<id>`` until ``COMPLETED`` with ``output.video_url`` (an
    ``output.error`` from the worker is a failure). GPU time (``executionTime``) is booked."""

    api_key: str
    endpoint_id: str
    cap_usd: float
    http: Callable[[str, str, Mapping[str, str], Any], tuple[int, dict]] = _http
    sleep: Callable[[float], None] = time.sleep
    poll_s: float = 10.0
    timeout_s: float = 1800.0
    spent_usd: float = 0.0
    base_url: str = "https://api.runpod.ai"
    ledger: list[dict] = field(default_factory=list)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def dub(self, *, video_url: str, audio: bytes, seconds: float) -> str:
        est = lipsync_usd("infinitetalk", seconds)
        if self.cap_usd and self.spent_usd + est > self.cap_usd + 1e-9:
            raise LipsyncError(f"spend cap ${self.cap_usd:.2f} reached before lip-sync")
        status, data = self.http("POST", f"{self.base_url}/v2/{self.endpoint_id}/run", self._headers(), {"input": {
            "task": "infinitetalk_dub", "video_url": video_url, "audio_base64": base64.b64encode(audio).decode(),
            "seconds": float(seconds)}})
        if status >= 400 or not data.get("id"):
            raise LipsyncError(f"InfiniteTalk worker refused the job ({status})")
        job = str(data["id"])
        waited = 0.0
        while waited <= self.timeout_s:
            status, data = self.http("GET", f"{self.base_url}/v2/{self.endpoint_id}/status/{job}", self._headers(),
                                     None)
            state = data.get("status")
            if state == "COMPLETED":
                output = data.get("output") or {}
                if output.get("error"):
                    raise LipsyncError(f"InfiniteTalk refused the job: {str(output['error'])[:200]}")
                url = output.get("video_url")
                if not url:
                    raise LipsyncError("InfiniteTalk finished without a video")
                gpu_s = float(data.get("executionTime") or 0) / 1000.0
                self.spent_usd = round(self.spent_usd + gpu_s / 3600 * E.RUNPOD_H100_PER_H, 4)
                return str(url)
            if state in ("FAILED", "CANCELLED", "TIMED_OUT"):
                raise LipsyncError(f"InfiniteTalk job {state.lower()}")
            self.sleep(self.poll_s)
            waited += self.poll_s
        raise LipsyncError("InfiniteTalk job timed out")


def kling_dub(client: KlingClient, *, video_url: str, audio: bytes, seconds: float) -> str:
    task = client.lip_sync(video_id="", video_url=video_url, audio_b64=base64.b64encode(audio).decode(),
                           seconds=int(math.ceil(seconds)))
    return str(client.wait("lipsync", task).get("url") or "")


def make_lipsync(engine: str, cap_usd: float, env: Mapping[str, str] | None = None, *,
                 http: Callable[[str, str, Mapping[str, str], Any], tuple[int, dict]] | None = None,
                 sleep: Callable[[float], None] | None = None) -> Callable[..., str]:
    e = os.environ if env is None else env
    if engine == "infinitetalk":
        if not configured("infinitetalk", e):
            raise LipsyncError("InfiniteTalk is not set up: RUNPOD_API_KEY and RUNPOD_INFINITETALK_ENDPOINT")
        extra: dict[str, Any] = {}
        if http is not None:
            extra["http"] = http
        if sleep is not None:
            extra["sleep"] = sleep
        dubber = InfiniteTalkDubber(api_key=e.get("RUNPOD_API_KEY", ""),
                                    endpoint_id=e.get("RUNPOD_INFINITETALK_ENDPOINT", ""), cap_usd=cap_usd, **extra)
        return lambda *, video_url, audio, seconds: dubber.dub(video_url=video_url, audio=audio, seconds=seconds)
    client = KlingClient.from_env(env, cap_usd=cap_usd)
    return lambda *, video_url, audio, seconds: kling_dub(client, video_url=video_url, audio=audio, seconds=seconds)


__all__ = ["ENGINES", "InfiniteTalkDubber", "LipsyncError", "configured", "kling_dub", "lipsync_usd",
           "make_lipsync", "tts_usd"]
