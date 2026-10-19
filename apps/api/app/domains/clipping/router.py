"""Long->short auto-clipping HTTP domain.

Routes under ``/api/v1``. Turns one long recording/URL into several vertical,
caption-burned short clips. Mirrors ``domains/reels/router.py`` wiring: validate
-> (optional) reserve wallet -> enqueue ``Job(kind='clipping')`` -> poll status.

Import-safe: the persistence / worker layers are pulled in inside a guarded block
(like ``domains/repurpose/router.py``) so merely importing this module never
crashes app startup; a missing layer degrades to a clean ``503`` at request time.
Every response uses the shared ``utils.get_response`` envelope.
"""

from __future__ import annotations

from typing import Any

from fastapi import Path, Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.utils import utils

from .schemas import ClipJobCreateRequest

CLIPPING_JOB_KIND = "clipping"

try:
    from app.core.auth import resolve_principal
    from app.models.db.base import get_session
    from app.models.db.models import Job
    from app.models.db.repositories import JobRepository

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before DB layer exists
    resolve_principal = None  # type: ignore[assignment]
    get_session = None  # type: ignore[assignment]
    Job = None  # type: ignore[assignment]
    JobRepository = None  # type: ignore[assignment]
    _DB_IMPORT_ERROR = exc


router = new_router()


# --------------------------------------------------------------------------- #
# Guards / helpers
# --------------------------------------------------------------------------- #
def _require_db(request_id: str) -> None:
    if _DB_IMPORT_ERROR is not None or get_session is None or JobRepository is None:
        logger.error(
            f"clipping persistence unavailable, request_id: {request_id}, "
            f"error: {_DB_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: persistence layer is not available",
        )


def _resolve_user(request: Request, session: Any, request_id: str):
    return resolve_principal(request, session, request_id)


def _stored_params(body: ClipJobCreateRequest, request_id: str) -> dict:
    """Build the JSON ``Job.params`` payload persisted for a clipping job."""
    return {
        "source_video_key": body.source_video_key,
        "source_url": body.source_url,
        "language": body.language,
        "target_count": body.target_count,
        "min_len_s": body.min_len_s,
        "max_len_s": body.max_len_s,
        "score_floor": body.score_floor,
        "captions": body.captions,
        "transitions": body.transitions,
        "publish_targets": list(body.publish_targets),
        "_correlation_id": request_id,
    }


def _reserve_wallet(
    session: Any, body: ClipJobCreateRequest, user_id: str, job_id: str, request_id: str
) -> dict:
    """Reserve the quoted max cost from the wallet when a quote is supplied.

    Best-effort at the edge: absent a quote this is a no-op (the classic path).
    A wallet failure maps to a clean HTTP error rather than orphaning the job.
    """
    from app.domains.clipping.wallet_bridge import (
        WalletBridgeError,
        extract_wallet_intent,
        reserve_for_job,
        validate_intent,
    )

    intent = extract_wallet_intent(body)
    if intent is None:
        return {}
    try:
        validate_intent(session, intent, request_id)
        return reserve_for_job(
            session,
            user_id=user_id,
            intent=intent,
            job_id=job_id,
            request_id=request_id,
        )
    except WalletBridgeError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=exc.status_code,
            message=f"{request_id}: {exc.message}",
        ) from exc


def _enforce_platform_spend_cap(body: ClipJobCreateRequest, request_id: str) -> None:
    """Fail-closed per-job USD ceiling for social-platform link ingestion.

    A platform (YouTube/TikTok/Vimeo/Twitch/X) source can pull a much larger,
    operator-uncontrolled video than an owned upload, so an optional spend cap
    bounds what such a job may reserve. ``0`` (the default) means "rely on the
    standard wallet quote ceiling only" and is a no-op here.
    """
    url = (body.source_url or "").strip()
    if not url:
        return
    from app.domains.clipping.platform_source import (
        platform_spend_cap_micros,
        recognize_platform,
    )

    if recognize_platform(url) is None:
        return
    cap = platform_spend_cap_micros()
    if cap <= 0:
        return
    quote = body.quote if isinstance(body.quote, dict) else {}
    try:
        requested = int(quote.get("max_cost_micros", 0) or 0)
    except (TypeError, ValueError):
        requested = 0
    if requested > cap:
        raise HttpException(
            task_id=request_id,
            status_code=402,
            message=(
                f"{request_id}: platform-ingest job exceeds the configured spend cap"
            ),
        )


def _import_worker(request_id: str):
    try:
        from app.workers import tasks

        return tasks
    except Exception as exc:  # noqa: BLE001 - surfaced as a clean 503
        logger.error(f"clipping worker unavailable, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: task orchestration is not available",
        )


def _job_view(job: Any) -> dict:
    params = getattr(job, "params", {}) or {}
    params = params if isinstance(params, dict) else {}
    stages = getattr(job, "stages", {}) or {}
    stages = stages if isinstance(stages, dict) else {}
    return {
        "id": job.id,
        "state": job.state,
        "progress": job.progress,
        "language": str(params.get("language") or "auto"),
        "target_count": int(params.get("target_count") or 0),
        "clip_count": len(_stored_clips(job)),
        "stitched_key": str(stages.get("stitched_key") or ""),
        "error": str(getattr(job, "error", "") or ""),
        "correlation_id": str(params.get("_correlation_id") or ""),
    }


