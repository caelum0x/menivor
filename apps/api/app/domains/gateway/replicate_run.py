"""One Replicate prediction, synchronous or async (shared by speech, sound effects and lip-sync).

Replicate's prediction API (``POST /v1/models/{owner}/{name}/predictions`` with
``Bearer`` auth; community models fall back to a version-pinned
``POST /v1/predictions``) with the HTTP and error mapping of
:mod:`app.domains.gateway.replicate_image`. :func:`run` waits (``Prefer: wait``
plus a bounded poll) and returns the output URL; :func:`submit` / :func:`poll`
are the async pair for long jobs (lip-sync).
"""

from __future__ import annotations

import os
import time
from typing import Any

from app.domains.gateway.replicate_image import _BASE, _first_output, _request, _resolve_version
from app.domains.routing.providers.kling_fal import KlingError as ProviderCallError

TOKEN_ENV = "REPLICATE_API_TOKEN"


def api_key() -> str:
    return os.getenv(TOKEN_ENV, "").strip()


def is_enabled() -> bool:
    return bool(api_key())


def _session(session: Any):
    if session is not None:
        return session
    import requests

    return requests.Session()


def _key(key: str) -> str:
    token = key or api_key()
    if not token:
        raise ProviderCallError(f"{TOKEN_ENV} not configured", kind="auth")
    return token


def submit(model_path: str, inputs: dict, *, key: str = "", session: Any = None, wait: bool = False,
           timeout_s: float = 120.0, sleep=time.sleep) -> dict:
    """Create a prediction; returns Replicate's payload (``id``, ``status``, ``urls.get``, ``output``)."""
    sess, token = _session(session), _key(key)
    try:
        return _request(sess, "POST", f"{_BASE}/models/{model_path}/predictions", api_key=token,
                        json={"input": inputs}, prefer_wait=wait, timeout_s=timeout_s, sleep=sleep)
    except ProviderCallError as exc:
        if getattr(exc, "status", 0) != 404:
            raise
    version = _resolve_version(sess, model_path, api_key=token, timeout_s=timeout_s, sleep=sleep)
    return _request(sess, "POST", f"{_BASE}/predictions", api_key=token, json={"version": version, "input": inputs},
                    prefer_wait=wait, timeout_s=timeout_s, sleep=sleep)


def get(url: str, *, key: str = "", session: Any = None, timeout_s: float = 60.0, sleep=time.sleep) -> dict:
    return _request(_session(session), "GET", url, api_key=_key(key), timeout_s=timeout_s, sleep=sleep)


def run(model_path: str, inputs: dict, *, key: str = "", session: Any = None, max_polls: int = 60,
        poll_s: float = 2.0, timeout_s: float = 120.0, sleep=time.sleep) -> str:
    """Run a prediction to completion and return its (first) output URL."""
    sess = _session(session)
    payload = submit(model_path, inputs, key=key, session=sess, wait=True, timeout_s=timeout_s, sleep=sleep)
    status = str(payload.get("status") or "")
    get_url = str((payload.get("urls") or {}).get("get") or "")
    polls = 0
    while status not in ("succeeded", "failed", "canceled"):
        if polls >= max_polls or not get_url:
            raise ProviderCallError(f"replicate {model_path} did not finish in time", kind="transient",
                                    retryable=True)
        polls += 1
        sleep(poll_s)
        payload = get(get_url, key=key, session=sess, timeout_s=timeout_s, sleep=sleep)
        status = str(payload.get("status") or "")
    if status != "succeeded":
        raise ProviderCallError(f"replicate {model_path} {status}: {payload.get('error') or ''}", kind="provider")
    url = _first_output(payload.get("output"))
    if not url:
        raise ProviderCallError(f"replicate {model_path} succeeded with no output", kind="provider")
    return url


def download(url: str, out_path: str, *, session: Any = None, timeout_s: float = 120.0) -> str:
    """Save a Replicate output URL to ``out_path`` (Replicate delivery URLs need no auth)."""
    resp = _session(session).request("GET", url, timeout=timeout_s)
    status = getattr(resp, "status_code", 200)
    if not 200 <= status < 300:
        raise ProviderCallError(f"replicate output download failed ({status})", kind="transient", retryable=True)
    with open(out_path, "wb") as fh:
        fh.write(resp.content)
    return out_path


__all__ = ["TOKEN_ENV", "api_key", "download", "get", "is_enabled", "run", "submit"]
