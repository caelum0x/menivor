"""Pixelle managed-API B-roll provider (single-clip t2v/image->video).

Drives the in-process **Pixelle generation capability** (Apache-2.0) and implements
the :class:`~app.domains.broll.providers.base.BrollGenProvider` Protocol
(``name = "pixelle"``), so it is interchangeable with the comfyui-deploy provider
at the registry level — exactly like HeyGen <-> LatentSync on the avatar side.

Contract (verified against ``api/routers/clip.py`` + ``api/routers/tasks.py``):

1. **Create run** — ``POST {base_url}/api/clip/generate/async`` with JSON body
   ``{prompt, image_url?, model, duration, aspect_ratio, negative_prompt?, seed?}``.
   Response: ``{"task_id": str}``. ``image_url`` set -> image->video; omitted -> t2v.
2. **Poll** — ``GET {base_url}/api/tasks/{task_id}`` until ``status`` is terminal
   (``completed`` | ``failed`` | ``cancelled``). On ``completed`` the body carries
   ``result: {video_url, duration, file_size}``.
3. Download the ``video_url`` to a local temp mp4 and return
   ``{'clip_path','duration','provider_job_id'}`` (+ best-effort ``clip_url``). The
   job-scoped R2 re-host is the *service* layer's job, so this provider stays
   job-agnostic.

The heavy generation stack runs in the dedicated ``generation`` Celery queue.
The compatibility client can still use a configured legacy base URL while
deployments migrate. All external I/O is wrapped so failures return
``None`` rather than crashing the pipeline (a B-roll failure never fails a reel).
"""

from __future__ import annotations

import os
import uuid

import requests
from loguru import logger

from app.config import config
from app.domains.broll.providers.base import register_broll_provider

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DEFAULT_TIMEOUT_S: float = 600.0  # managed clips are fast (30-120s); cap at 10 min
_DOWNLOAD_TIMEOUT_S: int = 300

_MODE_T2V = "t2v"
_MODE_I2V = "i2v"

_DEFAULT_MODEL = "kling-v3"


def _pixelle_config() -> dict:
    """Return the ``[pixelle]`` config section defensively (never raises)."""
    section = getattr(config, "pixelle", None)
    if section is None:
        return {}
    try:
        return dict(section)
    except Exception:  # noqa: BLE001 - non-mapping guard
        return {}


def _aspect_ratio(width: int, height: int) -> str:
    """Map pixel dims to a managed-provider aspect ratio string."""
    if height > width:
        return "9:16"
    if width > height:
        return "16:9"
    return "1:1"


class PixelleProvider:
    """``BrollGenProvider`` backed by the Pixelle-Video managed-API sidecar."""

    name: str = "pixelle"

    def __init__(self) -> None:
        cfg = _pixelle_config()
        self._model: str = str(cfg.get("model", "") or _DEFAULT_MODEL)
        self._timeout_s: float = float(
            cfg.get("timeout_s", _DEFAULT_TIMEOUT_S) or _DEFAULT_TIMEOUT_S
        )

    def is_enabled(self) -> bool:
        # VideoClient reads provider credentials from its environment/config.
        # ``enabled`` permits an explicit operational kill switch.
        return bool(_pixelle_config().get("enabled", True))

    def list_workflows(self) -> list[dict]:
        """Pixelle exposes no per-key motion catalog here; presets live in ReelForge."""
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
        """Generate one managed AI motion clip; returns the result dict or ``None``.

        ``workflow_id`` selects the managed model (falls back to the config default).
        ``mode='i2v'`` requires ``image_url``. Returns
        ``{'clip_path','duration','provider_job_id','clip_url'}`` or ``None`` on
        any failure/timeout.
        """
        prompt = (prompt or "").strip()
        if not self.is_enabled():
            logger.error("pixelle provider is disabled")
            return None
        if not prompt:
            logger.error("pixelle generate_clip requires a non-empty prompt")
            return None
        if mode == _MODE_I2V and not image_url:
            logger.error("pixelle i2v generation requires an image_url")
            return None

        from app.domains.broll.workflows import approved_workflow_ids

        requested_model = (workflow_id or "").strip()
        model = (
            requested_model
            if requested_model in approved_workflow_ids(self.name)
            else self._model
        )
        if requested_model and requested_model != model:
            logger.warning("ignored unapproved pixelle model selector")
        return self._generate_in_process(
            prompt=prompt,
            image_url=image_url,
            model=model,
            duration=max(1, int(round(duration_s))),
            aspect_ratio=_aspect_ratio(int(width), int(height)),
            seed=seed,
            extra_inputs=extra_inputs,
            correlation_id=correlation_id,
        )

    # -- internals ----------------------------------------------------------
    def _generate_in_process(self, **params: object) -> dict | None:
        """Invoke the licensed provider client directly in the GPU worker.

        This deliberately has no FastAPI-to-FastAPI hop: Celery dispatches the
        product job to the ``generation`` queue and this provider owns the
        engine call in that worker process.
        """
        from pathlib import Path

        from app.bootstrap import (
            RUNTIME_ROOT,
            configure_engine_imports,
            ensure_runtime_directories,
        )

        configure_engine_imports()
        from reelforge_engine import GenerationMode, GenerationRequest, get_pipeline

        ensure_runtime_directories()
        run_id = uuid.uuid4().hex
        clip_dir = RUNTIME_ROOT / "output" / "clips"
        clip_dir.mkdir(parents=True, exist_ok=True)
        image_path = None
        try:
            aspect_ratio = str(params["aspect_ratio"])
            width, height = {
                "9:16": (1080, 1920),
                "16:9": (1920, 1080),
                "1:1": (1080, 1080),
            }.get(aspect_ratio, (1080, 1920))
            image_url = str(params.get("image_url") or "")
            if image_url:
                image_path = str(clip_dir / f"{run_id}_ref")
                self._download_url(image_url, image_path)
            save_path = str(clip_dir / f"{run_id}.mp4")
            result = get_pipeline("managed-video").generate(
                GenerationRequest(
                    prompt=str(params["prompt"]),
                    mode=GenerationMode.IMAGE_TO_VIDEO
                    if image_path
                    else GenerationMode.TEXT_TO_VIDEO,
                    model=str(params["model"]),
                    output_path=Path(save_path),
                    width=width,
                    height=height,
                    duration_seconds=int(params["duration"]),
                    correlation_id=str(params.get("correlation_id") or run_id),
                    reference_image_path=Path(image_path) if image_path else None,
                    seed=params.get("seed"),
                    parameters=params.get("extra_inputs") or {},
                )
            )
            return {
                "clip_path": str(result.output_path),
                "duration": result.duration_seconds,
                "provider_job_id": result.provider_run_id,
            }
        except Exception as exc:  # noqa: BLE001 - provider failure must not crash callers
            logger.error(f"in-process pixelle clip failed: {exc}")
            return None
        finally:
            if image_path:
                try:
                    os.remove(image_path)
                except OSError:
                    pass

    @staticmethod
    def _download_url(url: str, destination: str) -> None:
        """Download an i2v reference into the backend runtime volume."""
        response = requests.get(url, stream=True, timeout=_DOWNLOAD_TIMEOUT_S)
        response.raise_for_status()
        with open(destination, "wb") as fh:
            for chunk in response.iter_content(chunk_size=1 << 16):
                if chunk:
                    fh.write(chunk)


# Self-register at import so ``get_broll_provider('pixelle')`` resolves.
register_broll_provider(PixelleProvider())
