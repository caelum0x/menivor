"""Dub Studio API — dub any video you own into another language (async).

Routes (all under ``/api/v1``):

* ``GET  /dub/options`` — languages, free edge-tts voices, whether ElevenLabs
  is configured, credit prices, limits, and whether the engine is set up here.
* ``POST /dub/videos`` — auth → rate limit → engine available (402
  ``format_locked`` otherwise) → option validation (400) → OWNERSHIP of the
  source video (403) + type/size check → one in-flight dub per user (409) →
  atomic ``Job`` create + credit debit (402 on insufficient) → enqueue → the
  initial snapshot. An enqueue failure refunds.
* ``GET  /dub/videos`` — the caller's dubs, newest first.
* ``GET  /dub/videos/{id}`` — owner-scoped poll; once complete it carries the
  dubbed video + subtitle files as short-lived download URLs.

The dub runs in a separate pyvideotrans container (GPL-3.0) invoked by the
worker over its CLI; nothing here imports it.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Path, Query, Request
from loguru import logger
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.auth import resolve_principal
from app.domains.dub import catalog
from app.models.const import TASK_STATE_COMPLETE, TASK_STATE_FAILED
from app.models.db.base import get_session
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

router = new_router()

_DEBIT_REASON = "dub_video_debit"
_RATE_LIMIT = 10
_RATE_WINDOW_S = 3600
_LIST_LIMIT_MAX = 50


class DubVideoRequest(BaseModel):
    video_key: str = Field(..., min_length=1, max_length=512)
    source_language: str = Field(..., min_length=2, max_length=10)
    target_language: str = Field(..., min_length=2, max_length=10)
    voice_engine: Optional[str] = Field(default=None, max_length=20)
    voice: Optional[str] = Field(default=None, max_length=64)
    whisper_model: Optional[str] = Field(default=None, max_length=20)


def _error(request_id: str, status: int, message: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=status, message=f"{request_id}: {message}")


def _find_owned_video(session: Any, user_id: str, key: str) -> Any:
    """BOLA guard: return the caller's ``Asset`` for ``key`` or ``None``.

    Besides uploads, the caller's own finished reel (``jobs/<id>/final.mp4``,
    the job's ``result_key``) can be dubbed directly, so "dub this reel" needs
    no download and re-upload.
    """
    from app.domains.media.repository import MediaRepository

    asset = MediaRepository(session).find_owned_asset(user_id, key)
    if asset is not None:
        return asset
    return _owned_reel_result(session, user_id, key)


def _owned_reel_result(session: Any, user_id: str, key: str) -> Any:
    """A finished reel's result owned by ``user_id``, shaped like an ``Asset``."""
    from types import SimpleNamespace

    from app.models.const import TASK_STATE_COMPLETE
    from app.models.db.models import Job

    parts = key.split("/")
    if len(parts) != 3 or parts[0] != "jobs" or not parts[1] or not parts[2].endswith(".mp4"):
        return None
    job = session.get(Job, parts[1])
    if (
        job is None
        or str(job.user_id) != str(user_id)
        or job.state != TASK_STATE_COMPLETE
        or str(job.result_key or "") != key
    ):
        return None
    return SimpleNamespace(content_type="video/mp4", kind="final", size_bytes=0, reel_result=True)


def _require_video(asset: Any, request_id: str) -> None:
    if asset is None:
        raise _error(request_id, 403, "media key does not belong to the caller")
    content_type = str(getattr(asset, "content_type", "") or "").lower()
    kind = str(getattr(asset, "kind", "") or "").lower()
    if kind == "upload_pending":
        raise _error(request_id, 409, "the upload has not finished yet")
    if not (content_type.startswith("video/") or kind in {"video", "final", catalog.DUB_JOB_KIND}):
        raise _error(request_id, 400, "pick a video file to dub")
    size = int(getattr(asset, "size_bytes", 0) or 0)
    limit = catalog.max_bytes()
    if limit and size > limit:
        raise _error(request_id, 413, f"video is larger than {limit // (1024 * 1024)} MB")


