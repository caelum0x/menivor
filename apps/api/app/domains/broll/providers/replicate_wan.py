"""Replicate-hosted Wan 2.2 B-roll provider (t2v / i2v, no self-hosted GPU).

Implements the :class:`~app.domains.broll.providers.base.BrollGenProvider`
Protocol (``name = "replicate"``) on top of the existing, battle-tested
:class:`app.domains.routing.providers.wan_replicate.WanAdapter` — the same
Replicate prediction lifecycle adapter the routing domain uses. This makes the
hosted "no-GPU-needed" Wan tier available to the standalone AI B-roll studio
(``POST /generation/broll/generate``) by setting::

    BROLL_GEN_PROVIDER=replicate
    REPLICATE_API_TOKEN=r8_…            # never logged, never echoed

Model selection (cheapest/fastest official Wan variants by default)::

    REPLICATE_WAN_T2V_MODEL=wan-video/wan-2.2-t2v-fast   # text→video
    REPLICATE_WAN_I2V_MODEL=wan-video/wan-2.2-i2v-fast   # image→video

Cost note: the *-fast Wan 2.2 models render 16 fps clips billed per output
second (~$0.05-0.06/s at time of wiring → ~$0.25-0.30 per 5 s render). Always
pair this provider with a hard spend limit at replicate.com AND the product's
own daily caps (see ``apps/api/DEPLOY.md`` §AI video spend protection).

Contract: like every broll provider, ``generate_clip`` NEVER raises on external
I/O failure — it returns ``None`` so the calling job fails clean (mark-failed +
credit refund) instead of crashing the worker.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

from loguru import logger

from app.domains.broll.providers.base import register_broll_provider

_MODE_T2V = "t2v"
_MODE_I2V = "i2v"

_DEFAULT_T2V_MODEL = "wan-video/wan-2.2-t2v-fast"
_DEFAULT_I2V_MODEL = "wan-video/wan-2.2-i2v-fast"

# Replicate *-fast Wan predictions typically finish in 60-180s; poll gently and
# stop well inside the Celery task's 1800s soft limit.
_POLL_INTERVAL_S: float = 5.0
_DEFAULT_TIMEOUT_S: float = 900.0
_DOWNLOAD_TIMEOUT_S: int = 300


def _t2v_model() -> str:
    return (os.getenv("REPLICATE_WAN_T2V_MODEL") or "").strip() or _DEFAULT_T2V_MODEL


def _i2v_model() -> str:
    return (os.getenv("REPLICATE_WAN_I2V_MODEL") or "").strip() or _DEFAULT_I2V_MODEL


def _aspect_ratio(width: int, height: int) -> str:
    """Map pixel dims to the Wan ``aspect_ratio`` selector."""
    if height > width:
        return "9:16"
    if width > height:
        return "16:9"
    return "1:1"


class ReplicateWanProvider:
    """``BrollGenProvider`` backed by Replicate's hosted Wan 2.2 models."""

    name: str = "replicate"

    def is_enabled(self) -> bool:
        return bool((os.getenv("REPLICATE_API_TOKEN") or "").strip())

    def list_workflows(self) -> list[dict]:
        """No queryable per-key catalog; ReelForge's preset table is the picker."""
        return []

    def generate_clip(
        self,
        prompt: str,
        *,
        mode: str = _MODE_T2V,
        image_url: str | None = None,
        width: int = 1080,
        height: int = 1920,
        duration_s: float = 5.0,
        workflow_id: str | None = None,
        seed: int | None = None,
        extra_inputs: dict | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        correlation_id: str = "",
    ) -> dict | None:
        """Generate one hosted Wan clip; returns the result dict or ``None``.

        Submits a Replicate prediction, polls it to a terminal state, downloads
        the delivered mp4 into the backend runtime volume, and returns
        ``{'clip_path', 'duration', 'provider_job_id'}``. Any failure/timeout is
        logged (never with the token) and surfaces as ``None``.
        """
        prompt = (prompt or "").strip()
        if not self.is_enabled():
            logger.error("replicate broll provider: REPLICATE_API_TOKEN not set")
            return None
        if not prompt:
            logger.error("replicate broll provider requires a non-empty prompt")
            return None
        if mode == _MODE_I2V and not image_url:
            logger.error("replicate broll provider: i2v requires an image_url")
            return None

        model = _i2v_model() if mode == _MODE_I2V else _t2v_model()
        seconds = max(1, int(round(duration_s or 5.0)))

        try:
            from app.domains.routing.providers.wan_replicate import WanAdapter

            adapter = WanAdapter(model=model)
            pred = adapter.submit(
                prompt=prompt,
                seconds=seconds,
                aspect_ratio=_aspect_ratio(int(width), int(height)),
                image_url=image_url or "",
            )
            logger.info(
                f"replicate broll: submitted prediction={pred.prediction_id} "
                f"model={model} correlation_id={correlation_id or 'n/a'}"
            )
            deadline = time.monotonic() + max(60.0, float(timeout_s))
            while not pred.is_terminal:
                if time.monotonic() > deadline:
                    logger.error(
                        f"replicate broll: prediction {pred.prediction_id} timed "
                        f"out after {timeout_s:.0f}s; cancelling"
                    )
                    adapter.cancel(pred)
                    return None
                time.sleep(_POLL_INTERVAL_S)
                pred = adapter.poll(pred)

            if pred.status != "succeeded" or not pred.output_url:
                logger.error(
                    f"replicate broll: prediction {pred.prediction_id} ended "
                    f"{pred.status}: {pred.failure or 'no output'}"
                )
                return None

            clip_path = self._download_clip(pred.output_url)
            duration = self._probe_duration(pred.raw, fallback=float(seconds))
            return {
                "clip_path": clip_path,
                "duration": duration,
                "provider_job_id": pred.prediction_id,
            }
        except Exception as exc:  # noqa: BLE001 - provider failure must not crash callers
            logger.error(f"replicate broll generation failed: {exc}")
            return None

    # -- internals ----------------------------------------------------------
    @staticmethod
    def _download_clip(url: str) -> str:
        """Stream the delivered mp4 into the backend runtime volume."""
        import requests

        from app.bootstrap import RUNTIME_ROOT, ensure_runtime_directories

        ensure_runtime_directories()
        clip_dir = RUNTIME_ROOT / "output" / "clips"
        clip_dir.mkdir(parents=True, exist_ok=True)
        destination = clip_dir / f"replicate_{uuid.uuid4().hex}.mp4"

        response = requests.get(url, stream=True, timeout=_DOWNLOAD_TIMEOUT_S)
        response.raise_for_status()
        with open(destination, "wb") as fh:
            for chunk in response.iter_content(chunk_size=1 << 16):
                if chunk:
                    fh.write(chunk)
        return str(destination)

    @staticmethod
    def _probe_duration(raw: Any, fallback: float) -> float:
        """Best-effort output duration from the prediction input (16 fps Wan)."""
        try:
            frames = int(((raw or {}).get("input") or {}).get("num_frames") or 0)
            if frames > 0:
                return round(frames / 16.0, 2)
        except Exception:  # noqa: BLE001 - metadata is cosmetic
            pass
        return float(fallback)


# Self-register at import so ``get_broll_provider('replicate')`` resolves.
register_broll_provider(ReplicateWanProvider())
