"""MiniMax (Hailuo) video generation — a REAL adapter over MiniMax's REST API.

A fifth real cloud backend with a distinctive **two-step completion**: the poll
returns a ``file_id`` once status is ``Success``, then a *separate* file-retrieve
call resolves the actual ``download_url``. Imports ``requests``; runs live with a
real ``MINIMAX_API_KEY`` (Bearer). MiniMax also wraps every response in a
``base_resp`` envelope with its own status code — handled here.

Real flow:
  1. **submit**  ``POST /v1/video_generation`` (Bearer) → ``{task_id, base_resp}``.
  2. **poll**    ``GET /v1/query/video_generation?task_id=…`` →
                 ``{status: Queueing|Preparing|Processing|Success|Fail, file_id}``.
  3. **resolve** ``GET /v1/files/retrieve?file_id=…`` → ``{file:{download_url}}``.
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

_BASE = "https://api.minimaxi.chat/v1"

MINIMAX_MODELS = {
    "hailuo-02": "MiniMax-Hailuo-02",
    "hailuo-live": "I2V-01-live",
    "hailuo-director": "T2V-01-Director",
}
_PRICE_MICROS_PER_SECOND = {
    "hailuo-02": 81_700,  # QM1.1: $0.49 per 1080P 6 s video (MiniMax pay-as-you-go, 2026-09-30)
    "hailuo-live": 300_000,
    "hailuo-director": 300_000,
}

_ACTIVE = {"queueing", "preparing", "processing"}


@dataclass
class MinimaxTask:
    task_id: str
    status: str = "Queueing"
    file_id: str = ""
    output_url: str = ""
    failure: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.status in ("Success", "Fail")


class MinimaxAdapter:
    provider_key = "minimax"

    def __init__(
        self,
        *,
        api_key: str = "",
        model: str = "hailuo-02",
        session: Any = None,
        timeout_s: float = 60.0,
        max_retries: int = 4,
        sleep=time.sleep,
    ) -> None:
        self._api_key = api_key or os.getenv("MINIMAX_API_KEY", "")
        if model not in MINIMAX_MODELS:
            raise ProviderCallError(
                f"unknown MiniMax model {model!r}", kind="validation"
            )
        self._model_key = model
        self._model = MINIMAX_MODELS[model]
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
            raise ProviderCallError("MINIMAX_API_KEY not configured", kind="auth")
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
                    f"minimax network error: {exc}",
                    kind="transient",
                    retryable=True,
                    acceptance=(
                        ACCEPTANCE_UNKNOWN if is_submit else ACCEPTANCE_DEFINITE_NO
                    ),
                ) from exc
            status = resp.status_code
            body = self._json(resp)
            if 200 <= status < 300:
                # MiniMax puts a logical status inside base_resp even on HTTP 200.
                self._check_base_resp(body)
                return body
            if status in (401, 403):
                raise ProviderCallError(
                    f"minimax auth failed (HTTP {status})", kind="auth", status=status
                )
            if status in (400, 422):
                raise ProviderCallError(
                    f"minimax rejected request (HTTP {status})",
                    kind="validation",
                    status=status,
                )
            if status == 429:
                if attempt <= self._max_retries:
                    self._sleep(min(30.0, 2**attempt))
                    continue
                raise ProviderCallError(
                    "minimax rate limit", kind="rate_limit", retryable=True, status=429
                )
            if status == 408 or status >= 500:
                if not is_submit and attempt <= self._max_retries:
                    self._sleep(min(20.0, 2 ** (attempt - 1)))
                    continue
                raise ProviderCallError(
                    f"minimax server error (HTTP {status})",
                    kind="transient",
                    retryable=True,
                    status=status,
                    acceptance=(
                        ACCEPTANCE_UNKNOWN if is_submit else ACCEPTANCE_DEFINITE_NO
                    ),
                )
            raise ProviderCallError(
                f"minimax unexpected status {status}", kind="provider", status=status
            )

    @staticmethod
    def _check_base_resp(body: dict) -> None:
        base = (body or {}).get("base_resp") or {}
        code = base.get("status_code")
        if code in (None, 0):
            return
        msg = str(base.get("status_msg") or f"base_resp {code}")
        # 1002/1039 rate-limit, 1004 auth, 2013 invalid params (per MiniMax docs).
        if code in (1004,):
            raise ProviderCallError(f"minimax auth: {msg}", kind="auth")
        if code in (1002, 1039):
            raise ProviderCallError(
                f"minimax rate limit: {msg}", kind="rate_limit", retryable=True
            )
        if code in (2013,):
            raise ProviderCallError(f"minimax invalid params: {msg}", kind="validation")
        raise ProviderCallError(f"minimax error {code}: {msg}", kind="provider")

    @staticmethod
    def _json(resp) -> dict:
        try:
            body = resp.json()
        except Exception:
            return {}
        return body if isinstance(body, dict) else {"data": body}

    def submit(
        self,
        *,
        prompt: str,
        seconds: int = 6,
        resolution: str = "1080P",
        image_url: str = "",
    ) -> MinimaxTask:
        if not prompt and not image_url:
            raise ProviderCallError("a prompt or image is required", kind="validation")
        body: dict = {
            "model": self._model,
            "prompt": prompt,
            "duration": int(seconds),
            "resolution": resolution,
        }
        if image_url:
            body["first_frame_image"] = image_url
        payload = self._call("POST", f"{_BASE}/video_generation", json=body)
        tid = str(payload.get("task_id") or "")
        if not tid:
            raise ProviderCallError(
                f"minimax submit returned no task_id: {payload}",
                kind="provider",
                acceptance=ACCEPTANCE_UNKNOWN,
            )
        return MinimaxTask(task_id=tid)

    def poll(self, task: MinimaxTask) -> MinimaxTask:
        if task.is_terminal:
            return task
        payload = self._call(
            "GET", f"{_BASE}/query/video_generation?task_id={task.task_id}"
        )
        task.raw = payload
        task.status = str(payload.get("status") or task.status)
        if task.status == "Success":
            task.file_id = str(payload.get("file_id") or "")
            if not task.file_id:
                raise ProviderCallError(
                    f"minimax success but no file_id: {payload}", kind="provider"
                )
            task.output_url = self._retrieve_download_url(task.file_id)
        elif task.status == "Fail":
            task.failure = str(
                payload.get("base_resp", {}).get("status_msg")
                or "minimax generation failed"
            )
        return task

    def _retrieve_download_url(self, file_id: str) -> str:
        payload = self._call("GET", f"{_BASE}/files/retrieve?file_id={file_id}")
        file_obj = payload.get("file") or {}
        url = str(
            file_obj.get("download_url") or file_obj.get("backup_download_url") or ""
        )
        if not url:
            raise ProviderCallError(
                f"minimax file has no download_url: {payload}", kind="provider"
            )
        return url

    def cost_micros(self, seconds: int) -> int:
        return int(max(1, int(seconds))) * _PRICE_MICROS_PER_SECOND[self._model_key]
