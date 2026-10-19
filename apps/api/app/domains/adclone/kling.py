"""Official Kling AI API client (kling.ai developer platform): image-to-video + audio lip-sync.

Auth: access key + secret key signed into a short-lived HS256 JWT (``iss`` = access key,
``exp`` = now + 30 min, ``nbf`` = now - 5 s), sent as ``Authorization: Bearer <jwt>``
(env ``KLING_ACCESS_KEY`` / ``KLING_SECRET_KEY``; a console API key in ``KLING_API_KEY`` is
sent as-is). Base URL ``https://api-singapore.klingai.com`` (servers outside China).

Endpoints (async tasks; poll until ``succeed`` / ``failed``):
* ``POST /v1/videos/image2video`` {model_name, image, prompt, negative_prompt, duration "5"|"10", mode, aspect_ratio}
* ``GET  /v1/videos/image2video/{task_id}`` -> data.task_status, data.task_result.videos[{id, url, duration}]
* ``POST /v1/videos/lip-sync`` {input: {video_id, mode: "audio2video", audio_type: "file", audio_file}}
* ``GET  /v1/videos/lip-sync/{task_id}``
Every call is checked against a spend cap; a balance error stops the run cleanly. The HTTP layer
is an injectable seam so tests never touch the network.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .engines import KLING_LIPSYNC_PER_5S, KLING_PRICES

BASE_URL = "https://api-singapore.klingai.com"
TOKEN_TTL_S = 1800
POLL_S = 10.0
TIMEOUT_S = 900.0
DONE, FAILED = "succeed", "failed"
BALANCE_CODES = {1101, 1102, 1103}  # account arrears / resource pack exhausted / expired
MAX_BACKOFF_S = 120.0
MAX_TRANSIENT = 6
NEGATIVE = "text, subtitles, watermark, logo, extra fingers, deformed hands, morphing print"

Http = Callable[[str, str, Mapping[str, str], Any], tuple[int, dict]]


class KlingError(RuntimeError):
    """``stop``: never retry (balance, auth, cap). ``transient``: retry with backoff (429, 5xx, network)."""

    def __init__(self, message: str, *, code: int | None = None, stop: bool = False, transient: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.stop = stop
        self.transient = transient and not stop


def backoff_s(attempt: int, base_s: float = POLL_S, cap_s: float = MAX_BACKOFF_S) -> float:
    """Exponential backoff for engine polling: base, 2x base, 4x base ... capped."""
    return float(min(cap_s, base_s * (2 ** max(attempt, 0))))


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def make_jwt(access_key: str, secret_key: str, now: float | None = None, ttl_s: int = TOKEN_TTL_S) -> str:
    t = int(now if now is not None else time.time())
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(json.dumps({"iss": access_key, "exp": t + ttl_s, "nbf": t - 5}, separators=(",", ":")).encode())
    sig = hmac.new(secret_key.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url(sig)}"


def default_http(method: str, url: str, headers: Mapping[str, str], body: Any) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=dict(headers))
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - fixed https base URL
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except Exception:  # noqa: BLE001
            return exc.code, {}


def clip_seconds(seconds: float) -> int:
    return 5 if seconds <= 5 else 10


def clip_cost(seconds: int, model: str, res: str) -> float:
    return round(seconds * KLING_PRICES[(model, res)], 4)


def lipsync_cost(seconds: int) -> float:
    return round(math.ceil(seconds / 5) * KLING_LIPSYNC_PER_5S, 4)


@dataclass
class KlingClient:
    access_key: str = ""
    secret_key: str = ""
    api_key: str = ""
    base_url: str = BASE_URL
    model: str = "kling-v3"
    resolution: str = "720p"
    mode: str = "std"
    http: Http = default_http
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.time
    cap_usd: float = 0.0
    spent_usd: float = 0.0
    ledger: list[dict] = field(default_factory=list)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, **kw: Any) -> "KlingClient":
        env = os.environ if env is None else env
        client = cls(access_key=env.get("KLING_ACCESS_KEY", ""), secret_key=env.get("KLING_SECRET_KEY", ""),
                     api_key=env.get("KLING_API_KEY", ""), base_url=env.get("KLING_BASE_URL") or BASE_URL,
                     model=env.get("KLING_MODEL") or "kling-v3", resolution=env.get("KLING_RESOLUTION") or "720p",
                     mode=env.get("KLING_MODE") or "std", **kw)
        if not client.configured:
            raise KlingError("set KLING_ACCESS_KEY and KLING_SECRET_KEY (or KLING_API_KEY)")
        return client

    @property
    def configured(self) -> bool:
        return bool(self.api_key or (self.access_key and self.secret_key))

    def _headers(self) -> dict[str, str]:
        token = self.api_key or make_jwt(self.access_key, self.secret_key, self.clock())
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _call(self, method: str, path: str, body: Any = None) -> dict:
        try:
            status, data = self.http(method, self.base_url + path, self._headers(), body)
        except Exception as exc:  # noqa: BLE001 - network boundary: retryable
            raise KlingError(f"Kling unreachable: {type(exc).__name__}", transient=True) from exc
        data = data if isinstance(data, dict) else {}
        code = data.get("code")
        if status == 429 or status >= 500:
            raise KlingError(f"Kling busy ({status})", code=code, transient=True)
        if code in BALANCE_CODES or status == 402:
            raise KlingError("Kling account balance or resource pack is exhausted", code=code, stop=True)
        if status >= 400 or (code not in (0, None)):
            raise KlingError(f"Kling error {status}/{code}: {str(data.get('message', ''))[:200]}", code=code,
                             stop=status in (401, 403))
        return data.get("data") or {}

    def _check_cap(self, item: str, usd: float) -> None:
        if self.cap_usd and self.spent_usd + usd > self.cap_usd + 1e-9:
            raise KlingError(f"spend cap ${self.cap_usd:.2f} reached before {item} (${usd:.2f})", stop=True)

    def _charge(self, item: str, usd: float) -> None:
        """Book a cost once Kling accepted the task (a refused submit is not billed)."""
        self.spent_usd = round(self.spent_usd + usd, 4)
        self.ledger.append({"item": item, "usd": usd})

    def _submit(self, item: str, usd: float, path: str, body: dict) -> str:
        self._check_cap(item, usd)
        task = self._call("POST", path, body)
        if not task.get("task_id"):
            raise KlingError("Kling returned no task id")
        self._charge(item, usd)
        return str(task["task_id"])

    # Engine interface shared with engine_clients (the worker drives every engine the same way).
    name = "kling"
    lipsync = "separate"  # a second lip-sync task drives the lips with our audio
    needs_url = False

    def image_to_video(self, *, image: str, prompt: str, seconds: float, aspect_ratio: str = "9:16",
                       audio_b64: str | None = None, image_url: str | None = None) -> str:
        dur = clip_seconds(seconds)
        body = {"model_name": self.model, "image": image, "prompt": prompt[:2500], "negative_prompt": NEGATIVE,
                "duration": str(dur), "mode": self.mode, "aspect_ratio": aspect_ratio, "cfg_scale": 0.5}
        return self._submit(f"i2v {dur}s", clip_cost(dur, self.model, self.resolution), "/v1/videos/image2video", body)

    def lip_sync(self, *, video_id: str, audio_b64: str, seconds: int, video_url: str | None = None,
                 audio_url: str | None = None) -> str:
        # A Kling-made clip is referenced by id; any other video (e.g. lip-sync translation) by its URL.
        if not video_id and not video_url:
            raise KlingError("lip-sync needs the Kling video id or a video URL", stop=True)
        source = {"video_id": video_id} if video_id else {"video_url": video_url}
        body = {"input": {**source, "mode": "audio2video", "audio_type": "file", "audio_file": audio_b64}}
        return self._submit(f"lip-sync {seconds}s", lipsync_cost(seconds), "/v1/videos/lip-sync", body)

    def status(self, kind: str, task_id: str) -> tuple[str, dict | None]:
        """One non-blocking poll: ("running", None) | ("done", video) | raises KlingError on a failed task."""
        path = {"i2v": "/v1/videos/image2video/", "lipsync": "/v1/videos/lip-sync/"}[kind] + task_id
        data = self._call("GET", path)
        state = data.get("task_status")
        if state == DONE:
            videos = (data.get("task_result") or {}).get("videos") or []
            if not videos:
                raise KlingError(f"Kling task {task_id} finished without a video")
            return "done", videos[0]
        if state == FAILED:
            raise KlingError(f"Kling task {task_id} failed: {str(data.get('task_status_msg', ''))[:200]}")
        return "running", None

    def wait(self, kind: str, task_id: str, *, poll_s: float = POLL_S, timeout_s: float = TIMEOUT_S) -> dict:
        """Blocking poll with exponential backoff on transient errors (429 / 5xx / network)."""
        start = self.clock()
        transient = 0
        while True:
            try:
                state, video = self.status(kind, task_id)
                transient = 0
            except KlingError as exc:
                if not exc.transient or transient >= MAX_TRANSIENT:
                    raise
                transient += 1
                self.sleep(backoff_s(transient, poll_s))
                continue
            if state == "done":
                return video or {}
            if self.clock() - start > timeout_s:
                raise KlingError(f"Kling task {task_id} timed out")
            self.sleep(poll_s)

    def render_talk_shot(self, *, first_frame: bytes, prompt: str, audio: bytes, seconds: float,
                         aspect_ratio: str = "9:16") -> dict:
        """Character still as first frame -> Kling video -> lip-synced to our ElevenLabs line audio."""
        image = base64.b64encode(first_frame).decode()
        i2v = self.wait("i2v", self.image_to_video(image=image, prompt=prompt, seconds=seconds,
                                                    aspect_ratio=aspect_ratio))
        dur = clip_seconds(seconds)
        lips = self.wait("lipsync", self.lip_sync(video_id=str(i2v.get("id")), audio_b64=base64.b64encode(audio).decode(),
                                                  seconds=dur))
        return {"video_id": i2v.get("id"), "video_url": i2v.get("url"), "lipsync_url": lips.get("url"),
                "seconds": dur, "spent_usd": self.spent_usd}

    def dry_run_requests(self, plan: Mapping[str, Any]) -> list[dict]:
        """What a paid run would send per shot (no network, no key needed)."""
        out = []
        for s in plan.get("shots") or []:
            dur = clip_seconds(float(s["dur"]))
            out.append({"shot": s["id"], "i2v": {"model_name": self.model, "duration": str(dur), "mode": self.mode,
                                                  "aspect_ratio": plan.get("aspect", "9:16"),
                                                  "first_frame": (s.get("refs") or [None])[0]},
                        "lip_sync": {"mode": "audio2video", "lines": list(s.get("lines") or [])},
                        "usd": round(clip_cost(dur, self.model, self.resolution) + lipsync_cost(dur), 4)})
        return out
