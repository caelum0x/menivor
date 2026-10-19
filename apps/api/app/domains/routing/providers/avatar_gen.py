"""HeyGen talking-head avatar — a REAL media-stack adapter (async, video output).

The gateway's **avatar** backend, served under the ``video`` modality. Async like
Suno music and the video providers: submit a script → get a ``video_id`` → poll
``video_status.get`` until HeyGen's ``video_url`` is ready. Imports ``requests``;
runs live with a real ``HEYGEN_API_KEY`` (``X-Api-Key``). HeyGen hosts the output
itself, so ``poll`` returns a provider ``video_url`` directly (no re-hosting) —
the same ``output_url`` shape as Suno's ``audioUrl``.

Real flow:
  1. **submit**  ``POST /v2/video/generate`` (X-Api-Key) → ``{data:{video_id}}``.
  2. **poll**    ``GET /v1/video_status.get?video_id=…`` →
                 ``{data:{status, video_url}}``.
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

_BASE = "https://api.heygen.com"

# HeyGen terminal states.
_SUCCESS = "completed"
_FAILED = {"failed", "error"}


@dataclass
class HeyGenTask:
    task_id: str
    status: str = "pending"
    output_url: str = ""
    failure: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.status == _SUCCESS or self.status in _FAILED


class HeyGenAvatarAdapter:
    provider_key = "heygen"

    def __init__(
        self,
        *,
        api_key: str = "",
        model: str = "",
        base_url: str | None = None,
        session: Any = None,
        timeout_s: float = 60.0,
        max_retries: int = 4,
        sleep=time.sleep,
    ) -> None:
        self._api_key = api_key or os.getenv("HEYGEN_API_KEY", "")
        self._model = model  # HeyGen avatar id / template
        self._base_url = (base_url or os.getenv("HEYGEN_BASE_URL", _BASE)).rstrip("/")
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
            raise ProviderCallError("HEYGEN_API_KEY not configured", kind="auth")
        return {"X-Api-Key": self._api_key, "Content-Type": "application/json"}

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
                    f"heygen network error: {exc}",
                    kind="transient",
                    retryable=True,
                    acceptance=ACCEPTANCE_UNKNOWN if is_submit else ACCEPTANCE_DEFINITE_NO,
                ) from exc
            status = resp.status_code
            body = self._json(resp)
            if 200 <= status < 300:
                self._check_error(body)
                return body
            if status in (401, 403):
                raise ProviderCallError(
                    f"heygen auth failed (HTTP {status})", kind="auth", status=status
                )
            if status in (400, 422):
                raise ProviderCallError(
                    f"heygen rejected request (HTTP {status})",
                    kind="validation",
                    status=status,
                )
            if status == 429:
                if attempt <= self._max_retries:
                    self._sleep(min(30.0, 2**attempt))
                    continue
                raise ProviderCallError(
                    "heygen rate limit", kind="rate_limit", retryable=True, status=429
                )
            if status == 408 or status >= 500:
                if not is_submit and attempt <= self._max_retries:
                    self._sleep(min(20.0, 2 ** (attempt - 1)))
                    continue
                raise ProviderCallError(
                    f"heygen server error (HTTP {status})",
                    kind="transient",
                    retryable=True,
                    status=status,
                    acceptance=ACCEPTANCE_UNKNOWN if is_submit else ACCEPTANCE_DEFINITE_NO,
                )
            raise ProviderCallError(
                f"heygen unexpected status {status}", kind="provider", status=status
            )

    @staticmethod
    def _check_error(body: dict) -> None:
        # HeyGen wraps responses in {code/error, data}; a non-null ``error`` (or a
        # non-zero ``code``) signals a logical failure even on HTTP 200.
        err = (body or {}).get("error")
        if err:
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise ProviderCallError(f"heygen error: {msg}", kind="provider")

    @staticmethod
    def _json(resp) -> dict:
        try:
            body = resp.json()
        except Exception:
            return {}
        return body if isinstance(body, dict) else {"data": body}

    @staticmethod
    def _data(body: dict) -> dict:
        data = body.get("data")
        return data if isinstance(data, dict) else body

    def submit(
        self,
        *,
        prompt: str,
        voice_id: str = "",
        image_url: str = "",
        seconds: int = 0,
    ) -> HeyGenTask:
        text = str(prompt or "")
        if not text:
            raise ProviderCallError("a prompt (script) is required", kind="validation")
        # Minimal, valid HeyGen v2 body: one avatar scene speaking the script. The
        # avatar id comes from the catalog ``model_ref``; ``voice_id`` is optional.
        character: dict[str, Any] = {"type": "avatar", "avatar_id": self._model}
        if image_url:
            character = {"type": "talking_photo", "talking_photo_url": image_url}
        voice: dict[str, Any] = {"type": "text", "input_text": text}
        if voice_id:
            voice["voice_id"] = voice_id
        body = {"video_inputs": [{"character": character, "voice": voice}]}
        payload = self._call("POST", f"{self._base_url}/v2/video/generate", json=body)
        data = self._data(payload)
        vid = str(data.get("video_id") or data.get("id") or "")
        if not vid:
            raise ProviderCallError(
                f"heygen submit returned no video_id: {payload}",
                kind="provider",
                acceptance=ACCEPTANCE_UNKNOWN,
            )
        return HeyGenTask(task_id=vid)

    def poll(self, task: HeyGenTask) -> HeyGenTask:
        if task.is_terminal:
            return task
        payload = self._call(
            "GET", f"{self._base_url}/v1/video_status.get?video_id={task.task_id}"
        )
        data = self._data(payload)
        task.raw = payload
        task.status = str(data.get("status") or task.status).lower()
        if task.status == _SUCCESS:
            task.output_url = str(data.get("video_url") or "")
            if not task.output_url:
                raise ProviderCallError(
                    f"heygen success but no video_url: {payload}", kind="provider"
                )
        elif task.status in _FAILED:
            err = data.get("error")
            task.failure = (
                (err.get("message") if isinstance(err, dict) else str(err))
                or task.status
            )
        return task
