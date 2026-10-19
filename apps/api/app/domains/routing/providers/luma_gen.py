"""Luma Dream Machine video generation — a REAL adapter over Luma's REST API.

A fourth real cloud backend. Imports ``requests``; runs live with a real
``LUMAAI_API_KEY``. Bearer auth (like Runway) but Luma's own generation/state
protocol (distinct from Runway's task states and Veo's LRO).

Real flow:
  1. **submit**  ``POST /dream-machine/v1/generations`` (Bearer)
                 body ``{prompt, model, resolution, duration, aspect_ratio}``
                 → ``{"id": "...", "state": "queued"}``.
  2. **poll**    ``GET /dream-machine/v1/generations/{id}`` →
                 ``{state: queued|dreaming|completed|failed, assets:{video}, failure_reason}``.

Error taxonomy shared with the other adapters. ``requests.Session`` injectable.
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

_BASE = "https://api.lumalabs.ai/dream-machine/v1"

LUMA_MODELS = {"ray-2": "ray-2", "ray-flash-2": "ray-flash-2", "ray-1.6": "ray-1-6"}
_PRICE_MICROS_PER_SECOND = {
    "ray-2": 320_000,
    "ray-flash-2": 120_000,
    "ray-1.6": 200_000,
}

_ACTIVE = {"queued", "dreaming", "pending", "processing"}


@dataclass
class LumaGeneration:
    generation_id: str
    state: str = "queued"
    output_url: str = ""
    failure: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.state in ("completed", "failed")


class LumaAdapter:
    provider_key = "luma"

    def __init__(
        self,
        *,
        api_key: str = "",
        model: str = "ray-2",
        session: Any = None,
        timeout_s: float = 60.0,
        max_retries: int = 4,
        sleep=time.sleep,
    ) -> None:
        self._api_key = api_key or os.getenv("LUMAAI_API_KEY", "")
        if model not in LUMA_MODELS:
            raise ProviderCallError(f"unknown Luma model {model!r}", kind="validation")
        self._model_key = model
        self._model = LUMA_MODELS[model]
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
            raise ProviderCallError("LUMAAI_API_KEY not configured", kind="auth")
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
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
                    f"luma network error: {exc}",
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
            msg = self._err_msg(body, status)
            if status in (401, 403):
                raise ProviderCallError(
                    f"luma auth failed: {msg}", kind="auth", status=status
                )
            if status in (400, 422):
                raise ProviderCallError(
                    f"luma rejected request: {msg}", kind="validation", status=status
                )
            if status == 429:
                if attempt <= self._max_retries:
                    self._sleep(min(30.0, 2**attempt))
                    continue
                raise ProviderCallError(
                    "luma rate limit", kind="rate_limit", retryable=True, status=429
                )
            if status == 408 or status >= 500:
                if not is_submit and attempt <= self._max_retries:
                    self._sleep(min(20.0, 2 ** (attempt - 1)))
                    continue
                raise ProviderCallError(
                    f"luma server error: {msg}",
                    kind="transient",
                    retryable=True,
                    status=status,
                    acceptance=(
                        ACCEPTANCE_UNKNOWN if is_submit else ACCEPTANCE_DEFINITE_NO
                    ),
                )
            raise ProviderCallError(
                f"luma unexpected status {status}: {msg}",
                kind="provider",
                status=status,
            )

    @staticmethod
    def _json(resp) -> dict:
        try:
            body = resp.json()
        except Exception:
            return {}
        return body if isinstance(body, dict) else {"data": body}

    @staticmethod
    def _err_msg(body: dict, status: int) -> str:
        if isinstance(body, dict):
            for k in ("detail", "message", "error"):
                v = body.get(k)
                if v:
                    return str(v)
        return f"HTTP {status}"

    def submit(
        self,
        *,
        prompt: str,
        seconds: int = 5,
        aspect_ratio: str = "9:16",
        resolution: str = "720p",
        image_url: str = "",
    ) -> LumaGeneration:
        if not prompt and not image_url:
            raise ProviderCallError("a prompt or image is required", kind="validation")
        body: dict = {
            "prompt": prompt,
            "model": self._model,
            "resolution": resolution,
            "duration": f"{int(seconds)}s",
            "aspect_ratio": aspect_ratio,
        }
        if image_url:
            # Luma keyframes: frame0 seeds the first frame (image-to-video).
            body["keyframes"] = {"frame0": {"type": "image", "url": image_url}}
        payload = self._call("POST", f"{_BASE}/generations", json=body)
        gid = str(payload.get("id") or "")
        if not gid:
            raise ProviderCallError(
                f"luma submit returned no id: {payload}",
                kind="provider",
                acceptance=ACCEPTANCE_UNKNOWN,
            )
        return LumaGeneration(
            generation_id=gid, state=str(payload.get("state") or "queued")
        )

    def poll(self, gen: LumaGeneration) -> LumaGeneration:
        if gen.is_terminal:
            return gen
        payload = self._call("GET", f"{_BASE}/generations/{gen.generation_id}")
        gen.raw = payload
        gen.state = str(payload.get("state") or gen.state)
        if gen.state == "completed":
            assets = payload.get("assets") or {}
            gen.output_url = str(assets.get("video") or assets.get("video_url") or "")
            if not gen.output_url:
                raise ProviderCallError(
                    f"luma completed but no video asset: {payload}", kind="provider"
                )
        elif gen.state == "failed":
            gen.failure = str(payload.get("failure_reason") or "luma generation failed")
        elif gen.state not in _ACTIVE:
            # Unknown non-terminal state — treat as still active rather than crashing.
            gen.state = gen.state or "dreaming"
        return gen

    def cancel(self, gen: LumaGeneration) -> bool:
        """Best-effort real cancellation via ``POST /generations/{id}/cancel``.

        Luma exposes an explicit cancel action for an in-flight generation.
        Returns ``True`` when the provider acknowledges (2xx) or the generation
        is already gone (404); ``False`` for a terminal generation or any
        transport/HTTP failure. Never raises.
        """
        if gen.is_terminal:
            return False
        try:
            resp = self._sess().request(
                "POST",
                f"{_BASE}/generations/{gen.generation_id}/cancel",
                headers=self._headers(),
                timeout=self._timeout,
            )
        except Exception:
            return False
        return 200 <= resp.status_code < 300 or resp.status_code == 404

    def cost_micros(self, seconds: int) -> int:
        return int(max(1, int(seconds))) * _PRICE_MICROS_PER_SECOND[self._model_key]
