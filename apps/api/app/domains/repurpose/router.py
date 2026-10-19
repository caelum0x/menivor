"""Repurposing engine HTTP domain.

Routes under ``/api/v1``. Turns a long recording/URL into ranked highlight clips
a creator can review and promote into reels. Import-safe guarded DB block.

Endpoints:
* ``POST /repurpose``                       create a repurpose job
* ``GET  /repurpose``                       list the caller's jobs
* ``GET  /repurpose/{id}``                  job status
* ``POST /repurpose/{id}/rank``             rank transcript -> highlight clips
* ``GET  /repurpose/{id}/clips``            list suggested clips
* ``POST /repurpose/clips/{clip_id}/promote`` promote a clip -> reel draft

Charging (MN1): a run that transcribes or calls the LLM ranker costs one credit
(auto rank, or a manual rank with unscored segments). Pre-scored segments are
ranked deterministically and stay free, as does promoting a clip (the reel it
becomes is charged by ``POST /jobs``). A short balance is a 402 with nothing
queued; a failed run is refunded exactly once, when the failure is seen (the
failing request itself, or the next read of the job).
"""

from __future__ import annotations

from typing import Any

from fastapi import Path, Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router
from app.domains.reels import charge
from app.models.exception import HttpException
from app.utils import utils

from .schemas import CreateRepurposeRequest, RankRequest

try:
    from app.core.auth import resolve_principal
    from app.domains.repurpose.service import RepurposeError, RepurposeService
    from app.models.db.base import get_session

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before DB layer exists
    resolve_principal = None  # type: ignore[assignment]
    RepurposeError = Exception  # type: ignore[assignment,misc]
    RepurposeService = None  # type: ignore[assignment]
    get_session = None  # type: ignore[assignment]
    _DB_IMPORT_ERROR = exc


router = new_router()


def _require_db(request_id: str) -> None:
    if _DB_IMPORT_ERROR is not None or get_session is None or RepurposeService is None:
        logger.error(
            f"repurpose persistence unavailable, request_id: {request_id}, "
            f"error: {_DB_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: persistence layer is not available",
        )


def _resolve_user(request: Request, session: Any, request_id: str):
    return resolve_principal(request, session, request_id)


_SETTLE_SCAN_LIMIT = 10


def _settle_failed(session: Any, user_id: str, jobs: list[dict]) -> None:
    """Refund failed runs that were not refunded yet (idempotent per debit)."""
    failed = [j for j in jobs if j.get("status") == "failed" and j.get("id")]
    for job in failed[:_SETTLE_SCAN_LIMIT]:
        charge.refund_ref_once(
            session, user_id=str(user_id), kind=charge.REPURPOSE_KIND, ref=str(job["id"])
        )


def _map_error(exc: Exception, request_id: str) -> HttpException:
    status_code = int(getattr(exc, "status_code", 400) or 400)
    message = str(getattr(exc, "message", "") or "invalid repurpose request")
    return HttpException(
        task_id=request_id, status_code=status_code, message=f"{request_id}: {message}"
    )


@router.post("/repurpose", summary="Create a repurpose job")
def create_repurpose(request: Request, body: CreateRepurposeRequest):
    """Start a long-video repurpose job (upload key or external URL)."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            data = RepurposeService(session).create_job(
                user.id,
                source_kind=body.source_kind,
                source_ref=body.source_ref,
                language=body.language,
                title=body.title,
            )
        except RepurposeError as exc:
            raise _map_error(exc, request_id) from exc
    return utils.get_response(200, data)


@router.get("/repurpose", summary="List repurpose jobs")
def list_repurpose(request: Request):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        jobs = RepurposeService(session).list_jobs(user.id)
        _settle_failed(session, user.id, jobs)
    return utils.get_response(200, {"jobs": jobs})


@router.get("/repurpose/{job_id}", summary="Get a repurpose job")
def get_repurpose(request: Request, job_id: str = Path(..., description="Repurpose job id")):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            data = RepurposeService(session).get_job(job_id, user.id)
        except RepurposeError as exc:
            raise _map_error(exc, request_id) from exc
        _settle_failed(session, user.id, [data])
    return utils.get_response(200, data)


@router.post("/repurpose/{job_id}/rank", summary="Rank transcript into clips")
def rank_repurpose(
    request: Request,
    body: RankRequest,
    job_id: str = Path(..., description="Repurpose job id"),
):
    """Rank a job's transcript into non-overlapping highlight clips.

    Pass pre-scored segments for deterministic selection, or unscored segments to
    invoke the LLM ranker (503 when the LLM layer is unavailable).
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    segments = [s.model_dump() for s in body.segments]
    if not segments:
        return _queue_auto_rank(request, body, job_id, request_id)
    from app.domains.repurpose.service import _needs_ranking

    charged_user = ""
    if _needs_ranking(segments):
        # The LLM ranker runs: debit first in its own committed transaction so
        # the user-row lock is not held across the model call.
        with get_session() as session:
            user = _resolve_user(request, session, request_id)
            try:
                RepurposeService(session).get_job(job_id, user.id)
            except RepurposeError as exc:
                raise _map_error(exc, request_id) from exc
            charge.debit_ref_or_402(
                session, user_id=str(user.id), kind=charge.REPURPOSE_KIND, ref=job_id,
                request_id=request_id, what="clip ranking",
            )
            charged_user = str(user.id)
    try:
        clips = _rank_segments(request, body, job_id, request_id, segments)
    except Exception:
        if charged_user:
            charge.safe_refund_ref_once(user_id=charged_user, kind=charge.REPURPOSE_KIND, ref=job_id)
        raise
    return utils.get_response(200, {"clips": clips})


