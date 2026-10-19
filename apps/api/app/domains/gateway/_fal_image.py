"""Real fal.ai synchronous image generation (queue protocol, wait inline).

Images on fal.ai use the same queue REST API as video but render fast, so the
gateway waits inline and returns the image URL directly (OpenRouter ``/images``
parity). Real ``requests`` calls to ``queue.fal.run``, real ``Key`` auth, real
poll loop + error mapping (reusing ``KlingError`` as the shared error type). The
``session`` is injectable for tests; the protocol is real.
"""

from __future__ import annotations

import time
from typing import Any, Sequence

from app.domains.routing.providers.kling_fal import KlingError

_QUEUE_BASE = "https://queue.fal.run"


def _session(session: Any):
    if session is not None:
        return session
    import requests

    return requests.Session()


def _headers(api_key: str) -> dict:
    if not api_key:
        raise KlingError("FAL_KEY not configured", kind="auth")
    return {"Authorization": f"Key {api_key}", "Content-Type": "application/json"}


def _json(resp) -> dict:
    try:
        body = resp.json()
    except Exception as exc:  # pragma: no cover
        raise KlingError(f"fal.ai returned a non-JSON body: {exc}", kind="provider") from exc
    return body if isinstance(body, dict) else {"data": body}


def _check(resp) -> dict:
    status = resp.status_code
    if 200 <= status < 300:
        return _json(resp)
    if status in (401, 403):
        raise KlingError(f"fal.ai auth failed ({status})", kind="auth", status=status)
    if status == 422:
        raise KlingError("fal.ai rejected the image request (422)", kind="validation", status=422)
    if status == 429:
        raise KlingError("fal.ai rate limit", kind="rate_limit", retryable=True, status=429)
    if status >= 500:
        raise KlingError(f"fal.ai server error {status}", kind="transient", retryable=True, status=status)
    raise KlingError(f"fal.ai unexpected status {status}", kind="provider", status=status)


def _first_image_url(output: dict) -> str:
    """fal image output shape: {"images": [{"url": "…"}]} (or a single "image")."""
    images = output.get("images")
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, dict) and first.get("url"):
            return str(first["url"])
    img = output.get("image")
    if isinstance(img, dict) and img.get("url"):
        return str(img["url"])
    return ""


def fal_generate_image(
    model_ref: str, prompt: str, *, api_key: str, image_urls: Sequence[str] = (), session: Any = None,
    timeout_s: float = 60.0, max_poll_s: float = 120.0, poll_interval_s: float = 1.0,
    sleep=time.sleep,
) -> str:
    """Submit an image job, wait inline, and return the produced image URL.

    ``image_urls`` (reference images, already public URLs in @ImageN order) are sent
    as ``"image_urls"`` (the fal Seedream / Nano Banana edit shape); without them the
    body is the prompt only, exactly as before.
    """
    if not prompt:
        raise KlingError("a prompt is required", kind="validation")
    sess = _session(session)
    h = _headers(api_key)

    payload: dict[str, Any] = {"prompt": prompt}
    refs = [str(u) for u in image_urls or () if u]
    if refs:
        payload["image_urls"] = refs
    body = _check(sess.request("POST", f"{_QUEUE_BASE}/{model_ref}",
                               headers=h, json=payload, timeout=timeout_s))
    request_id = str(body.get("request_id") or "")
    if not request_id:
        raise KlingError(f"fal.ai submit returned no request_id: {body}", kind="provider")
    status_url = str(body.get("status_url") or f"{_QUEUE_BASE}/{model_ref}/requests/{request_id}/status")
    response_url = str(body.get("response_url") or f"{_QUEUE_BASE}/{model_ref}/requests/{request_id}")

    waited = 0.0
    while True:
        status = _check(sess.request("GET", status_url, headers=h, timeout=timeout_s))
        state = str(status.get("status", "IN_PROGRESS") or "IN_PROGRESS").upper()
        if state == "COMPLETED":
            break
        if waited >= max_poll_s:
            raise KlingError(f"image did not complete within {max_poll_s}s", kind="transient", retryable=True)
        sleep(poll_interval_s)
        waited += poll_interval_s

    result = _check(sess.request("GET", response_url, headers=h, timeout=timeout_s))
    url = _first_image_url(result)
    if not url:
        raise KlingError(f"completed but no image url: {result}", kind="provider")
    return url
