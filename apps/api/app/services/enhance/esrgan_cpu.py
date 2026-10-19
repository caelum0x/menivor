"""4x image upscale on CPU through the Real-ESRGAN sidecar (MH7).

The sidecar (``deploy/esrgan-ncnn``, box 1, tier 3, 512 MiB cap) wraps
Real-ESRGAN (BSD-3-Clause): the ncnn build when its CPU path works on the box,
else the PyTorch CPU build. This client sends one image, checks the answer is
exactly ``SCALE`` times larger, and records how long it took, so the "under
20 s for 1080p" target is measured per run before launch (target, not a claim).

Limits: inputs up to 1920 px on the long side; a per-user daily cap
(``UPSCALE_IMAGE_DAILY_CAP``, default 10) on standard-credit accounts. The CPU
lane costs us $0, so image upscales inside the cap are not charged.
"""

from __future__ import annotations

import io
import os
import time
import urllib.request
from dataclasses import dataclass
from typing import Callable

from .errors import EnhanceError

SCALE = 4
MAX_LONG_SIDE = 1920
DEFAULT_DAILY_CAP = 10
TIMEOUT_S = 120.0
URL_ENV = "MENIVOR_ESRGAN_URL"
CAP_ENV = "UPSCALE_IMAGE_DAILY_CAP"
#: The measured target: 1080p in, 4x out, on box 1 CPU (target until measured).
TARGET_SECONDS_1080P = 20.0

Post = Callable[[str, bytes, dict[str, str], float], tuple[int, bytes]]


@dataclass(frozen=True)
class Upscaled:
    image: bytes
    width: int
    height: int
    seconds: float


def sidecar_url() -> str:
    return (os.getenv(URL_ENV) or "").strip().rstrip("/")


def daily_cap() -> int:
    try:
        return max(0, int(os.getenv(CAP_ENV) or DEFAULT_DAILY_CAP))
    except ValueError:
        return DEFAULT_DAILY_CAP


def image_size(image: bytes) -> tuple[int, int]:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(image)) as im:
            return int(im.width), int(im.height)
    except (UnidentifiedImageError, OSError) as exc:
        raise EnhanceError(400, "not_an_image", "that file is not an image we can read") from exc


def check_input(image: bytes) -> tuple[int, int]:
    width, height = image_size(image)
    if max(width, height) > MAX_LONG_SIDE:
        raise EnhanceError(400, "image_too_large", f"images up to {MAX_LONG_SIDE} px on the long side")
    return width, height


def _post(url: str, body: bytes, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, method="POST", headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - configured sidecar URL
        return int(response.status), response.read()


def upscale(image: bytes, *, post: Post | None = None, url: str | None = None) -> Upscaled:
    base = url if url is not None else sidecar_url()
    if not base:
        raise EnhanceError(503, "upscale_offline", "image upscale is not switched on yet")
    width, height = check_input(image)
    started = time.monotonic()
    try:
        status, body = (post or _post)(f"{base}/v1/upscale?scale={SCALE}", image,
                                       {"Content-Type": "application/octet-stream"}, TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - network errors become a plain retry message
        raise EnhanceError(502, "upscale_failed", "the upscaler did not answer; try again") from exc
    seconds = time.monotonic() - started
    if status != 200:
        raise EnhanceError(502, "upscale_failed", "the upscaler could not finish this image")
    out_w, out_h = image_size(body)
    if (out_w, out_h) != (width * SCALE, height * SCALE):
        raise EnhanceError(502, "upscale_failed", "the upscaler returned the wrong size")
    return Upscaled(image=body, width=out_w, height=out_h, seconds=round(seconds, 2))


__all__ = ["MAX_LONG_SIDE", "SCALE", "TARGET_SECONDS_1080P", "Upscaled", "check_input", "daily_cap", "image_size",
           "sidecar_url", "upscale"]