def _rank_segments(
    request: Request, body: RankRequest, job_id: str, request_id: str, segments: list[dict]
) -> list[dict]:
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            return RepurposeService(session).rank(
                job_id,
                user.id,
                segments=segments,
                max_clips=body.max_clips,
                min_len_s=body.min_len_s,
                max_len_s=body.max_len_s,
                min_score=body.min_score,
            )
        except RepurposeError as exc:
            raise _map_error(exc, request_id) from exc


def _queue_auto_rank(request: Request, body: RankRequest, job_id: str, request_id: str):
    """No segments supplied: transcribe + rank the source on a worker.

    Returns the job's current clips (empty until the worker finishes) plus the
    job view, whose ``status`` moves ``transcribing`` -> ``ranking`` -> ``ready``
    (or ``failed`` with a reason).
    """
    from app.services.ratelimit import enforce_rate_limit

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        enforce_rate_limit(request, f"repurpose_auto:{user.id}", limit=10, window_s=3600)
        service = RepurposeService(session)
        user_id = str(user.id)
        try:
            # A previous failed run is settled before this one is charged.
            _settle_failed(session, user_id, [service.get_job(job_id, user_id)])
            job = service.request_auto_rank(job_id, user_id)
            clips = service.list_clips(job_id, user_id)
        except RepurposeError as exc:
            raise _map_error(exc, request_id) from exc
        if job.get("queued"):
            # 402 rolls back the status flip too: nothing is queued.
            charge.debit_ref_or_402(
                session, user_id=user_id, kind=charge.REPURPOSE_KIND, ref=job_id,
                request_id=request_id, what="repurpose run",
            )
    if job.pop("queued", False):
        try:
            from app.workers.tasks import run_repurpose_task

            run_repurpose_task.delay(
                {
                    "job_id": job_id,
                    "request_id": request_id,
                    "max_clips": body.max_clips,
                    "min_len_s": body.min_len_s,
                    "max_len_s": body.max_len_s,
                    "min_score": body.min_score,
                }
            )
        except Exception as exc:  # noqa: BLE001 - broker down -> visible failure
            logger.error(f"repurpose enqueue failed, request_id: {request_id}: {exc}")
            from app.domains.repurpose.service import _fail

            _fail(job_id, "the processing queue is unavailable; try again shortly")
            charge.safe_refund_ref_once(user_id=user_id, kind=charge.REPURPOSE_KIND, ref=job_id)
            raise HttpException(
                task_id=request_id,
                status_code=503,
                message=f"{request_id}: processing queue is unavailable",
            ) from exc
    return utils.get_response(200, {"clips": clips, "job": job})


@router.get("/repurpose/{job_id}/clips", summary="List suggested clips")
def list_clips(request: Request, job_id: str = Path(..., description="Repurpose job id")):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            clips = RepurposeService(session).list_clips(job_id, user.id)
        except RepurposeError as exc:
            raise _map_error(exc, request_id) from exc
    return utils.get_response(200, {"clips": clips})


@router.post("/repurpose/clips/{clip_id}/promote", summary="Promote a clip to a reel draft")
def promote_clip(request: Request, clip_id: str = Path(..., description="Clip id")):
    """Mark a clip promoted and return a ready-to-submit reel draft."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            data = RepurposeService(session).promote_clip(clip_id, user.id)
        except RepurposeError as exc:
            raise _map_error(exc, request_id) from exc
    return utils.get_response(200, data)