def _require_clean_reel_access(user_id: str, request_id: str) -> None:
    """Dubbing a reel returns a clean MP4, so it needs the clean-download entitlement."""
    from app.services.user_entitlements import can_access_clean_result

    if not can_access_clean_result(user_id):
        raise _error(
            request_id,
            402,
            "dubbing a finished reel needs a plan or credit pack; you can still dub a video you upload",
        )


def _has_active_dub(session: Any, user_id: str) -> bool:
    from app.models.db.repositories import JobRepository

    recent = JobRepository(session).list_for_user_by_kind(user_id, catalog.DUB_JOB_KIND, limit=10)
    return any(job.state not in (TASK_STATE_COMPLETE, TASK_STATE_FAILED) for job in recent)


def _presign(key: str, download_name: str = "") -> str:
    if not key:
        return ""
    try:
        from app.platform.storage.r2 import get_r2_client

        return get_r2_client().presign_result_get(key, download_name or None)
    except Exception as exc:  # noqa: BLE001 - a poll never fails on one presign
        logger.warning(f"dub: presign failed for {key}: {exc}")
        return ""


def _snapshot(job: Any) -> dict[str, Any]:
    params = job.params if isinstance(job.params, dict) else {}
    complete = job.state == TASK_STATE_COMPLETE
    target = str(params.get("target_language") or "")
    video_key = str(job.result_key or "") if complete else ""
    subtitle_keys = params.get("subtitle_keys") if complete else None
    subtitles = []
    if isinstance(subtitle_keys, dict):
        for code, key in sorted(subtitle_keys.items()):
            subtitles.append({
                "language": code,
                "key": key,
                "url": _presign(str(key), f"dub-{job.id}-{code}.srt"),
            })
    state = "complete" if complete else ("failed" if job.state == TASK_STATE_FAILED else "processing")
    return {
        "dub_id": job.id,
        "state": state,
        "progress": int(job.progress or 0),
        "source_key": str(params.get("video_key") or ""),
        "source_language": str(params.get("source_language") or ""),
        "target_language": target,
        "voice_engine": str(params.get("voice_engine") or ""),
        "voice": str(params.get("voice") or ""),
        "free": bool(params.get("free")),
        "credits_cost": int(params.get("credits_cost") or 0),
        "refunded": bool(params.get("refunded")),
        "video_key": video_key,
        "video_url": _presign(video_key, f"dub-{job.id}-{target}.mp4") if video_key else "",
        "subtitles": subtitles,
        "error": str(job.error or "") if job.state == TASK_STATE_FAILED else "",
        "created_at": job.created_at.isoformat() if getattr(job, "created_at", None) else None,
    }


@router.get("/dub/options", summary="Dubbing languages, voices, prices and availability")
def dub_options(request: Request):
    request_id = base.get_task_id(request)
    with get_session() as session:
        resolve_principal(request, session, request_id)
    return utils.get_response(200, catalog.options_document())


