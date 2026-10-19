"""Upscale and smooth workers (MH7). Image jobs run on the CPU sidecar; video jobs call the APIs.

A failed image job costs nothing (it was never charged); a failed video job
gives its AI-video credits back once. Seconds taken are stored on the job so
the 1080p "under 20 s" target is measured on every run.
"""

from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Callable

from loguru import logger

from app.workers.celery_app import celery_app

from . import esrgan_cpu, rife, seedvr_api, service
from .errors import EnhanceError

IMAGE_TASK = "app.services.enhance.tasks.enhance_image_task"
VIDEO_TASK = "app.services.enhance.tasks.enhance_video_task"


def _fetch(key: str) -> bytes:
    from app.domains.characters.hub import fetch_bytes

    return fetch_bytes(key)


def _upload(path: str, key: str, content_type: str) -> None:
    from app.platform.storage.r2 import get_r2_client

    get_r2_client().upload_file(path, key, content_type=content_type)


def _download(url: str, path: str) -> None:
    import requests

    with requests.get(url, stream=True, timeout=300) as response:
        response.raise_for_status()
        with open(path, "wb") as fh:
            for chunk in response.iter_content(1 << 20):
                fh.write(chunk)


@dataclass
class Deps:
    fetch: Callable[[str], bytes] = _fetch
    upload: Callable[[str, str, str], None] = _upload
    download: Callable[[str, str], None] = _download
    upscale_image: Callable[[bytes], esrgan_cpu.Upscaled] = esrgan_cpu.upscale
    upscale_video: Callable[[str], str] = lambda url: seedvr_api.SeedVRClient().wait(
        seedvr_api.SeedVRClient().submit(url))
    smooth_video: Callable[[str], str] = rife.interpolate
    media_url: Callable[[str], str] = service._media_url


def _session():
    from app.models.db.base import get_session

    return get_session()


def _job(session: Any, job_id: str, kind: str):
    from app.models.db.models import Job

    job = session.get(Job, job_id)
    if job is None or job.kind != kind:
        raise LookupError(f"{kind} {job_id} not found")
    return job


def _mark_failed(job: Any, exc: Exception) -> None:
    job.state = service.TASK_STATE_FAILED
    job.error = str(exc)[:300] if isinstance(exc, EnhanceError) else "the enhance step failed"
    job.failed_stage = job.kind


def run_image(job_id: str, deps: Deps | None = None) -> dict[str, Any]:
    deps = deps or Deps()
    with _session() as session:
        job = _job(session, job_id, service.JOB_IMAGE)
        if job.state in (service.TASK_STATE_COMPLETE, service.TASK_STATE_FAILED):
            return {"job_id": job_id, "state": job.state}
        try:
            result = deps.upscale_image(deps.fetch(job.params["source_key"]))
            with tempfile.TemporaryDirectory(prefix="enhance-") as work:
                path = os.path.join(work, "upscaled.png")
                with open(path, "wb") as fh:
                    fh.write(result.image)
                key = f"jobs/{job.id}/enhance/upscaled-{esrgan_cpu.SCALE}x.png"
                deps.upload(path, key, "image/png")
            job.result_key = key
            job.state, job.progress = service.TASK_STATE_COMPLETE, 100
            job.params = {**dict(job.params or {}), "_seconds": result.seconds,
                          "_output": [result.width, result.height]}
        except Exception as exc:  # noqa: BLE001 - an image upscale was free; nothing to refund
            logger.warning(f"enhance image {job_id} failed: {exc}")
            _mark_failed(job, exc)
        return {"job_id": job_id, "state": job.state}


def run_video(job_id: str, deps: Deps | None = None) -> dict[str, Any]:
    from app.models.db.models import Job

    deps = deps or Deps()
    with _session() as session:
        job = _job(session, job_id, service.JOB_VIDEO)
        if job.state in (service.TASK_STATE_COMPLETE, service.TASK_STATE_FAILED):
            return {"job_id": job_id, "state": job.state}
        started = time.monotonic()
        try:
            source = session.get(Job, job.params["source_job_id"])
            url = deps.media_url(source.result_key)
            op = job.params.get("op")
            out_url = deps.upscale_video(url) if op == "upscale" else deps.smooth_video(url)
            with tempfile.TemporaryDirectory(prefix="enhance-") as work:
                path = os.path.join(work, "out.mp4")
                deps.download(out_url, path)
                key = f"jobs/{job.id}/enhance/{op}.mp4"
                deps.upload(path, key, "video/mp4")
            job.result_key = key
            job.state, job.progress = service.TASK_STATE_COMPLETE, 100
            job.params = {**dict(job.params or {}), "_seconds": round(time.monotonic() - started, 1)}
        except Exception as exc:  # noqa: BLE001 - a failed video job refunds its credits
            logger.warning(f"enhance video {job_id} failed: {exc}")
            _mark_failed(job, exc)
            service.refund_video(session, job)
        return {"job_id": job_id, "state": job.state}


def enqueue_image(job_id: str) -> str:
    return str(enhance_image_task.apply_async(args=[job_id], queue="generation").id)


def enqueue_video(job_id: str) -> str:
    return str(enhance_video_task.apply_async(args=[job_id], queue="generation").id)


@celery_app.task(name=IMAGE_TASK, soft_time_limit=300, time_limit=330)
def enhance_image_task(job_id: str) -> dict[str, Any]:
    return run_image(job_id)


@celery_app.task(name=VIDEO_TASK, soft_time_limit=2400, time_limit=2460)
def enhance_video_task(job_id: str) -> dict[str, Any]:
    return run_video(job_id)


__all__ = ["Deps", "IMAGE_TASK", "VIDEO_TASK", "enqueue_image", "enqueue_video", "enhance_image_task",
           "enhance_video_task", "run_image", "run_video"]
