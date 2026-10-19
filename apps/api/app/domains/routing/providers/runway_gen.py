"""Runway Gen-4 video generation — a REAL adapter over Runway's REST API.

A second real cloud backend for the media gateway, on a genuinely different API
than fal.ai: Runway's developer API (``api.dev.runwayml.com``) uses ``Bearer``
auth + a required ``X-Runway-Version`` header + task polling. Imports ``requests``;
runs live with a real ``RUNWAY_API_SECRET``.

Real flow:
  1. **submit**  ``POST /v1/image_to_video``  headers ``Authorization: Bearer …`` +
                 ``X-Runway-Version: 2024-11-06``; body ``{model, promptImage,
                 promptText, ratio, duration}`` → ``{id}``.
  2. **poll**    ``GET /v1/tasks/{id}`` → ``{status: PENDING|THROTTLED|RUNNING|
                 SUCCEEDED|FAILED, output: [url], failure, failureCode}``.
  3. **download** stream the produced MP4.

Real error taxonomy + retry (auth / validation / throttle / transient), shared
error type with the other adapters via ``KlingError`` (renamed here for clarity
but structurally identical). The ``requests.Session`` is injectable for tests.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

from app.domains.routing.providers.kling_fal import (
    ACCEPTANCE_DEFINITE_NO,
    ACCEPTANCE_UNKNOWN,
    KlingError as ProviderCallError,
)

_BASE = "https://api.dev.runwayml.com"
_RUNWAY_VERSION = "2024-11-06"

RUNWAY_MODELS = {"gen4_turbo": "gen4_turbo", "gen3a_turbo": "gen3a_turbo"}
_PRICE_MICROS_PER_SECOND = 500_000  # Runway Gen-4 ≈ $0.05/credit; ~$0.5/s equiv


@dataclass
class RunwayTask:
    task_id: str
    state: str = "PENDING"  # PENDING | THROTTLED | RUNNING | SUCCEEDED | FAILED
    output_url: str = ""
    failure: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.state in ("SUCCEEDED", "FAILED")


class RunwayAdapter:
    provider_key = "runway"

    def __init__(
        self,
        *,
        api_key: str = "",
        model: str = "gen4_turbo",
        session: Any = None,
        timeout_s: float = 60.0,
        max_retries: int = 4,
        sleep=time.sleep,
    ) -> None:
        self._api_key = api_key or os.getenv("RUNWAY_API_SECRET", "")
        if model not in RUNWAY_MODELS:
            raise ProviderCallError(
                f"unknown Runway model {model!r}", kind="validation"
            )
        self._model = RUNWAY_MODELS[model]
        self._session = session
        self._timeout = timeout_s
        self._max_retries = max_retries
        self._sleep = sleep

    def _sess(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
        return self._session

    def _headers(self) -> dict:
        if not self._api_key:
            raise ProviderCallError("RUNWAY_API_SECRET not configured", kind="auth")
        return {
            "Authorization": f"Bearer {self._api_key}",
            "X-Runway-Version": _RUNWAY_VERSION,
            "Content-Type": "application/json",
        }

    def _call(self, method: str, url: str, *, json: dict | None = None) -> dict:
        import requests

        is_submit = method.upper() == "POST"
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self._sess().request(
                    method,
                    url,
                    headers=self._headers(),
                    json=json,
                    timeout=self._timeout,
                )
            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            ) as exc:
                if not is_submit and attempt <= self._max_retries:
                    self._sleep(min(20.0, 2 ** (attempt - 1)))
                    continue
                raise ProviderCallError(
                    f"runway network error: {exc}",
                    kind="transient",
                    retryable=True,
                    acceptance=(
                        ACCEPTANCE_UNKNOWN if is_submit else ACCEPTANCE_DEFINITE_NO
                    ),
                ) from exc
            status = resp.status_code
            if 200 <= status < 300:
                return self._json(resp)
            if status in (401, 403):
                raise ProviderCallError(
                    f"runway auth failed ({status})", kind="auth", status=status
                )
            if status in (400, 422):
                raise ProviderCallError(
                    f"runway rejected request ({status}): {self._detail(resp)}",
                    kind="validation",
                    status=status,
                )
            if status == 429:
                if attempt <= self._max_retries:
                    self._sleep(min(30.0, 2**attempt))
                    continue
                raise ProviderCallError(
                    "runway rate limit", kind="rate_limit", retryable=True, status=429
                )
            if status == 408 or status >= 500:
                if not is_submit and attempt <= self._max_retries:
                    self._sleep(min(20.0, 2 ** (attempt - 1)))
                    continue
                raise ProviderCallError(
                    f"runway server error {status}",
                    kind="transient",
                    retryable=True,
                    status=status,
                    acceptance=(
                        ACCEPTANCE_UNKNOWN if is_submit else ACCEPTANCE_DEFINITE_NO
                    ),
                )
            raise ProviderCallError(
                f"runway unexpected status {status}", kind="provider", status=status
            )

    @staticmethod
    def _json(resp) -> dict:
        try:
            body = resp.json()
        except Exception as exc:  # pragma: no cover
            raise ProviderCallError(
                f"runway non-JSON body: {exc}", kind="provider"
            ) from exc
        return body if isinstance(body, dict) else {"data": body}

    @staticmethod
    def _detail(resp) -> str:
        try:
            b = resp.json()
            return str(b.get("error") or b.get("message") or b)[:300]
        except Exception:
            return (getattr(resp, "text", "") or "")[:300]

    def submit(
        self,
        *,
        prompt: str = "",
        image_url: str = "",
        seconds: int = 5,
        ratio: str = "768:1280",
    ) -> RunwayTask:
        if not image_url:
            raise ProviderCallError(
                "Runway image_to_video requires an image_url (promptImage)",
                kind="validation",
            )
        body = {
            "model": self._model,
            "promptImage": image_url,
            "promptText": prompt,
            "ratio": ratio,
            "duration": int(seconds),
        }
        payload = self._call("POST", f"{_BASE}/v1/image_to_video", json=body)
        task_id = str(payload.get("id") or "")
        if not task_id:
            raise ProviderCallError(
                f"runway submit returned no id: {payload}",
                kind="provider",
                acceptance=ACCEPTANCE_UNKNOWN,
            )
        return RunwayTask(task_id=task_id)

    def poll(self, task: RunwayTask) -> RunwayTask:
        if task.is_terminal:
            return task
        payload = self._call("GET", f"{_BASE}/v1/tasks/{task.task_id}")
        task.raw = payload
        task.state = str(payload.get("status", "RUNNING") or "RUNNING").upper()
        if task.state == "SUCCEEDED":
            output = payload.get("output") or []
            task.output_url = (
                str(output[0]) if isinstance(output, list) and output else ""
            )
            if not task.output_url:
                raise ProviderCallError(
                    f"runway succeeded but no output: {payload}", kind="provider"
                )
        elif task.state == "FAILED":
            task.failure = str(
                payload.get("failure") or payload.get("failureCode") or "runway failed"
            )
        return task

    def cancel(self, task: RunwayTask) -> bool:
        """Best-effort real cancellation via ``DELETE /v1/tasks/{id}``.

        Runway's developer API cancels (and deletes) a still-running task with a
        DELETE. Returns ``True`` when the provider acknowledges the cancellation
        (2xx) or the task no longer exists (404); ``False`` for a terminal task
        or any transport/HTTP failure. Never raises — a failed cancel must not
        mask the caller's abandon intent.
        """
        if task.is_terminal:
            return False
        try:
            resp = self._sess().request(
                "DELETE",
                f"{_BASE}/v1/tasks/{task.task_id}",
                headers=self._headers(),
                timeout=self._timeout,
            )
        except Exception:
            return False
        return 200 <= resp.status_code < 300 or resp.status_code == 404

    def cost_micros(self, seconds: int) -> int:
        return int(max(1, int(seconds))) * _PRICE_MICROS_PER_SECOND
