"""Google Imagen image generation — a REAL adapter over the Generative Language API.

A fourth real *image* backend, on the same Google surface as the Veo video adapter
(API-key query-param auth) but the **synchronous** ``:predict`` endpoint. Imports
``requests``; runs live with a real ``GEMINI_API_KEY``.

Real flow:
  ``POST /v1beta/models/{model}:predict?key=…``
  body ``{instances:[{prompt}], parameters:{sampleCount, aspectRatio}}``
  → ``{predictions:[{bytesBase64Encoded, mimeType}]}``.

Imagen returns base64 image bytes (no hosted URL), so this returns a
``data:<mime>;base64,…`` URL — a directly-renderable URL honoring the gateway's
"images come back as a url" contract.
"""

from __future__ import annotations

import time
from typing import Any

from app.domains.routing.providers.kling_fal import KlingError as ProviderCallError

_BASE = "https://generativelanguage.googleapis.com/v1beta"


def imagen_generate_image(model_ref: str, prompt: str, *, api_key: str, session: Any = None,
                          aspect_ratio: str = "9:16", timeout_s: float = 120.0,
                          max_retries: int = 3, sleep=time.sleep) -> str:
    """Generate one image synchronously and return a ``data:`` URL."""
    if not prompt:
        raise ProviderCallError("a prompt is required", kind="validation")
    if not api_key:
        raise ProviderCallError("GEMINI_API_KEY not configured", kind="auth")
    if session is None:
        import requests

        session = requests.Session()

    body = {
        "instances": [{"prompt": prompt}],
        "parameters": {"sampleCount": 1, "aspectRatio": aspect_ratio},
    }
    url = f"{_BASE}/models/{model_ref}:predict?key={api_key}"
    payload = _post(session, url, body, timeout_s=timeout_s, max_retries=max_retries, sleep=sleep)

    preds = payload.get("predictions") or []
    if not isinstance(preds, list) or not preds:
        raise ProviderCallError(f"imagen returned no predictions: {payload}", kind="provider")
    first = preds[0] or {}
    b64 = str(first.get("bytesBase64Encoded") or first.get("image") or "")
    if not b64:
        raise ProviderCallError(f"imagen prediction had no image bytes: {first}", kind="provider")
    mime = str(first.get("mimeType") or "image/png")
    return f"data:{mime};base64,{b64}"


def _post(session: Any, url: str, body: dict, *, timeout_s: float, max_retries: int, sleep) -> dict:
    import requests

    attempt = 0
    while True:
        attempt += 1
        try:
            resp = session.request("POST", url, headers={"Content-Type": "application/json"},
                                   json=body, timeout=timeout_s)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            if attempt <= max_retries:
                sleep(min(20.0, 2 ** (attempt - 1)))
                continue
            raise ProviderCallError(f"imagen network error: {exc}", kind="transient",
                                    retryable=True) from exc
        status = resp.status_code
        payload = _json(resp)
        if 200 <= status < 300:
            return payload
        gerr = (payload.get("error") or {}) if isinstance(payload, dict) else {}
        msg = str(gerr.get("message") or f"HTTP {status}")
        if status in (401, 403):
            raise ProviderCallError(f"imagen auth failed: {msg}", kind="auth", status=status)
        if status == 400:
            raise ProviderCallError(f"imagen rejected request: {msg}", kind="validation", status=400)
        if status == 429:
            if attempt <= max_retries:
                sleep(min(30.0, 2 ** attempt))
                continue
            raise ProviderCallError("imagen rate limit (quota)", kind="rate_limit", retryable=True, status=429)
        if status >= 500:
            if attempt <= max_retries:
                sleep(min(20.0, 2 ** (attempt - 1)))
                continue
            raise ProviderCallError(f"imagen server error: {msg}", kind="transient", retryable=True,
                                    status=status)
        raise ProviderCallError(f"imagen unexpected status {status}: {msg}", kind="provider", status=status)


def _json(resp) -> dict:
    try:
        body = resp.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {"data": body}
