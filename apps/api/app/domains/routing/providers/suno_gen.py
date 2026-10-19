"""Suno music generation — a REAL adapter over the Suno API (v1).

The gateway's **audio** backend. Imports ``requests``; runs live with a real
``SUNO_API_KEY`` (Bearer). Async like video: submit a prompt → get a ``taskId`` →
poll ``record-info`` until the clip's ``audioUrl`` is ready. Suno wraps every
response in a ``{code, msg, data}`` envelope whose ``code`` signals logical
success even on HTTP 200 (like MiniMax's ``base_resp``), handled here.

Real flow:
  1. **submit**  ``POST /api/v1/generate`` (Bearer) → ``{code, data:{taskId}}``.
  2. **poll**    ``GET /api/v1/generate/record-info?taskId=…`` →
                 ``{data:{status, response:{sunoData:[{audioUrl}]}}}``.
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

_BASE = "https://api.sunoapi.org"

SUNO_MODELS = {"suno-v4": "V4", "suno-v4.5": "V4_5", "suno-v3.5": "V3_5"}
_PRICE_MICROS = {"suno-v4": 80_000, "suno-v4.5": 100_000, "suno-v3.5": 60_000}

# Suno's terminal states (success + the various failure codes).
_SUCCESS = "SUCCESS"
_FAILED = {
    "CREATE_TASK_FAILED",
    "GENERATE_AUDIO_FAILED",
    "CALLBACK_EXCEPTION",
    "SENSITIVE_WORD_ERROR",
}


@dataclass
class SunoTask:
    task_id: str
    status: str = "PENDING"
    output_url: str = ""
    failure: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.status == _SUCCESS or self.status in _FAILED


class SunoAdapter:
    provider_key = "suno"

    def __init__(
        self,
        *,
        api_key: str = "",
        model: str = "suno-v4",
        session: Any = None,
        timeout_s: float = 60.0,
        max_retries: int = 4,
        sleep=time.sleep,
    ) -> None:
        self._api_key = api_key or os.getenv("SUNO_API_KEY", "")
        if model not in SUNO_MODELS:
            raise ProviderCallError(f"unknown Suno model {model!r}", kind="validation")
        self._model_key = model
        self._model = SUNO_MODELS[model]
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
            raise ProviderCallError("SUNO_API_KEY not configured", kind="auth")
        return {
            "Authorization": f"Bearer {self._api_key}",
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
                    f"suno network error: {exc}",
                    kind="transient",
                    retryable=True,
                    acceptance=(
                        ACCEPTANCE_UNKNOWN if is_submit else ACCEPTANCE_DEFINITE_NO
                    ),
                ) from exc
            status = resp.status_code
            body = self._json(resp)
            if 200 <= status < 300:
                self._check_code(body)
                return body
            if status in (401, 403):
                raise ProviderCallError(
                    f"suno auth failed (HTTP {status})", kind="auth", status=status
                )
            if status in (400, 422):
                raise ProviderCallError(
                    f"suno rejected request (HTTP {status})",
                    kind="validation",
                    status=status,
                )
            if status == 429:
                if attempt <= self._max_retries:
                    self._sleep(min(30.0, 2**attempt))
                    continue
                raise ProviderCallError(
                    "suno rate limit", kind="rate_limit", retryable=True, status=429
                )
            if status == 408 or status >= 500:
                if not is_submit and attempt <= self._max_retries:
                    self._sleep(min(20.0, 2 ** (attempt - 1)))
                    continue
                raise ProviderCallError(
                    f"suno server error (HTTP {status})",
                    kind="transient",
                    retryable=True,
                    status=status,
                    acceptance=(
                        ACCEPTANCE_UNKNOWN if is_submit else ACCEPTANCE_DEFINITE_NO
                    ),
                )
            raise ProviderCallError(
                f"suno unexpected status {status}", kind="provider", status=status
            )

    @staticmethod
    def _check_code(body: dict) -> None:
        code = (body or {}).get("code")
        if code in (None, 200):
            return
        msg = str(body.get("msg") or f"code {code}")
        if code in (401, 403):
            raise ProviderCallError(f"suno auth: {msg}", kind="auth")
        if code in (429,):
            raise ProviderCallError(
                f"suno rate limit: {msg}", kind="rate_limit", retryable=True
            )
        if code in (400, 422, 430):
            raise ProviderCallError(f"suno invalid params: {msg}", kind="validation")
        raise ProviderCallError(f"suno error {code}: {msg}", kind="provider")

    @staticmethod
    def _json(resp) -> dict:
        try:
            body = resp.json()
        except Exception:
            return {}
        return body if isinstance(body, dict) else {"data": body}

    def submit(self, *, prompt: str, instrumental: bool = False) -> SunoTask:
        if not prompt:
            raise ProviderCallError("a prompt is required", kind="validation")
        body = {
            "prompt": prompt,
            "customMode": False,
            "instrumental": bool(instrumental),
            "model": self._model,
            "callBackUrl": "",
        }
        payload = self._call("POST", f"{_BASE}/api/v1/generate", json=body)
        data = payload.get("data") or {}
        tid = str(data.get("taskId") or data.get("task_id") or "")
        if not tid:
            raise ProviderCallError(
                f"suno submit returned no taskId: {payload}",
                kind="provider",
                acceptance=ACCEPTANCE_UNKNOWN,
            )
        return SunoTask(task_id=tid)

    def poll(self, task: SunoTask) -> SunoTask:
        if task.is_terminal:
            return task
        payload = self._call(
            "GET", f"{_BASE}/api/v1/generate/record-info?taskId={task.task_id}"
        )
        data = payload.get("data") or {}
        task.raw = payload
        task.status = str(data.get("status") or task.status)
        if task.status == _SUCCESS:
            task.output_url = self._first_audio_url(data)
            if not task.output_url:
                raise ProviderCallError(
                    f"suno success but no audioUrl: {payload}", kind="provider"
                )
        elif task.status in _FAILED:
            task.failure = str(data.get("errorMessage") or task.status)
        return task

    @staticmethod
    def _first_audio_url(data: dict) -> str:
        response = data.get("response") or {}
        clips = response.get("sunoData") or response.get("data") or []
        if isinstance(clips, list) and clips:
            first = clips[0] or {}
            return str(first.get("audioUrl") or first.get("audio_url") or "")
        return ""

    def cost_micros(self) -> int:
        return _PRICE_MICROS[self._model_key]
