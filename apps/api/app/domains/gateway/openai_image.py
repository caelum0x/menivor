"""OpenAI image generation — a REAL adapter over the OpenAI Images API.

The second real *image* backend (alongside fal.ai), giving the gateway's ``/images``
surface true multi-provider parity like OpenRouter. Imports ``requests``; runs live
with a real ``OPENAI_API_KEY`` (Bearer). Synchronous: one POST returns the image.

Real flow:
  ``POST https://api.openai.com/v1/images/generations`` (Bearer)
  body ``{model, prompt, size, n}`` → ``{data: [{url} | {b64_json}]}``.

``gpt-image-1`` returns base64 (no hosted url), so when only ``b64_json`` is present
this returns a ``data:image/png;base64,…`` URL — still a directly-renderable URL,
honoring the gateway's "images come back as a url" contract. Error taxonomy shared
with the video adapters via :class:`KlingError`. ``requests.Session`` is injectable.
"""

from __future__ import annotations

import time
from typing import Any

from app.domains.routing.providers.kling_fal import KlingError as ProviderCallError

_URL = "https://api.openai.com/v1/images/generations"


def openai_generate_image(model_ref: str, prompt: str, *, api_key: str, session: Any = None,
                          size: str = "1024x1536", timeout_s: float = 120.0,
                          max_retries: int = 3, sleep=time.sleep) -> str:
    """Generate one image synchronously and return a renderable URL.

    ``size`` defaults to a 2:3 portrait (good for short-form covers). Returns a
    hosted url when the model provides one, otherwise a ``data:`` URL built from
    the returned base64.
    """
    if not prompt:
        raise ProviderCallError("a prompt is required", kind="validation")
    if not api_key:
        raise ProviderCallError("OPENAI_API_KEY not configured", kind="auth")
    if session is None:
        import requests

        session = requests.Session()

    body = {"model": model_ref, "prompt": prompt, "size": size, "n": 1}
    payload = _post(session, body, api_key=api_key, timeout_s=timeout_s,
                    max_retries=max_retries, sleep=sleep)
    data = payload.get("data") or []
    if not isinstance(data, list) or not data:
        raise ProviderCallError(f"openai returned no image data: {payload}", kind="provider")
    first = data[0] or {}
    url = str(first.get("url") or "")
    if url:
        return url
    b64 = str(first.get("b64_json") or "")
    if b64:
        return f"data:image/png;base64,{b64}"
    raise ProviderCallError(f"openai image had neither url nor b64_json: {first}", kind="provider")


def _post(session: Any, body: dict, *, api_key: str, timeout_s: float, max_retries: int, sleep) -> dict:
    import requests

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    attempt = 0
    while True:
        attempt += 1
        try:
            resp = session.request("POST", _URL, headers=headers, json=body, timeout=timeout_s)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            if attempt <= max_retries:
                sleep(min(20.0, 2 ** (attempt - 1)))
                continue
            raise ProviderCallError(f"openai network error: {exc}", kind="transient",
                                    retryable=True) from exc
        status = resp.status_code
        payload = _json(resp)
        if 200 <= status < 300:
            return payload
        msg = str(((payload.get("error") or {}).get("message")) if isinstance(payload, dict) else "") \
            or f"HTTP {status}"
        if status in (401, 403):
            raise ProviderCallError(f"openai auth failed: {msg}", kind="auth", status=status)
        if status == 400:
            raise ProviderCallError(f"openai rejected request: {msg}", kind="validation", status=400)
        if status == 429:
            if attempt <= max_retries:
                sleep(min(30.0, 2 ** attempt))
                continue
            raise ProviderCallError("openai rate limit", kind="rate_limit", retryable=True, status=429)
        if status >= 500:
            if attempt <= max_retries:
                sleep(min(20.0, 2 ** (attempt - 1)))
                continue
            raise ProviderCallError(f"openai server error: {msg}", kind="transient", retryable=True,
                                    status=status)
        raise ProviderCallError(f"openai unexpected status {status}: {msg}", kind="provider", status=status)


def _json(resp) -> dict:
    try:
        body = resp.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {"data": body}