@router.post("/dub/videos", summary="Dub a video you own into another language (async)")
def create_dub(request: Request, body: DubVideoRequest):
    request_id = base.get_task_id(request)
    if not catalog.sidecar_configured():
        from app.core.launch.formats import raise_format_locked

        raise_format_locked(request_id, "dub_video", "the dubbing engine is not set up on this deployment")
    try:
        plan = catalog.resolve_plan(
            source_language=body.source_language,
            target_language=body.target_language,
            voice_engine=body.voice_engine or "",
            voice=body.voice or "",
            whisper_model=body.whisper_model or "",
        )
    except catalog.DubOptionError as exc:
        raise _error(request_id, 400, str(exc)) from exc

    video_key = body.video_key.strip()
    from app.core.capabilities import pilot_enabled, require_generation_access
    from app.models.db.repositories import CreditRepository, JobRepository

    with get_session() as session:
        user = resolve_principal(request, session, request_id)
        enforce_rate_limit(request, f"dub_video:{user.id}", limit=_RATE_LIMIT, window_s=_RATE_WINDOW_S)
        video = _find_owned_video(session, user.id, video_key)
        _require_video(video, request_id)
        if getattr(video, "reel_result", False):
            _require_clean_reel_access(str(user.id), request_id)
        if _has_active_dub(session, user.id):
            raise _error(request_id, 409, "you already have a dub in progress; wait for it to finish")
        require_generation_access(request, session, user.id, "reel", plan.credits_cost, request_id)

        params: dict[str, Any] = {
            "_correlation_id": request_id,
            "video_key": video_key,
            **plan.as_params(),
            "workspace_id": None,
        }
        job = JobRepository(session).create(user_id=user.id, kind=catalog.DUB_JOB_KIND, params=params)
        if plan.credits_cost > 0:
            try:
                CreditRepository(session).debit(
                    user.id,
                    plan.credits_cost,
                    job.id,
                    "pilot_reel_debit" if pilot_enabled() else _DEBIT_REASON,
                )
            except ValueError as exc:
                raise _error(request_id, 402, f"insufficient credits: {exc}") from exc
        if plan.premium_voice_credits > 0:
            from app.services.billing import premium_credits

            try:
                premium_credits.debit(
                    session,
                    str(user.id),
                    premium_credits.KIND_PREMIUM_VOICE,
                    plan.premium_voice_credits,
                    f"{premium_credits.DEBIT_REASON}:{job.id}",
                    job.id,
                )
            except premium_credits.InsufficientPremiumCredits as exc:
                raise HttpException(
                    task_id=request_id,
                    status_code=402,
                    message=(
                        f"{request_id}: an ElevenLabs dub uses {exc.needed} premium voice "
                        f"credits; you have {exc.available}. Pick a free voice or add credits."
                    ),
                    data={
                        "code": "premium_voice_credits_required",
                        "needed": exc.needed,
                        "available": exc.available,
                    },
                ) from exc
        job_id = job.id
        snapshot = _snapshot(job)

    try:
        _enqueue(job_id, request_id)
    except Exception as exc:  # noqa: BLE001 - a paid job must never be orphaned
        logger.error(f"dub: enqueue failed for job {job_id}: {exc}")
        from app.domains.dub.tasks import mark_failed_and_refund

        mark_failed_and_refund(job_id, RuntimeError("failed to enqueue"))
        raise _error(request_id, 502, "failed to start the dub") from exc
    return utils.get_response(200, snapshot)


def _enqueue(job_id: str, request_id: str) -> None:
    from app.domains.dub.tasks import run_dub_video_task
    from app.models.db.repositories import JobRepository

    result = run_dub_video_task.apply_async(
        args=[{"job_id": job_id, "request_id": request_id}],
        headers={"correlation_id": request_id},
    )
    with get_session() as session:
        JobRepository(session).set_celery_task_id(job_id, result.id)


@router.get("/dub/videos", summary="List your dubs")
def list_dubs(request: Request, limit: int = Query(default=20, ge=1, le=_LIST_LIMIT_MAX)):
    request_id = base.get_task_id(request)
    from app.models.db.repositories import JobRepository

    with get_session() as session:
        user = resolve_principal(request, session, request_id)
        jobs = JobRepository(session).list_for_user_by_kind(user.id, catalog.DUB_JOB_KIND, limit=limit)
        items = [_snapshot(job) for job in jobs]
    return utils.get_response(200, {"dubs": items})


@router.get("/dub/videos/{dub_id}", summary="Poll one dub")
def get_dub(request: Request, dub_id: str = Path(..., max_length=64)):
    request_id = base.get_task_id(request)
    from app.models.db.repositories import JobRepository

    with get_session() as session:
        user = resolve_principal(request, session, request_id)
        job = JobRepository(session).get(dub_id)
        if job is None or job.user_id != user.id or job.kind != catalog.DUB_JOB_KIND:
            raise _error(request_id, 404, "dub not found")
        snapshot = _snapshot(job)
    return utils.get_response(200, snapshot)
