"""Dub an owned video as an async ``Job(kind="dub_video")``.

    POST /dub/videos -> Job(kind="dub_video") -> run_dub_video_task (Celery)
                                                   │
                         run_dub_video ────────────┘  (this module)
                         R2 -> work dir -> pyvideotrans container -> R2 -> Assets -> done

The Celery task stays a thin wrapper; this module does the work and is
unit-testable with the sidecar seam mocked. On any hard failure it raises so
the task's ``on_failure`` marks the job failed and calls
:func:`refund_dub_video` (idempotent, same pattern as ``domains/speak``).

Params persisted on the ``Job`` row::

    {"video_key", "source_language", "target_language", "voice_engine", "voice",
     "whisper_model", "translation", "free", "credits_cost", "workspace_id"?,
     "_correlation_id"?, "refunded"?, "subtitle_keys"? (set on completion)}
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any
from uuid import uuid4

from loguru import logger

from app.domains.dub import catalog, sidecar

DUB_VIDEO_ASSET_KIND = "dub_video"
DUB_SUBTITLE_ASSET_KIND = "dub_subtitle"
_VIDEO_CONTENT_TYPE = "video/mp4"
_SRT_CONTENT_TYPE = "application/x-subrip"


def _load_job_context(job_id: str) -> tuple[str, dict[str, Any]] | None:
    from app.models.db.base import get_session
    from app.models.db.repositories import JobRepository

    with get_session() as session:
        job = JobRepository(session).get(job_id)
        if job is None:
            return None
        return job.user_id, dict(job.params or {})


def _set_progress(job_id: str, progress: int) -> None:
    try:
        from app.models.db.base import get_session
        from app.models.db.repositories import JobRepository

        with get_session() as session:
            JobRepository(session).set_progress(job_id, progress)
    except Exception as exc:  # noqa: BLE001 - progress is cosmetic
        logger.debug(f"dub_video: progress update failed for {job_id!r}: {exc}")


def _download_input(key: str, local_path: str) -> None:
    """Pull the OWNED source video from our bucket (seam; mocked in tests)."""
    from app.platform.storage.r2 import get_r2_client

    get_r2_client().download_file(key, local_path)


def _upload(local_path: str, key: str, content_type: str) -> None:
    from app.platform.storage.r2 import get_r2_client

    with open(local_path, "rb") as fh:
        get_r2_client().upload_bytes(key, fh.read(), content_type)


def probe_duration(path: str) -> float:
    """Seconds of media in ``path`` via ffprobe (our own ffmpeg, not the sidecar)."""
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "json", path,
            ],
            capture_output=True, text=True, timeout=60, check=False,
        )
        data = json.loads(proc.stdout or "{}")
        return float((data.get("format") or {}).get("duration") or 0.0)
    except Exception as exc:  # noqa: BLE001 - normalized below
        raise RuntimeError(f"dub_video: could not read the video duration: {exc}") from exc


def _work_dir(job_id: str, settings: sidecar.SidecarSettings) -> str:
    safe = sidecar.container_name(job_id)
    path = os.path.join(settings.work_root, f"{safe}-{uuid4().hex[:8]}")
    os.makedirs(os.path.join(path, sidecar.OUTPUT_DIRNAME), exist_ok=True)
    return path


def run_dub_video(job_id: str) -> dict[str, Any]:
    """Dub one video for ``Job(kind="dub_video")``. Raises on hard failure.

    Raises :class:`sidecar.SidecarBusy` (without touching the job) when another
    dub holds the host lock, so the task can retry later.
    """
    job_id = (job_id or "").strip()
    if not job_id:
        raise RuntimeError("dub_video: run called without a job_id")
    ctx = _load_job_context(job_id)
    if ctx is None:
        raise RuntimeError(f"dub_video: job {job_id!r} not found")
    user_id, params = ctx
    video_key = str(params.get("video_key") or "").strip()
    if not video_key:
        raise RuntimeError("dub_video: job has no video_key")
    for field_name in ("source_language", "target_language", "voice"):
        if not str(params.get(field_name) or "").strip():
            raise RuntimeError(f"dub_video: job is missing {field_name}")

    settings = sidecar.settings_from_config()
    with sidecar.host_lock(settings.lock_path):
        work_dir = _work_dir(job_id, settings)
        try:
            return _run_locked(job_id, user_id, params, video_key, work_dir, settings)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)


def _run_locked(
    job_id: str,
    user_id: str,
    params: dict[str, Any],
    video_key: str,
    work_dir: str,
    settings: sidecar.SidecarSettings,
) -> dict[str, Any]:
    correlation_id = str(params.get("_correlation_id") or "")
    _set_progress(job_id, 5)
    input_path = os.path.join(work_dir, sidecar.INPUT_NAME)
    _download_input(video_key, input_path)
    if not os.path.isfile(input_path) or os.path.getsize(input_path) <= 0:
        raise RuntimeError("dub_video: source video download produced no bytes")

    duration = probe_duration(input_path)
    limit = catalog.max_seconds()
    if duration <= 0:
        raise RuntimeError("dub_video: the file has no readable video/audio stream")
    if limit and duration > limit:
        raise RuntimeError(
            f"dub_video: video is {duration:.0f}s; the limit is {limit}s per dub"
        )

    _set_progress(job_id, 15)
    result = sidecar.run_dub(job_id=job_id, work_dir=work_dir, plan=params, settings=settings)

    _set_progress(job_id, 85)
    target = str(params.get("target_language"))
    prefix = f"jobs/{job_id}/dub"
    video_out_key = f"{prefix}/{uuid4().hex}-{target}.mp4"
    _upload(result.video_path, video_out_key, _VIDEO_CONTENT_TYPE)
    subtitle_keys: dict[str, str] = {}
    for code, path in result.subtitle_paths.items():
        key = f"{prefix}/{uuid4().hex}-{code}.srt"
        _upload(path, key, _SRT_CONTENT_TYPE)
        subtitle_keys[code] = key

    _persist_and_complete(
        job_id=job_id,
        user_id=user_id,
        video_key=video_out_key,
        subtitle_keys=subtitle_keys,
        duration=duration,
        meta={
            "correlation_id": correlation_id,
            "source_key": video_key,
            "source_language": params.get("source_language"),
            "target_language": target,
            "voice_engine": params.get("voice_engine"),
            "voice": params.get("voice"),
            "engine": f"pyvideotrans {catalog.PYVIDEOTRANS_VERSION}",
            "free": bool(params.get("free")),
        },
    )
    logger.success(f"dub_video: completed job={job_id!r} -> {video_out_key}")
    return {"job_id": job_id, "video_key": video_out_key, "subtitle_keys": subtitle_keys}


def _persist_and_complete(
    *,
    job_id: str,
    user_id: str,
    video_key: str,
    subtitle_keys: dict[str, str],
    duration: float,
    meta: dict[str, Any],
) -> None:
    """Write the video + subtitle ``Asset`` rows and mark the job complete."""
    from app.models.db.base import get_session
    from app.models.db.repositories import AssetRepository, JobRepository

    with get_session() as session:
        assets = AssetRepository(session)
        assets.create(
            user_id=user_id,
            kind=DUB_VIDEO_ASSET_KIND,
            r2_key=video_key,
            job_id=job_id,
            content_type=_VIDEO_CONTENT_TYPE,
            duration_s=duration,
            meta=meta,
        )
        for code, key in subtitle_keys.items():
            assets.create(
                user_id=user_id,
                kind=DUB_SUBTITLE_ASSET_KIND,
                r2_key=key,
                job_id=job_id,
                content_type=_SRT_CONTENT_TYPE,
                duration_s=0.0,
                meta={**meta, "language": code},
            )
        repo = JobRepository(session)
        job = repo._locked_job(job_id)  # noqa: SLF001 - same pattern as refunds
        if job is not None:
            job.params = {**dict(job.params or {}), "subtitle_keys": subtitle_keys}
        # result_key = the dubbed video, so /jobs/{id} download and native
        # publish (which reads result_key) work unchanged.
        repo.mark_complete(job_id, video_key)


def refund_dub_video(job_id: str) -> None:
    """Idempotently refund a failed dub's debit (best-effort, never raises)."""
    job_id = (job_id or "").strip()
    if not job_id:
        return
    # Premium voice credits held by the dub go back too (idempotent).
    from app.services.billing.premium_credits import refund_job_once

    refund_job_once(job_id)
    try:
        from app.models.db.base import get_session
        from app.models.db.repositories import CreditRepository, JobRepository

        with get_session() as session:
            job = JobRepository(session)._locked_job(job_id)  # noqa: SLF001
            if job is None:
                return
            params = dict(job.params or {})
            if params.get("refunded"):
                return
            cost = int(params.get("credits_cost") or 0)
            if cost <= 0:
                return
            workspace_id = params.get("workspace_id") or None
            credits = CreditRepository(session)
            if workspace_id:
                credits.workspace_grant(workspace_id, cost, "dub_video_refund", job.user_id)
            else:
                credits.grant(job.user_id, cost, "dub_video_refund")
            job.params = {**params, "refunded": True}
            session.flush()
        logger.info(f"dub_video: refunded {cost} credit(s) for failed job={job_id!r}")
    except Exception as exc:  # noqa: BLE001 - refund is best-effort
        logger.error(f"dub_video: refund failed for job={job_id!r}: {exc}")


__all__ = [
    "DUB_SUBTITLE_ASSET_KIND",
    "DUB_VIDEO_ASSET_KIND",
    "probe_duration",
    "refund_dub_video",
    "run_dub_video",
]
