"""Replicate image generation — a REAL adapter over Replicate's predictions API.

A third real *image* backend (FLUX / SDXL and other open image models hosted on
Replicate). Imports ``requests``; runs live with a real ``REPLICATE_API_TOKEN``.
Replicate predictions are normally async, but the API accepts a ``Prefer: wait``
header that blocks until the prediction finishes (or the wait window elapses) —
so the gateway's synchronous ``/images`` contract is honored with a single call,
falling back to a short bounded poll if the wait window is exceeded.

Real flow:
  ``POST /v1/models/{owner}/{name}/predictions`` (Bearer + ``Prefer: wait``)
  → ``{status: succeeded|processing|…, output: url|[url], urls:{get}, error}``.
"""

from __future__ import annotations

import time
from typing import Any, Sequence

from app.domains.routing.providers.kling_fal import KlingError as ProviderCallError

_BASE = "https://api.replicate.com/v1"


SEEDREAM_45 = "bytedance/seedream-4.5"
FLUX_KONTEXT_PRO = "black-forest-labs/flux-kontext-pro"
NANO_BANANA = "google/nano-banana"
# Models that take a list of reference images as ``image_input`` (multi-reference).
NANO_BANANA_PRO = "google/nano-banana-pro"
_IMAGE_INPUT_LIST = {SEEDREAM_45: 14, NANO_BANANA: 3, NANO_BANANA_PRO: 14}
# Models that take one reference image as ``input_image``.
_INPUT_IMAGE_ONE = {FLUX_KONTEXT_PRO}
# Seedream custom sizes per aspect ratio (its custom range is 1024-4096 px a side).
_SEEDREAM_SIZES = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (2048, 2048)}


def build_image_input(model_ref: str, prompt: str, *, aspect_ratio: str = "9:16",
                      image_urls: Sequence[str] = ()) -> dict:
    """The Replicate ``input`` for an image model, references mapped per model (pure).

    Seedream 4.5 / Nano Banana: ``image_input`` list. FLUX Kontext Pro:
    ``input_image`` (exactly one). Any other model refuses references (never
    dropped silently).
    """
    refs = [u for u in image_urls if u]
    inp: dict = {"prompt": prompt}
    if model_ref == SEEDREAM_45:
        width, height = _SEEDREAM_SIZES.get(aspect_ratio, (2048, 2048))
        inp.update(size="custom", width=width, height=height)
    else:
        inp["aspect_ratio"] = aspect_ratio
    if model_ref == NANO_BANANA_PRO:
        inp.update(resolution="2K", output_format="png")  # the Oxhan episode renders: 2K, lettering holds
    if not refs:
        return inp
    if model_ref in _IMAGE_INPUT_LIST:
        cap = _IMAGE_INPUT_LIST[model_ref]
        if len(refs) > cap:
            raise ProviderCallError(f"{model_ref} takes at most {cap} reference images", kind="validation")
        inp["image_input"] = refs
    elif model_ref in _INPUT_IMAGE_ONE:
        if len(refs) > 1:
            raise ProviderCallError(f"{model_ref} takes one reference image", kind="validation")
        inp["input_image"] = refs[0]
    else:
        raise ProviderCallError(f"{model_ref} does not take reference images", kind="validation")
    return inp


