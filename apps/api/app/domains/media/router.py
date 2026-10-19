"""Canonical `/api/v1/uploads/*` HTTP adapter."""

from fastapi import Path, Query, Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.auth import resolve_principal
from app.domains.media.schemas import (
    PresignRequest,
    PresignResponse,
    RegisterUploadRequest,
    RegisterUploadResponse,
)
from app.models.db.base import get_session
from app.models.exception import HttpException
from app.utils import utils

from . import service

router = new_router()


def _domain_error(error: service.MediaDomainError, request_id: str) -> HttpException:
    return HttpException(
        task_id=request_id,
        status_code=error.status_code,
        message=f"{request_id}: {error.message}",
    )


@router.post(
    "/uploads/presign", response_model=PresignResponse, summary="Presign an upload"
)
def presign_upload(request: Request, body: PresignRequest):
    request_id = base.get_task_id(request)
    try:
        with get_session() as session:
            user = resolve_principal(request, session, request_id)
            data = service.create_upload_intent(
                session,
                user_id=str(user.id),
                filename=body.filename,
                content_type=body.content_type,
                size=body.size,
            )
    except service.MediaDomainError as exc:
        logger.error(f"presign upload failed, request_id: {request_id}: {exc}")
        raise _domain_error(exc, request_id) from exc
    return utils.get_response(200, data)


@router.post(
    "/uploads/register",
    response_model=RegisterUploadResponse,
    summary="Register an uploaded object as a caller-owned asset",
)
def register_upload(request: Request, body: RegisterUploadRequest):
    request_id = base.get_task_id(request)
    try:
        with get_session() as session:
            user = resolve_principal(request, session, request_id)
            data = service.register_upload(
                session,
                user_id=str(user.id),
                key=body.key,
                kind=body.kind,
            )
    except service.MediaDomainError as exc:
        raise _domain_error(exc, request_id) from exc
    return utils.get_response(200, data)


@router.get("/uploads", summary="List the caller's uploads")
def list_uploads(
    request: Request,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    kind: str | None = Query(default=None, max_length=40),
    include_pending: bool = Query(default=False),
):
    """Owner-scoped uploads (newest first) with short-lived preview/download URLs."""
    request_id = base.get_task_id(request)
    with get_session() as session:
        user = resolve_principal(request, session, request_id)
        data = service.list_uploads(
            session,
            user_id=str(user.id),
            limit=limit,
            offset=offset,
            kind=(kind or "").strip() or None,
            include_pending=include_pending,
        )
    return utils.get_response(200, data)


@router.delete("/uploads/{asset_id}", summary="Delete one of the caller's uploads")
def delete_upload(request: Request, asset_id: str = Path(..., max_length=64)):
    request_id = base.get_task_id(request)
    try:
        with get_session() as session:
            user = resolve_principal(request, session, request_id)
            key = service.delete_upload(session, user_id=str(user.id), asset_id=asset_id)
    except service.MediaDomainError as exc:
        raise _domain_error(exc, request_id) from exc
    removed = service.delete_stored_object(key)
    if not removed:
        logger.warning(f"upload object cleanup failed for {key!r}, request_id: {request_id}")
    return utils.get_response(200, {"id": asset_id, "deleted": True, "storage_removed": removed})
