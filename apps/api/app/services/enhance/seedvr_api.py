"""Video upscale through the SeedVR2 API (MH7), AI-video credits only.

SeedVR2 weights are Apache-2.0; we call the hosted model on the fal queue
(``fal-ai/seedvr/upscale/video``) and never run it ourselves. The price comes
from the gateway catalog row ``bytedance/seedvr2-upscale`` ($0.001 per output
megapixel-frame, source and date recorded there), sold at 3x
(``premium_credits.AI_VIDEO_MARKUP``) and quoted before anything starts.
1080p for 5 s at 24 fps is about $0.25 at cost.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from typing import Any

from .errors import EnhanceError

MODEL_ID = "bytedance/seedvr2-upscale"
QUEUE = "https://queue.fal.run"
FACTOR = 2
MAX_SECONDS = 60.0
MAX_OUTPUT_LONG_SIDE = 3840
POLL_S = 5.0
TIMEOUT_S = 30 * 60.0


def _model():
    from app.domains.gateway.media_catalog import stage_models

    model = next((m for m in stage_models() if m.id == MODEL_ID), None)
    if model is None:
        raise EnhanceError(402, "sku_unpriced", "video upscale has no recorded price")
    return model


def output_size(width: int, height: int, factor: int = FACTOR) -> tuple[int, int]:
    out_w, out_h = int(width) * factor, int(height) * factor
    if max(out_w, out_h) > MAX_OUTPUT_LONG_SIDE:
        shrink = MAX_OUTPUT_LONG_SIDE / max(out_w, out_h)
        out_w, out_h = int(out_w * shrink) // 2 * 2, int(out_h * shrink) // 2 * 2
    return out_w, out_h


def quote(*, width: int, height: int, seconds: float, fps: float) -> dict[str, Any]:
    from app.services.billing.premium_credits import ai_video_credits_for_usd

    if seconds <= 0 or fps <= 0:
        raise EnhanceError(400, "bad_video", "we could not read that video's length")
    if seconds > MAX_SECONDS:
        raise EnhanceError(400, "video_too_long", f"video upscale takes clips up to {int(MAX_SECONDS)} s")
    model = _model()
    out_w, out_h = output_size(width, height)
    megapixels = out_w * out_h * math.ceil(seconds * fps) / 1_000_000
    usd = round(megapixels * model.price_micros / 1_000_000, 4)
    return {
        "op": "upscale", "output": [out_w, out_h], "megapixels": round(megapixels, 1), "provider_usd": usd,
        "ai_video_credits": max(1, ai_video_credits_for_usd(usd)), "price_source": model.price_source,
        "price_date": model.price_date,
    }


@dataclass
class SeedVRClient:
    api_key: str = ""
    session: Any = None
    sleep: Any = time.sleep

    def _headers(self) -> dict[str, str]:
        key = self.api_key or os.getenv("FAL_KEY", "")
        if not key:
            raise EnhanceError(503, "upscale_offline", "video upscale is not switched on yet")
        return {"Authorization": f"Key {key}", "Content-Type": "application/json"}

    def _http(self):
        if self.session is None:
            import requests

            self.session = requests.Session()
        return self.session

    def submit(self, video_url: str, factor: int = FACTOR) -> dict[str, str]:
        model = _model()
        response = self._http().post(f"{QUEUE}/{model.model_ref}", headers=self._headers(),
                                     json={"video_url": video_url, "upscale_factor": factor}, timeout=60)
        if response.status_code >= 400:
            raise EnhanceError(502, "upscale_failed", f"the upscaler refused the video ({response.status_code})")
        body = response.json() or {}
        request_id = str(body.get("request_id") or "")
        if not request_id:
            raise EnhanceError(502, "upscale_failed", "the upscaler did not accept the video")
        base = f"{QUEUE}/{model.model_ref}/requests/{request_id}"
        return {"request_id": request_id, "status_url": str(body.get("status_url") or f"{base}/status"),
                "response_url": str(body.get("response_url") or base)}

    def wait(self, handle: dict[str, str], *, timeout_s: float = TIMEOUT_S) -> str:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            status = self._http().get(handle["status_url"], headers=self._headers(), timeout=30).json() or {}
            state = str(status.get("status") or "").upper()
            if state == "COMPLETED":
                result = self._http().get(handle["response_url"], headers=self._headers(), timeout=30).json() or {}
                url = str(((result.get("video") or {}) if isinstance(result.get("video"), dict) else {}).get("url")
                          or "")
                if not url:
                    raise EnhanceError(502, "upscale_failed", "the upscaler finished without a video")
                return url
            if state in {"FAILED", "CANCELLED", "ERROR"}:
                raise EnhanceError(502, "upscale_failed", "the upscaler could not finish this video")
            self.sleep(POLL_S)
        raise EnhanceError(504, "upscale_timeout", "the upscaler took too long")


__all__ = ["FACTOR", "MAX_SECONDS", "MODEL_ID", "SeedVRClient", "output_size", "quote"]
