"""Veo video generation — a REAL adapter over Google's Generative Language API.

A third real cloud backend on yet another protocol: Google's **long-running
operation** (LRO) pattern with **API-key query-param auth** (distinct from fal's
``Key`` header and Runway's ``Bearer`` + version header). Imports ``requests``;
runs live with a real ``GEMINI_API_KEY``.

Real flow:
  1. **submit**  ``POST /v1beta/models/{model}:predictLongRunning?key=…``
                 body ``{instances:[{prompt}], parameters:{aspectRatio, durationSeconds}}``
                 → ``{"name": "models/veo-3.1/operations/…"}`` (an operation handle).
  2. **poll**    ``GET /v1beta/{operation_name}?key=…`` → ``{done: bool, response:{…}}``.
  3. result URI at ``response.generateVideoResponse.generatedSamples[0].video.uri``.

Real Google error shape (``{error:{code,message,status}}``) mapped to the shared
error taxonomy. The ``requests.Session`` is injectable for tests.
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

_BASE = "https://generativelanguage.googleapis.com/v1beta"

VEO_MODELS = {
    "veo-3.1": "veo-3.1-generate-preview",
    "veo-3.1-lite": "veo-3.1-fast-generate-preview",
}
_PRICE_MICROS_PER_SECOND = {"veo-3.1": 400_000, "veo-3.1-lite": 150_000}


@dataclass
class VeoOperation:
    name: str  # "models/veo-3.1/operations/…"
    done: bool = False
    output_url: str = ""
    error: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.done


class VeoAdapter:
    provider_key = "veo"

    def __init__(
        self,
        *,
        api_key: str = "",
        model: str = "veo-3.1",
        session: Any = None,
        timeout_s: float = 60.0,
        max_retries: int = 4,
        sleep=time.sleep,
    ) -> None:
        self._api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        if model not in VEO_MODELS:
            raise ProviderCallError(f"unknown Veo model {model!r}", kind="validation")
        self._model_key = model
        self._model = VEO_MODELS[model]
        self._session = session
        self._timeout = timeout_s
        self._max_retries = max_retries
        self._sleep = sleep

    def _sess(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
        return self._session

    def _key(self) -> str:
        if not self._api_key:
            raise ProviderCallError("GEMINI_API_KEY not configured", kind="auth")
        return self._api_key

    def _call(self, method: str, url: str, *, json: dict | None = None) -> dict:
        import requests

        is_submit = method.upper() == "POST"
        # API key is a query param (Google style), not a header.
        sep = "&" if "?" in url else "?"
        full = f"{url}{sep}key={self._key()}"
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self._sess().request(
                    method,
                    full,
                    headers={"Content-Type": "application/json"},
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
                    f"veo network error: {exc}",
                    kind="transient",
                    retryable=True,
                    acceptance=(
                        ACCEPTANCE_UNKNOWN if is_submit else ACCEPTANCE_DEFINITE_NO
                    ),
                ) from exc
            status = resp.status_code
            body = self._json(resp)
            if 200 <= status < 300:
                return body
            # Google errors carry {error:{code,message,status}}.
            gerr = (body.get("error") or {}) if isinstance(body, dict) else {}
            msg = str(gerr.get("message") or f"HTTP {status}")
            if status in (401, 403):
                raise ProviderCallError(
                    f"veo auth failed: {msg}", kind="auth", status=status
                )
            if status == 400:
                raise ProviderCallError(
                    f"veo rejected request: {msg}", kind="validation", status=400
                )
            if status == 429:
                if attempt <= self._max_retries:
                    self._sleep(min(30.0, 2**attempt))
                    continue
                raise ProviderCallError(
                    "veo rate limit (quota)",
                    kind="rate_limit",
                    retryable=True,
                    status=429,
                )
            if status == 408 or status >= 500:
                if not is_submit and attempt <= self._max_retries:
                    self._sleep(min(20.0, 2 ** (attempt - 1)))
                    continue
                raise ProviderCallError(
                    f"veo server error: {msg}",
                    kind="transient",
                    retryable=True,
                    status=status,
                    acceptance=(
                        ACCEPTANCE_UNKNOWN if is_submit else ACCEPTANCE_DEFINITE_NO
                    ),
                )
            raise ProviderCallError(
                f"veo unexpected status {status}: {msg}", kind="provider", status=status
            )

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
        seconds: int = 8,
        aspect_ratio: str = "9:16",
        image_url: str = "",
    ) -> VeoOperation:
        if not prompt and not image_url:
            raise ProviderCallError("a prompt or image is required", kind="validation")
        instance: dict = {"prompt": prompt}
        if image_url:
            instance["image"] = {"imageUri": image_url}
        body = {
            "instances": [instance],
            "parameters": {
                "aspectRatio": aspect_ratio,
                "durationSeconds": int(seconds),
            },
        }
        payload = self._call(
            "POST", f"{_BASE}/models/{self._model}:predictLongRunning", json=body
        )
        name = str(payload.get("name") or "")
        if not name:
            raise ProviderCallError(
                f"veo submit returned no operation name: {payload}",
                kind="provider",
                acceptance=ACCEPTANCE_UNKNOWN,
            )
        return VeoOperation(name=name)

    def poll(self, op: VeoOperation) -> VeoOperation:
        if op.is_terminal:
            return op
        payload = self._call("GET", f"{_BASE}/{op.name}")
        op.raw = payload
        op.done = bool(payload.get("done", False))
        if op.done:
            if "error" in payload:
                op.error = str((payload["error"] or {}).get("message") or "veo failed")
                return op
            op.output_url = self._extract_uri(payload.get("response") or {})
            if not op.output_url:
                raise ProviderCallError(
                    f"veo done but no video uri: {payload}", kind="provider"
                )
        return op

    @staticmethod
    def _extract_uri(response: dict) -> str:
        gvr = response.get("generateVideoResponse") or {}
        samples = gvr.get("generatedSamples") or gvr.get("samples") or []
        if isinstance(samples, list) and samples:
            video = (samples[0] or {}).get("video") or {}
            return str(video.get("uri") or video.get("url") or "")
        return ""

    def cost_micros(self, seconds: int) -> int:
        return int(max(1, int(seconds))) * _PRICE_MICROS_PER_SECOND[self._model_key]
