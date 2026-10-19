"""OTT transcode tasks (MV2/MV3): short sources on box 1 (tier 3, bulk queue), stale claims requeued.

The packager binary's checksum is verified before the first job (a mismatch
fails the job; nothing is packaged with an unpinned build). Every job records
its node, CPU seconds and cost.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Callable

from loguru import logger

from app.workers.celery_app import celery_app

BOX1_TASK = "app.workers.tasks_ott.package_on_box1_task"
REQUEUE_TASK = "app.workers.tasks_ott.requeue_stale_task"
BEAT_SCHEDULE: dict[str, dict] = {"menivor-ott-requeue-stale": {"task": REQUEUE_TASK, "schedule": 120.0}}
PLATFORM_ENV = "SHAKA_PACKAGER_PLATFORM"


def box1_queue() -> str:
    """The bulk render lane (never ahead of paid renders) when lanes are on, else the render queue."""
    from app.domains.reels.policy import DEFAULT_RENDER_QUEUE, LANE_BULK, LANE_QUEUES, lanes_enabled

    return LANE_QUEUES[LANE_BULK] if lanes_enabled() else DEFAULT_RENDER_QUEUE


#: Box 1 never downloads more than this for one source (a 3-min 1080p master is far below it).
BOX1_MAX_SOURCE_BYTES = 4 * 1024 ** 3


class SourceTooLarge(RuntimeError):
    """The source is over the box 1 byte cap; the job goes to the Mac or burst lane."""


def _download(url: str, path: str, *, max_bytes: int | None = None) -> None:
    import requests

    written = 0
    with requests.get(url, stream=True, timeout=600) as response:
        response.raise_for_status()
        with open(path, "wb") as fh:
            for chunk in response.iter_content(1 << 20):
                written += len(chunk)
                if max_bytes is not None and written > max_bytes:
                    raise SourceTooLarge(f"the source is over {max_bytes} bytes")
                fh.write(chunk)


def _box1_download(url: str, path: str) -> None:
    _download(url, path, max_bytes=BOX1_MAX_SOURCE_BYTES)


def _probe(path: str):
    from app.domains.film.story8_render import ffmpeg_bin
    from app.services.ott_transcode import pipeline

    ffmpeg = ffmpeg_bin()
    ffprobe = ffmpeg.replace("ffmpeg", "ffprobe") if "ffmpeg" in os.path.basename(ffmpeg) else "ffprobe"
    return pipeline.probe(ffprobe, path)


def _reroute(job_id: str, seconds: float, short_side: int) -> dict[str, Any]:
    from app.models.db.base import get_session
    from app.services.ott_transcode import service
    from app.services.ott_transcode.models import OttEncodeJob

    with get_session() as session:
        job = session.get(OttEncodeJob, job_id)
        service.reroute_from_box1(session, job, seconds=seconds, short_side=short_side)
        logger.info(f"ott box1 job {job_id} rerouted to {job.lane}: {seconds:.0f} s, short side {short_side}")
        return service.job_view(job)


def _upload_dir(out_dir: str, prefix: str, files: list[str]) -> None:
    from app.services.ott_transcode.pipeline import content_type
    from app.services.ott_transcode.uploads import R2Storage

    store = R2Storage()
    for rel in files:
        store._s3.upload_file(os.path.join(out_dir, rel), store._bucket, f"{prefix}/{rel}",
                              ExtraArgs={"ContentType": content_type(rel)})


def package_on_box1(job_id: str, *, download: Callable[[str, str], None] = _box1_download,
                    upload_dir: Callable[[str, str, list[str]], None] = _upload_dir,
                    source_url: Callable[[str], str] | None = None, ffmpeg: str | None = None,
                    packager_bin: str | None = None, probe: Callable[[str], Any] | None = None) -> dict[str, Any]:
    """Package a short source on box 1.

    The length and resolution on the job come from the upload form, so they are
    never trusted: the download stops at ``BOX1_MAX_SOURCE_BYTES`` and the real
    source is probed before any encode. A source over the box 1 limits is sent
    back to the Mac/burst queue (``service.reroute_from_box1``) instead.
    """
    from app.domains.film.story8_render import ffmpeg_bin
    from app.domains.ott.models import OttTitle
    from app.models.db.base import get_session
    from app.services.ott_package import packager
    from app.services.ott_transcode import picker, pipeline, service
    from app.services.ott_transcode.models import CLAIMED, LANE_BOX1, QUEUED, OttEncodeJob
    from app.services.ott_transcode.router import api_base, storage

    with get_session() as session:
        job = session.get(OttEncodeJob, job_id)
        if job is None or job.lane != LANE_BOX1 or job.status != QUEUED:
            return {"job_id": job_id, "skipped": True}
        job.status, job.node_id = CLAIMED, "box1"
        job.claimed_at = job.heartbeat_at = datetime.now(timezone.utc)
        title = session.get(OttTitle, job.title_id)
        protection = service.protection_for(session, title, api_base()) if title is not None else None
        source_key, prefix = job.source_key, job.output_prefix
        declared = (float(job.source_seconds or 0), int(job.source_height or 0))
        session.commit()
    try:
        binary = packager_bin or packager.packager_bin()
        digest = packager.verify_binary(binary, os.getenv(PLATFORM_ENV) or "linux-arm64")
        with tempfile.TemporaryDirectory(prefix="ott-") as work:
            src = os.path.join(work, "source")
            try:
                download((source_url or (lambda key: storage().presign_get(key, 6 * 3600)))(source_key), src)
            except SourceTooLarge:
                return _reroute(job_id, max(declared[0], picker.BOX1_MAX_SECONDS + 1), declared[1])
            real = (probe or _probe)(src)
            if not picker.box1_allowed(real.seconds, real.short_side):
                return _reroute(job_id, real.seconds, real.short_side)
            result = pipeline.run(src, work, ffmpeg=ffmpeg or ffmpeg_bin(), packager_bin=binary,
                                  protection=protection)
            upload_dir(result.out_dir, prefix, result.files)
        with get_session() as session:
            job = session.get(OttEncodeJob, job_id)
            # QM verify: encode minutes count the probed length, not the length the upload form claimed.
            measured = float(real.seconds) if real.seconds and real.seconds > 0 else None
            service.finish(session, job, cpu_seconds=result.cpu_seconds, packager_sha256=digest, node_id="box1",
                           measured_seconds=measured)
            return service.job_view(job)
    except Exception as exc:  # noqa: BLE001 - a failed job is retried or marked failed, never lost
        logger.warning(f"ott box1 job {job_id} failed: {exc}")
        with get_session() as session:
            job = session.get(OttEncodeJob, job_id)
            service.fail(session, job, str(exc) or type(exc).__name__)
            view = service.job_view(job)
        if view["status"] == QUEUED:
            package_on_box1_task.apply_async(args=[job_id], queue=box1_queue(), countdown=300)
        return view


@celery_app.task(name=BOX1_TASK, soft_time_limit=3600, time_limit=3660)
def package_on_box1_task(job_id: str) -> dict[str, Any]:
    return package_on_box1(job_id)


@celery_app.task(name=REQUEUE_TASK)
def requeue_stale_task() -> int:
    try:
        from app.models.db.base import get_session
        from app.services.ott_transcode import service

        from app.services.ott_transcode.models import LANE_BOX1, QUEUED

        with get_session() as session:
            stale = service.requeue_stale_jobs(session)
            box1 = [job.id for job in stale if job.lane == LANE_BOX1 and job.status == QUEUED]
            count = len(stale)
        for job_id in box1:  # a box 1 worker that died leaves nobody to pick its job up
            package_on_box1_task.apply_async(args=[job_id], queue=box1_queue())
        return count
    except Exception as exc:  # noqa: BLE001 - a beat tick never crashes the worker
        logger.error(f"ott requeue failed: {exc}")
        return 0


__all__ = ["BEAT_SCHEDULE", "BOX1_MAX_SOURCE_BYTES", "BOX1_TASK", "REQUEUE_TASK", "SourceTooLarge", "package_on_box1", "package_on_box1_task",
           "requeue_stale_task"]