def _stored_clips(job: Any) -> list[dict]:
    stages = getattr(job, "stages", {}) or {}
    clips = stages.get("clips") if isinstance(stages, dict) else None
    return list(clips) if isinstance(clips, list) else []


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.post("/clipping/jobs", summary="Create a long->short clipping job")
def create_clip_job(request: Request, body: ClipJobCreateRequest):
    """Validate -> reserve wallet (opt-in) -> enqueue ``Job(kind='clipping')``."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _enforce_platform_spend_cap(body, request_id)
    tasks = _import_worker(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        params = _stored_params(body, request_id)
        job = JobRepository(session).create(
            user_id=user.id, kind=CLIPPING_JOB_KIND, params=params
        )
        marker = _reserve_wallet(session, body, user.id, job.id, request_id)
        if marker:
            job.params = {**job.params, **marker}
            session.flush()
        job_id = job.id
        state, progress = job.state, job.progress

    try:
        result = tasks.run_clipping.apply_async(
            args=[{"job_id": job_id, "request_id": request_id}],
            headers={"correlation_id": request_id},
        )
        with get_session() as session:
            JobRepository(session).set_celery_task_id(job_id, result.id)
    except Exception as exc:  # noqa: BLE001 - enqueue failure must not orphan a job
        logger.error(f"clipping enqueue failed for job {job_id}: {exc}")
        with get_session() as session:
            JobRepository(session).mark_failed(job_id, "enqueue", str(exc))
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to enqueue clipping job",
        ) from exc

    return utils.get_response(
        200,
        {
            "id": job_id,
            "state": state,
            "progress": progress,
            "correlation_id": request_id,
        },
    )


@router.get("/clipping/jobs", summary="List clipping jobs")
def list_clip_jobs(request: Request, limit: int = 50, offset: int = 0):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    limit = max(1, min(100, int(limit)))
    offset = max(0, int(offset))
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        rows = JobRepository(session).list_for_user_by_kind(
            user.id, CLIPPING_JOB_KIND, limit=limit, offset=offset
        )
        jobs = [_job_view(job) for job in rows]
    return utils.get_response(200, {"jobs": jobs})


@router.get("/clipping/jobs/{job_id}", summary="Get a clipping job")
def get_clip_job(
    request: Request, job_id: str = Path(..., description="Clipping job id")
):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        job = JobRepository(session).get(job_id)
        if job is None or job.user_id != user.id or job.kind != CLIPPING_JOB_KIND:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: clipping job not found",
            )
        data = _job_view(job)
    return utils.get_response(200, data)


@router.get("/clipping/jobs/{job_id}/clips", summary="List a job's produced clips")
def list_clip_job_clips(
    request: Request, job_id: str = Path(..., description="Clipping job id")
):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        job = JobRepository(session).get(job_id)
        if job is None or job.user_id != user.id or job.kind != CLIPPING_JOB_KIND:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: clipping job not found",
            )
        clips = [
            {**clip, "id": f"{job_id}:{index}", "clip_job_id": job_id}
            for index, clip in enumerate(_stored_clips(job))
        ]
    return utils.get_response(200, {"clips": clips})


@router.post(
    "/clipping/clips/{clip_id}/promote", summary="Promote a clip to a reel draft"
)
def promote_clip(
    request: Request, clip_id: str = Path(..., description="Clip id ({job_id}:{index})")
):
    """Promote one produced clip into a ready-to-submit reel draft.

    Reuses the ``repurpose.promote_clip`` pattern: this domain never spends
    credits — the returned draft is what the client submits to ``POST /jobs``.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    job_id, _, raw_index = str(clip_id).partition(":")
    try:
        index = int(raw_index)
    except (TypeError, ValueError):
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: malformed clip id (expected '<job_id>:<index>')",
        )
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        job = JobRepository(session).get(job_id)
        if job is None or job.user_id != user.id or job.kind != CLIPPING_JOB_KIND:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: clip not found",
            )
        clips = _stored_clips(job)
        if index < 0 or index >= len(clips):
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: clip not found",
            )
        clip = clips[index]
        params = job.params if isinstance(job.params, dict) else {}
        durable_clip_key = str(clip.get("result_key") or "")
        draft = {
            "video_subject": clip.get("title") or clip.get("hook") or "Clipped short",
            "video_script": clip.get("transcript", ""),
            "source_kind": "upload"
            if durable_clip_key or params.get("source_video_key")
            else "url",
            "source_ref": durable_clip_key
            or params.get("source_video_key")
            or params.get("source_url", ""),
            "start_s": 0
            if durable_clip_key
            else clip.get("source_in_s", clip.get("start_s", 0)),
            "end_s": clip.get("length_s", 0)
            if durable_clip_key
            else clip.get("source_out_s", clip.get("end_s", 0)),
        }
    return utils.get_response(
        200, {"clip": {**clip, "id": clip_id}, "reel_draft": draft}
    )
