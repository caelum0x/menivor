"""Authenticated editor commands exposed through the product API.

Every export is a render and costs one credit (MN1). The debit commits with
the export job, before it is queued: a short balance is a 402 with no job. A
queue outage refunds at once; a failed render is refunded exactly once by
:func:`app.domains.reels.charge.refund_failed_job_once`, and the next export
request settles any failed export that was not refunded yet.
"""

from fastapi import Path, Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.auth import resolve_principal
from app.core.idempotency import read_idempotency_key
from app.domains.reels import charge
from app.models.db.base import get_session
from app.models.db.repositories import JobRepository
from app.models.exception import HttpException
from app.models.schema import JobResponse
from app.services.billing.pro_access import require_pro_action
from app.utils import utils

from .schemas import EditorExportRequest, TimelineExportRequest
from .service import (
    EditorDomainError,
    create_export_job,
    create_timeline_export_job,
    mark_enqueue_failure,
)

router = new_router()


def _require_pro_export(user_id: str, request_id: str) -> None:
    require_pro_action(user_id, request_id, action="export")


def _charge_export(session, user_id: str, response: dict, request_id: str) -> None:
    """Debit one credit for a freshly created export job (402 rolls it back)."""
    charge.refund_failed_jobs(session, user_id, charge.EDITOR_EXPORT_KINDS)
    charge.debit_or_402(
        session,
        user_id=user_id,
        job_id=str(response["job_id"]),
        request_id=request_id,
        reason=charge.EDITOR_DEBIT_REASON,
        what="export",
    )


def _fail_unqueued(export_job_id: str, error: str) -> None:
    mark_enqueue_failure(export_job_id, error)
    charge.refund_job_once(export_job_id, charge.EDITOR_REFUND_REASON)


@router.post(
    "/jobs/{job_id}/exports",
    response_model=JobResponse,
    summary="Export a selected range from a completed reel",
)
def create_editor_export(
    request: Request,
    body: EditorExportRequest,
    job_id: str = Path(..., min_length=1, max_length=64),
):
    request_id = base.get_task_id(request)
    idempotency_key = read_idempotency_key(request, request_id)
    try:
        with get_session() as session:
            user = resolve_principal(request, session, request_id)
            _require_pro_export(str(user.id), request_id)
            response, replay = create_export_job(
                session,
                user_id=str(user.id),
                source_job_id=job_id,
                in_point=body.in_point,
                out_point=body.out_point,
                idempotency_key=idempotency_key,
                request_id=request_id,
            )
            if not replay:
                _charge_export(session, str(user.id), response, request_id)
    except EditorDomainError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=exc.status_code,
            message=f"{request_id}: {exc.message}",
        ) from exc

    if replay:
        return utils.get_response(200, response)

    export_job_id = str(response["job_id"])
    try:
        from app.workers.tasks import export_editor_cut_task

        task = export_editor_cut_task.apply_async(
            args=[{"job_id": export_job_id, "request_id": request_id}],
            headers={"correlation_id": request_id},
        )
        with get_session() as session:
            JobRepository(session).set_celery_task_id(export_job_id, task.id)
    except Exception as exc:  # noqa: BLE001 - convert dispatch failure to job truth
        logger.error(
            f"editor export enqueue failed for {export_job_id}, "
            f"request_id: {request_id}: {exc}"
        )
        _fail_unqueued(export_job_id, str(exc))
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: editor export could not be queued",
        ) from exc
    return utils.get_response(200, response)


@router.post(
    "/jobs/{job_id}/timeline-exports",
    summary="Export a multi-segment timeline (trims + captions + overlays)",
)
def create_editor_timeline_export(
    request: Request,
    body: TimelineExportRequest,
    job_id: str = Path(..., min_length=1, max_length=64),
):
    """OpenCut-style export: an EDL of source trims + per-segment captions +
    time-anchored text overlays. The server validates and renders (authoritative);
    the browser editor only assembles the EDL."""
    request_id = base.get_task_id(request)
    idempotency_key = read_idempotency_key(request, request_id)
    try:
        with get_session() as session:
            user = resolve_principal(request, session, request_id)
            _require_pro_export(str(user.id), request_id)
            response, replay = create_timeline_export_job(
                session,
                user_id=str(user.id),
                source_job_id=job_id,
                segments=[s.model_dump() for s in body.segments],
                overlays=[o.model_dump() for o in body.overlays],
                music=body.music.model_dump() if body.music else None,
                idempotency_key=idempotency_key,
                request_id=request_id,
            )
            if not replay:
                _charge_export(session, str(user.id), response, request_id)
    except EditorDomainError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=exc.status_code,
            message=f"{request_id}: {exc.message}",
        ) from exc

    if replay:
        return utils.get_response(200, response)

    export_job_id = str(response["job_id"])
    try:
        from app.workers.tasks import export_editor_cut_task

        task = export_editor_cut_task.apply_async(
            args=[{"job_id": export_job_id, "request_id": request_id}],
            headers={"correlation_id": request_id},
        )
        with get_session() as session:
            JobRepository(session).set_celery_task_id(export_job_id, task.id)
    except Exception as exc:  # noqa: BLE001 - convert dispatch failure to job truth
        logger.error(
            f"timeline export enqueue failed for {export_job_id}, "
            f"request_id: {request_id}: {exc}"
        )
        _fail_unqueued(export_job_id, str(exc))
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: timeline export could not be queued",
        ) from exc
    return utils.get_response(200, response)


__all__ = ["create_editor_export", "create_editor_timeline_export", "router"]
