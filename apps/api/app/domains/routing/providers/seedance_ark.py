"""Seedance 2.0 direct from ByteDance via BytePlus ModelArk (provider key ``ark``).

Protocol (async task API, the same one the legacy engine client speaks):

  1. **submit**  ``POST {ARK_BASE_URL}/contents/generations/tasks``
                 (``Authorization: Bearer $ARK_API_KEY``) with
                 ``{"model", "content": [...], "duration", "ratio", "resolution"}``.
                 ``content`` holds one ``{"type": "text", "text": prompt}`` item and one
                 ``{"type": "image_url", "image_url": {"url": ...}, "role": ...}`` item
                 per image, role ``first_frame`` (image-to-video) or
                 ``reference_image`` (reference-to-video). Returns ``{"id": ...}``.
  2. **poll**    ``GET .../contents/generations/tasks/{id}`` until ``status`` is
                 ``succeeded`` (``content.video_url``) or ``failed``/``expired``/``cancelled``.
  3. **cancel**  ``DELETE .../contents/generations/tasks/{id}`` (queued tasks only).

Environment:

* ``ARK_API_KEY``        - the ModelArk API key. Missing: a clean "not configured"
                           auth error (the gateway answers 503), never a crash.
* ``ARK_BASE_URL``       - defaults to the international BytePlus endpoint
                           :data:`DEFAULT_ARK_BASE_URL` (not the mainland China
                           ``ark.cn-beijing.volces.com`` host).
* ``SEEDANCE_ARK_MODEL`` - the ModelArk model id (default :data:`DEFAULT_SEEDANCE_ARK_MODEL`).

Errors reuse the fal adapter's :class:`KlingError` taxonomy so the shared
executor normalizes them the same way. A failed submit that may have reached
the vendor is marked ``acceptance=unknown`` and is never retried blindly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Sequence

from app.domains.routing.providers.kling_fal import (
    ACCEPTANCE_DEFINITE_NO,
    ACCEPTANCE_UNKNOWN,
    KlingError,
)

DEFAULT_ARK_BASE_URL = "https://ark.ap-southeast.bytepluses.com/api/v3"
DEFAULT_SEEDANCE_ARK_MODEL = "dreamina-seedance-2-0-260128"
ROLE_FIRST_FRAME = "first_frame"
ROLE_REFERENCE = "reference_image"
_TASKS_PATH = "/contents/generations/tasks"


def ark_base_url() -> str:
    return (os.getenv("ARK_BASE_URL", "").strip() or DEFAULT_ARK_BASE_URL).rstrip("/")


def seedance_ark_model() -> str:
    return os.getenv("SEEDANCE_ARK_MODEL", "").strip() or DEFAULT_SEEDANCE_ARK_MODEL


def _ark_ratio(aspect_ratio: str) -> str:
    value = str(aspect_ratio or "").strip()
    return value if value in {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9"} else "adaptive"


@dataclass
class ArkTask:
    task_id: str
    status: str = "queued"  # queued | running | succeeded | failed | expired | cancelled
    output_url: str = ""
    failure: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.status in {"succeeded", "failed", "expired", "cancelled"}


class SeedanceArkAdapter:
    """Real ModelArk adapter (``requests``-compatible session is injectable for tests)."""

    provider_key = "ark"

    def __init__(
        self,
        *,
        api_key: str = "",
        model: str = "",
        base_url: str = "",
        session: Any = None,
        timeout_s: float = 60.0,
    ) -> None:
        self._api_key = api_key or os.getenv("ARK_API_KEY", "")
        self._model = model or seedance_ark_model()
        self._base = (base_url or ark_base_url()).rstrip("/")
        self._session = session
        self._timeout = timeout_s

    @property
    def base_url(self) -> str:
        return self._base

    def _sess(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
        return self._session

    def _headers(self) -> dict:
        if not self._api_key:
            raise KlingError("Seedance via BytePlus ModelArk is not configured (ARK_API_KEY is not set)",
                             kind="auth")
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    def _call(self, method: str, url: str, *, json: dict | None = None) -> dict:
        import requests

        headers = self._headers()
        is_submit = method.upper() == "POST"
        maybe = ACCEPTANCE_UNKNOWN if is_submit else ACCEPTANCE_DEFINITE_NO
        try:
            resp = self._sess().request(method, url, headers=headers, json=json, timeout=self._timeout)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            raise KlingError(f"ModelArk transport error: {exc}", kind="transient", retryable=True,
                             acceptance=maybe) from exc
        status = int(getattr(resp, "status_code", 0) or 0)
        if 200 <= status < 300:
            try:
                body = resp.json()
            except Exception:  # noqa: BLE001 - empty body (DELETE) is fine
                body = {}
            return body if isinstance(body, dict) else {"data": body}
        detail = _error_detail(resp)
        if status in (401, 403):
            raise KlingError(f"ModelArk auth failed ({status}); check ARK_API_KEY", kind="auth", status=status)
        if status in (400, 404, 422):
            raise KlingError(f"ModelArk rejected the request ({status}): {detail}",
                             kind="validation" if status != 404 else "not_found", status=status)
        if status == 429:
            raise KlingError("ModelArk rate limit exceeded", kind="rate_limit", retryable=True, status=429)
        if status == 408 or status >= 500:
            raise KlingError(f"ModelArk server error {status}", kind="transient", retryable=True,
                             status=status, acceptance=maybe)
        raise KlingError(f"ModelArk unexpected status {status}: {detail}", kind="provider", status=status)

    @staticmethod
    def build_body(
        *,
        model: str,
        prompt: str,
        image_urls: Sequence[str] = (),
        mode: str = ROLE_FIRST_FRAME,
        seconds: int = 5,
        aspect_ratio: str = "9:16",
        resolution: str = "720p",
    ) -> dict:
        """The task body: a text item plus one image item per URL with its role."""
        content: list[dict] = []
        if prompt:
            content.append({"type": "text", "text": prompt})
        urls = [u for u in image_urls if u]
        if mode == ROLE_FIRST_FRAME:
            urls = urls[:1]
        for url in urls:
            content.append({"type": "image_url", "image_url": {"url": url}, "role": mode})
        return {
            "model": model,
            "content": content,
            "duration": int(seconds),
            "ratio": _ark_ratio(aspect_ratio),
            "resolution": resolution or "720p",
        }

    def submit(
        self,
        *,
        prompt: str,
        image_urls: Sequence[str] = (),
        mode: str = ROLE_FIRST_FRAME,
        seconds: int = 5,
        aspect_ratio: str = "9:16",
        resolution: str = "720p",
    ) -> ArkTask:
        if mode not in (ROLE_FIRST_FRAME, ROLE_REFERENCE):
            raise KlingError(f"unknown ModelArk image role {mode!r}", kind="validation")
        if not prompt and not any(image_urls):
            raise KlingError("a prompt or an image is required", kind="validation")
        body = self.build_body(model=self._model, prompt=prompt, image_urls=image_urls, mode=mode,
                               seconds=seconds, aspect_ratio=aspect_ratio, resolution=resolution)
        data = self._call("POST", f"{self._base}{_TASKS_PATH}", json=body)
        task_id = str(data.get("id") or "")
        if not task_id:
            raise KlingError(f"ModelArk submit returned no task id: {str(data)[:200]}", kind="provider",
                             acceptance=ACCEPTANCE_UNKNOWN)
        return ArkTask(task_id=task_id)

    def poll(self, task: ArkTask) -> ArkTask:
        if task.is_terminal:
            return task
        data = self._call("GET", f"{self._base}{_TASKS_PATH}/{task.task_id}")
        status = str(data.get("status") or "running").lower()
        if status == "canceled":
            status = "cancelled"
        task.status = status if status in {"queued", "running", "succeeded", "failed", "expired",
                                           "cancelled"} else "running"
        if task.status == "succeeded":
            content = data.get("content") if isinstance(data.get("content"), dict) else {}
            task.output_url = str(content.get("video_url") or data.get("video_url") or "")
            if not task.output_url:
                raise KlingError("ModelArk task succeeded without a video url", kind="provider")
        elif task.status in {"failed", "expired", "cancelled"}:
            error = data.get("error") if isinstance(data.get("error"), dict) else {}
            task.failure = str(error.get("message") or data.get("status_msg")
                               or f"ModelArk generation {task.status}")
        return task

    def cancel(self, task: ArkTask) -> bool:
        try:
            self._call("DELETE", f"{self._base}{_TASKS_PATH}/{task.task_id}")
            return True
        except KlingError:
            return False


def _error_detail(resp: Any) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                return str(err.get("message") or err)[:300]
            return str(body)[:300]
    except Exception:  # noqa: BLE001
        pass
    return str(getattr(resp, "text", "") or "")[:300]


__all__ = [
    "ArkTask", "DEFAULT_ARK_BASE_URL", "DEFAULT_SEEDANCE_ARK_MODEL", "ROLE_FIRST_FRAME", "ROLE_REFERENCE",
    "SeedanceArkAdapter", "ark_base_url", "seedance_ark_model",
]