def replicate_generate_image(model_ref: str, prompt: str, *, api_key: str, session: Any = None,
                             aspect_ratio: str = "9:16", timeout_s: float = 120.0,
                             max_polls: int = 20, sleep=time.sleep, image_urls: Sequence[str] = ()) -> str:
    """Generate one image synchronously and return its hosted URL.

    ``model_ref`` is a Replicate ``owner/name`` path (e.g. ``black-forest-labs/flux-schnell``).
    ``image_urls`` are reference images, mapped per model by :func:`build_image_input`.
    """
    if not prompt:
        raise ProviderCallError("a prompt is required", kind="validation")
    if not api_key:
        raise ProviderCallError("REPLICATE_API_TOKEN not configured", kind="auth")
    if session is None:
        import requests

        session = requests.Session()

    body = {"input": build_image_input(model_ref, prompt, aspect_ratio=aspect_ratio, image_urls=image_urls)}
    # Official models (e.g. black-forest-labs/flux-*) are served by the
    # official-model route; community models (stability-ai/sdxl, ideogram,
    # recraft, playground, sd-3.5-large, …) are NOT — that route returns 404 —
    # so fall back to a version-pinned ``POST /v1/predictions``. Replicate
    # ignores unknown input keys, so the portable ``aspect_ratio`` is safe to
    # send even to models that size via width/height.
    try:
        payload = _request(session, "POST", f"{_BASE}/models/{model_ref}/predictions", api_key=api_key,
                           json=body, prefer_wait=True, timeout_s=timeout_s, sleep=sleep)
    except ProviderCallError as exc:
        if getattr(exc, "status", 0) != 404:
            raise
        version = _resolve_version(session, model_ref, api_key=api_key, timeout_s=timeout_s, sleep=sleep)
        payload = _request(session, "POST", f"{_BASE}/predictions", api_key=api_key,
                           json={"version": version, **body}, prefer_wait=True,
                           timeout_s=timeout_s, sleep=sleep)

    status = str(payload.get("status") or "")
    get_url = str((payload.get("urls") or {}).get("get") or "")
    polls = 0
    while status not in ("succeeded", "failed", "canceled"):
        if polls >= max_polls or not get_url:
            raise ProviderCallError("replicate image did not finish in the wait window",
                                    kind="transient", retryable=True)
        polls += 1
        sleep(1.0)
        payload = _request(session, "GET", get_url, api_key=api_key, timeout_s=timeout_s, sleep=sleep)
        status = str(payload.get("status") or "")

    if status != "succeeded":
        raise ProviderCallError(f"replicate image {status}: {payload.get('error') or ''}",
                                kind="provider")
    url = _first_output(payload.get("output"))
    if not url:
        raise ProviderCallError(f"replicate image succeeded but no output: {payload}", kind="provider")
    return url


def _resolve_version(session: Any, model_ref: str, *, api_key: str, timeout_s: float, sleep) -> str:
    """Resolve a Replicate model's latest version id for a version-pinned submit."""
    meta = _request(session, "GET", f"{_BASE}/models/{model_ref}", api_key=api_key,
                    timeout_s=timeout_s, sleep=sleep)
    version = str((meta.get("latest_version") or {}).get("id") or "")
    if not version:
        raise ProviderCallError(f"replicate model {model_ref!r} has no resolvable version",
                                kind="provider")
    return version


def _first_output(output: Any) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, list) and output:
        first = output[0]
        return str(first) if isinstance(first, str) else ""
    return ""


def _request(session: Any, method: str, url: str, *, api_key: str, json: dict | None = None,
             prefer_wait: bool = False, timeout_s: float, max_retries: int = 3, sleep) -> dict:
    import requests

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if prefer_wait:
        headers["Prefer"] = "wait"
    attempt = 0
    while True:
        attempt += 1
        try:
            resp = session.request(method, url, headers=headers, json=json, timeout=timeout_s)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            if attempt <= max_retries:
                sleep(min(20.0, 2 ** (attempt - 1)))
                continue
            raise ProviderCallError(f"replicate network error: {exc}", kind="transient",
                                    retryable=True) from exc
        status = resp.status_code
        payload = _json(resp)
        if 200 <= status < 300:
            return payload
        detail = str((payload.get("detail") or payload.get("title")) if isinstance(payload, dict) else "") \
            or f"HTTP {status}"
        if status in (401, 403):
            raise ProviderCallError(f"replicate auth failed: {detail}", kind="auth", status=status)
        if status in (400, 422):
            raise ProviderCallError(f"replicate rejected request: {detail}", kind="validation", status=status)
        if status == 429:
            if attempt <= max_retries:
                sleep(min(30.0, 2 ** attempt))
                continue
            raise ProviderCallError("replicate rate limit", kind="rate_limit", retryable=True, status=429)
        if status >= 500:
            if attempt <= max_retries:
                sleep(min(20.0, 2 ** (attempt - 1)))
                continue
            raise ProviderCallError(f"replicate server error: {detail}", kind="transient", retryable=True,
                                    status=status)
        raise ProviderCallError(f"replicate unexpected status {status}: {detail}", kind="provider",
                                status=status)


def _json(resp) -> dict:
    try:
        body = resp.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {"data": body}
