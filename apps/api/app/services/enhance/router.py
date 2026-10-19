"""Upscale and smooth routes (MH7). Signed in; video work is priced first.

* ``POST /api/v1/enhance/image``          4x image upscale (free inside the daily cap)
* ``POST /api/v1/enhance/video/quote``    price of a video upscale or smooth, in AI-video credits
* ``POST /api/v1/enhance/video``          start it with the price you saw
* ``GET  /api/v1/enhance/{job_id}``       progress and the result
"""

from __future__ import annotations

from fastapi import Path, Request
from loguru import logger
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.utils import utils

from . import service
from .errors import EnhanceError

router = new_router()


class ImageRequest(BaseModel):
    image_key: str = Field("", max_length=512)
    source_job_id: str = Field("", max_length=32)


class VideoQuoteRequest(BaseModel):
    source_job_id: str = Field(..., min_length=1, max_length=32)
    op: str = Field("upscale", max_length=16)


class VideoRequest(VideoQuoteRequest):
    quoted_credits: int = Field(..., ge=0)


def _http(exc: EnhanceError, request_id: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=exc.status_code, message=f"{request_id}: {exc}",
                         data={"code": exc.code})


def _enqueue_or_fail(job_id: str, enqueue, request_id: str, refund: bool) -> None:
    try:
        enqueue(job_id)
    except Exception as exc:  # noqa: BLE001 - an enqueue failure never keeps credits
        logger.error(f"enhance {job_id} enqueue failed: {exc}")
        from app.models.db.models import Job

        with get_session() as session:
            job = session.get(Job, job_id)
            job.state, job.error = service.TASK_STATE_FAILED, "could not start"
            if refund:
                service.refund_video(session, job)
        raise HttpException(task_id=request_id, status_code=502, message=f"{request_id}: could not start",
                            data={"code": "enqueue_failed"}) from exc


def enqueue_image(job_id: str) -> str:
    from .tasks import enqueue_image as _enqueue

    return _enqueue(job_id)


def enqueue_video(job_id: str) -> str:
    from .tasks import enqueue_video as _enqueue

    return _enqueue(job_id)


@router.post("/enhance/image", summary="Upscale an image 4x (free inside the daily cap)")
def upscale_image(request: Request, body: ImageRequest):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            job = service.start_image(session, str(user.id), image_key=body.image_key,
                                      source_job_id=body.source_job_id)
        except EnhanceError as exc:
            raise _http(exc, request_id) from exc
        job_id = job.id
    _enqueue_or_fail(job_id, enqueue_image, request_id, refund=False)
    return utils.get_response(200, {"job_id": job_id, "state": service.TASK_STATE_PROCESSING})


@router.post("/enhance/video/quote", summary="Price a video upscale or smooth motion (AI-video credits)")
def quote_video(request: Request, body: VideoQuoteRequest):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            price = service.video_quote(session, str(user.id), source_job_id=body.source_job_id, op=body.op)
        except EnhanceError as exc:
            raise _http(exc, request_id) from exc
    # Price sources name vendors; they stay server-side (recorded on the catalog row).
    public = {k: v for k, v in price.items() if k not in ("price_source", "price_date", "provider_usd")}
    return utils.get_response(200, public)


@router.post("/enhance/video", summary="Start a video upscale or smooth motion with the quoted price")
def start_video(request: Request, body: VideoRequest):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            job = service.start_video(session, str(user.id), source_job_id=body.source_job_id, op=body.op,
                                      quoted_credits=body.quoted_credits)
        except EnhanceError as exc:
            raise _http(exc, request_id) from exc
        job_id = job.id
    _enqueue_or_fail(job_id, enqueue_video, request_id, refund=True)
    return utils.get_response(200, {"job_id": job_id, "state": service.TASK_STATE_PROCESSING})


@router.get("/enhance/{job_id}", summary="Upscale or smooth progress and result")
def get_enhance(request: Request, job_id: str = Path(..., max_length=32)):
    from app.models.db.models import Job

    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        job = session.get(Job, job_id)
        if job is None or job.kind not in (service.JOB_IMAGE, service.JOB_VIDEO) or str(job.user_id) != str(user.id):
            raise HttpException(task_id=request_id, status_code=404, message=f"{request_id}: not found")
        view = service.job_view(job)
    return utils.get_response(200, view)
