"""2x frame interpolation (smooth motion) with Practical-RIFE on the GPU lane only (MH7).

Practical-RIFE (MIT) runs in a RunPod Serverless worker we deploy; it never
runs on box 1 or the Mac. The lane is off until ``RIFE_RUNPOD_ENDPOINT_ID``
and ``RIFE_RUNPOD_API_KEY`` are set, and unpriced (402 ``sku_unpriced``) until
the measured GPU price per output minute is recorded in ``RIFE_GPU_USD_PER_MIN``
(MG3 rule: a SKU without a recorded price is never sold). Sold at 3x.
"""

from __future__ import annotations

import os
from typing import Any

from .errors import EnhanceError

ENDPOINT_ENV = "RIFE_RUNPOD_ENDPOINT_ID"
KEY_ENV = "RIFE_RUNPOD_API_KEY"
PRICE_ENV = "RIFE_GPU_USD_PER_MIN"
MAX_SECONDS = 60.0
MULTI = 2


def lane_configured() -> bool:
    return bool((os.getenv(ENDPOINT_ENV) or "").strip() and (os.getenv(KEY_ENV) or "").strip())


def usd_per_minute() -> float | None:
    raw = (os.getenv(PRICE_ENV) or "").strip()
    try:
        value = float(raw) if raw else 0.0
    except ValueError:
        return None
    return value if value > 0 else None


def quote(*, seconds: float) -> dict[str, Any]:
    from app.services.billing.premium_credits import ai_video_credits_for_usd

    if not lane_configured():
        raise EnhanceError(503, "gpu_lane_off", "smooth motion runs only on the GPU lane, which is off right now")
    price = usd_per_minute()
    if price is None:
        raise EnhanceError(402, "sku_unpriced", "smooth motion has no recorded price yet")
    if seconds <= 0 or seconds > MAX_SECONDS:
        raise EnhanceError(400, "video_too_long", f"smooth motion takes clips up to {int(MAX_SECONDS)} s")
    usd = round(price * seconds / 60.0, 4)
    return {"op": "smooth", "multi": MULTI, "provider_usd": usd,
            "ai_video_credits": max(1, ai_video_credits_for_usd(usd)), "price_source": PRICE_ENV}


def interpolate(video_url: str, *, client: Any = None) -> str:
    """Run the RIFE worker and return the output video URL."""
    if not lane_configured():
        raise EnhanceError(503, "gpu_lane_off", "smooth motion runs only on the GPU lane, which is off right now")
    if client is None:
        from app.services.avatar.latentsync_runpod import LatentSyncClient

        client = LatentSyncClient(api_key=os.getenv(KEY_ENV, ""), endpoint_id=os.getenv(ENDPOINT_ENV, ""))
    job = client.run({"video_url": video_url, "multi": MULTI})
    output = client.wait(job) or {}
    url = str(output.get("video_url") or output.get("output") or "")
    if not url.startswith("https://"):
        raise EnhanceError(502, "smooth_failed", "the GPU lane finished without a video")
    return url


__all__ = ["MAX_SECONDS", "interpolate", "lane_configured", "quote", "usd_per_minute"]
