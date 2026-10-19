"""OTT upload and transcode-lane routes (MV2/MV3).

Creator (signed in; 404 until OTT_ENABLED and OTT_UPLOAD_LIVE):
* ``POST /api/v1/ott/uploads``            start a resumable multipart upload to R2
* ``POST /api/v1/ott/uploads/parts``      presigned URLs for some part numbers (resume any time)
* ``POST /api/v1/ott/uploads/complete``   finish it; a draft title is created and queued for packaging
* ``POST /api/v1/ott/uploads/abort``

Every upload passes the per-user quota (402 with an upgrade path) and the
content check before it can publish (Wave Q QM1.2). Staff:
``GET /api/v1/admin/ott/upload-checks`` and ``POST .../{title_id}/review``.

Creator (404 until OTT_PACKAGING_LIVE):
* ``POST /api/v1/ott/studio/titles/{id}/package``   queue a reel title for the CMAF ladder
* ``GET  /api/v1/ott/studio/titles/{id}/package``   lane, node, CPU seconds and cost of the latest job

Nodes (bearer node token; 404 until OTT_PACKAGING_LIVE): ``/api/v1/ott/nodes/...``.
Staff: ``POST /api/v1/admin/ott/nodes`` registers a node and shows its token once.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import Depends, Path, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.domains.ott import flags
from app.domains.ott.models import OttTitle
from app.models.exception import HttpException
from app.utils import utils

from . import mac_node, nodes, service, uploads
from .models import LANE_BOX1, OttEncodeJob

router = new_router()
_UPLOAD = [Depends(flags.require("upload"))]
_PACKAGING = [Depends(flags.require("packaging"))]
API_BASE_ENV = "MENIVOR_PUBLIC_API_BASE"


class SourceStorage:
    """``ott:<key>`` lives in the OTT bucket; ``r2:<key>`` is a finished reel in the media bucket."""

    def __init__(self, ott: Any | None = None) -> None:
        self._ott = ott

    @property
    def ott(self) -> Any:
        if self._ott is None:
            self._ott = uploads.R2Storage()
        return self._ott

    def presign_get(self, key: str, ttl_s: int) -> str:
        scheme, _, path = key.partition(":")
        if scheme == "r2":
            from app.platform.storage.r2 import get_r2_client

            return get_r2_client().presign_result_get(path)
        return self.ott.presign_get(path, ttl_s)

    def presign_put(self, key: str, content_type: str, ttl_s: int) -> str:
        return self.ott.presign_put(key, content_type, ttl_s)


def storage() -> SourceStorage:
    return SourceStorage()


def enqueue_box1(job_id: str) -> None:
    from app.workers.tasks_ott import box1_queue, package_on_box1_task

    package_on_box1_task.apply_async(args=[job_id], queue=box1_queue())


def api_base() -> str:
    return (os.getenv(API_BASE_ENV) or "https://api.menivor.com").rstrip("/")


def _http(exc: Exception, request_id: str) -> HttpException:
    status = getattr(exc, "status_code", 400)
    return HttpException(task_id=request_id, status_code=status, message=f"{request_id}: {exc}",
                         data={"code": getattr(exc, "code", "error")})


# --------------------------------------------------------------------------- #
# Uploads
# --------------------------------------------------------------------------- #
class UploadStart(BaseModel):
    filename: str = Field(..., min_length=1, max_length=200)
    size_bytes: int = Field(..., gt=0)
    content_type: str = Field(..., max_length=60)
    seconds: float | None = Field(None, gt=0, le=6 * 3600)


class UploadParts(BaseModel):
    key: str = Field(..., max_length=512)
    upload_id: str = Field(..., max_length=1024)
    part_numbers: list[int] = Field(..., min_length=1, max_length=500)


class UploadPart(BaseModel):
    PartNumber: int = Field(..., ge=1, le=uploads.MAX_PARTS)
    ETag: str = Field(..., max_length=200)


class UploadComplete(BaseModel):
    key: str = Field(..., max_length=512)
    upload_id: str = Field(..., max_length=1024)
    parts: list[UploadPart] = Field(..., min_length=1, max_length=uploads.MAX_PARTS)
    title: str = Field(..., min_length=1, max_length=120)
    kind: str = Field("episode", max_length=16)
    seconds: float = Field(..., gt=0, le=6 * 3600)
    short_side: int = Field(..., ge=0, le=4320)
    size_bytes: int = Field(0, ge=0)


class UploadAbort(BaseModel):
    key: str = Field(..., max_length=512)
    upload_id: str = Field(..., max_length=1024)


def _ott_caps_check(session, user_id: str, request_id: str) -> None:
    from app.services.billing import ott_plans

    if not flags.enabled("plans"):
        return
    for meter in ("encode_minutes", "gb_stored"):
        try:
            ott_plans.require_under_cap(session, user_id, meter)
        except ott_plans.OttPlanError as exc:
            raise _http(exc, request_id) from exc


def _user(request: Request, session, request_id: str) -> str:
    return str(_resolve_user(request, session, request_id).id)


def _quota_http(exc: uploads.QuotaExceeded, request_id: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=402, message=f"{request_id}: {exc}",
                         data={"code": exc.code, "upgrade_url": exc.upgrade_url})


def enqueue_upload_check(title_id: str) -> None:
    """Queue the content check (QM1.2); the gate sweep re-queues it if this send is lost."""
    from app.domains.ott.tasks import upload_check_task

    try:
        upload_check_task.apply_async(args=[title_id])
    except Exception as exc:  # noqa: BLE001 - the pending row stays and the sweep retries
        from loguru import logger

        logger.warning(f"upload check for {title_id} not queued now: {exc}")


@router.post("/ott/uploads", dependencies=_UPLOAD, summary="Start a resumable upload")
def start_upload(request: Request, body: UploadStart):
    import uuid

    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user_id = _user(request, session, request_id)
        _ott_caps_check(session, user_id, request_id)  # Wave P PM3.1 (MV7): caps without an overage opt-in
        try:
            # Wave Q QM1.2 (P-M6): the per-user quota applies whatever the plans flag says.
            uploads.require_quota(session, user_id, paid=service.paid_plan(user_id), add_bytes=body.size_bytes,
                                  add_seconds=body.seconds or 0.0)
        except uploads.QuotaExceeded as exc:
            raise _quota_http(exc, request_id) from exc
    try:
        parts = uploads.check_start(body.size_bytes, body.content_type)
    except uploads.UploadError as exc:
        raise _http(exc, request_id) from exc
    key = uploads.upload_key(user_id, uuid.uuid4().hex, body.filename)
    upload_id = storage().ott.create(key, body.content_type)
    return utils.get_response(200, {"key": key, "upload_id": upload_id, "part_size": uploads.PART_BYTES,
                                    "parts": parts})


@router.post("/ott/uploads/parts", dependencies=_UPLOAD, summary="Presigned URLs for upload parts")
def upload_parts(request: Request, body: UploadParts):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user_id = _user(request, session, request_id)
    if not uploads.owns(body.key, user_id):
        raise HttpException(task_id=request_id, status_code=404, message=f"{request_id}: upload not found")
    store = storage().ott
    urls = {str(n): store.part_url(body.key, body.upload_id, n) for n in sorted(set(body.part_numbers))
            if 1 <= n <= uploads.MAX_PARTS}
    return utils.get_response(200, {"urls": urls})


@router.post("/ott/uploads/complete", dependencies=_UPLOAD, summary="Finish an upload and queue it")
def complete_upload(request: Request, body: UploadComplete):
    from app.domains.ott import service as ott_service
    from app.domains.ott.models import KINDS

    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user_id = _user(request, session, request_id)
        if not uploads.owns(body.key, user_id):
            raise HttpException(task_id=request_id, status_code=404, message=f"{request_id}: upload not found")
        if body.kind not in KINDS:
            raise HttpException(task_id=request_id, status_code=400, message=f"{request_id}: unknown kind")
        ceiling = len(body.parts) * uploads.PART_BYTES
        size = min(body.size_bytes, ceiling) if body.size_bytes else ceiling
        paid = service.paid_plan(user_id)
        uploads.lock_quota(session, user_id)  # QM verify: parallel completes cannot share one headroom
        store = storage().ott
        try:
            uploads.require_quota(session, user_id, paid=paid, add_bytes=size, add_seconds=body.seconds)
        except uploads.QuotaExceeded as exc:
            store.abort(body.key, body.upload_id)  # nothing past the quota is kept
            raise _quota_http(exc, request_id) from exc
        store.complete(body.key, body.upload_id, [p.model_dump() for p in sorted(body.parts,
                                                                                key=lambda p: p.PartNumber)])
        # QM verify: the quota counts the bytes actually stored, not the size the client reported.
        size = uploads.measured_size(store, body.key, size)
        try:
            uploads.require_quota(session, user_id, paid=paid, add_bytes=size, add_seconds=body.seconds)
        except uploads.QuotaExceeded as exc:
            delete = getattr(store, "delete", None)
            if callable(delete):
                delete(body.key)
            raise _quota_http(exc, request_id) from exc
        channel = ott_service.ensure_channel(session, user_id)
        try:
            ott_service._vendor_check(body.title)
        except ott_service.OttError as exc:
            raise _http(exc, request_id) from exc
        title = OttTitle(channel_id=channel.id, kind=body.kind, source_key=f"ott:{body.key}", title=body.title,
                         duration_s=body.seconds, genres=[], geo_countries=[])
        session.add(title)
        session.flush()
        from app.domains.ott import upload_check

        check = upload_check.record_upload(session, title, user_id=user_id, size_bytes=size, seconds=body.seconds)
        job = service.submit(session, title, source_key=f"ott:{body.key}", seconds=body.seconds,
                             short_side=body.short_side, user_id=user_id)
        view = {"title_id": title.id, "job": service.job_view(job), "check": upload_check.check_view(check)}
        lane, job_id, title_id = job.lane, job.id, title.id
    enqueue_upload_check(title_id)
    if lane == LANE_BOX1:
        enqueue_box1(job_id)
    return utils.get_response(200, view)


@router.post("/ott/uploads/abort", dependencies=_UPLOAD, summary="Cancel an upload")
def abort_upload(request: Request, body: UploadAbort):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user_id = _user(request, session, request_id)
    if not uploads.owns(body.key, user_id):
        raise HttpException(task_id=request_id, status_code=404, message=f"{request_id}: upload not found")
    storage().ott.abort(body.key, body.upload_id)
    return utils.get_response(200, {"aborted": True})


# --------------------------------------------------------------------------- #
# Packaging a reel title
# --------------------------------------------------------------------------- #
def _own_title(session, user_id: str, title_id: str) -> OttTitle:
    from app.domains.ott.repository import OttRepository

    channel = OttRepository(session).channel_for_user(user_id)
    title = OttRepository(session).title(channel.id, title_id) if channel else None
    if title is None:
        raise service.TranscodeError(404, "not_found", "title not found")
    return title


@router.post("/ott/studio/titles/{title_id}/package", dependencies=_PACKAGING, summary="Package a title")
def package_title(request: Request, title_id: str = Path(..., max_length=32)):
    from app.models.db.models import Job

    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user_id = _user(request, session, request_id)
        try:
            title = _own_title(session, user_id, title_id)
            if not title.source_job_id:
                raise service.TranscodeError(409, "no_source", "uploads are queued when they finish")
            reel = session.get(Job, title.source_job_id)
            seconds = float(title.duration_s or dict(reel.params or {}).get("target_duration_s") or 60)
            job = service.submit(session, title, source_key=f"r2:{reel.result_key}", seconds=seconds,
                                 short_side=720, user_id=user_id)
        except service.TranscodeError as exc:
            raise _http(exc, request_id) from exc
        view, lane, job_id = service.job_view(job), job.lane, job.id
    if lane == LANE_BOX1:
        enqueue_box1(job_id)
    return utils.get_response(200, view)


@router.get("/ott/studio/titles/{title_id}/package", dependencies=_PACKAGING, summary="Latest packaging job")
def get_package(request: Request, title_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user_id = _user(request, session, request_id)
        try:
            title = _own_title(session, user_id, title_id)
        except service.TranscodeError as exc:
            raise _http(exc, request_id) from exc
        job = session.execute(select(OttEncodeJob).where(OttEncodeJob.title_id == title.id)
                              .order_by(OttEncodeJob.created_at.desc()).limit(1)).scalars().first()
        view = service.job_view(job) if job else None
    return utils.get_response(200, {"job": view})


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #
class Heartbeat(BaseModel):
    free_gb: float = Field(..., ge=0)
    cores: int = Field(0, ge=0, le=512)


class Files(BaseModel):
    files: list[str] = Field(..., min_length=1, max_length=mac_node.MAX_FILES)


class Complete(Files):
    cpu_seconds: float = Field(..., ge=0)
    packager_sha256: str = Field(..., min_length=64, max_length=64)
    #: QM verify (h): the probed source length; billed instead of the declared one when present.
    measured_seconds: float | None = Field(None)


class Failed(BaseModel):
    error: str = Field(..., max_length=500)


class NodeCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    kind: str = Field(..., max_length=12)


def _node(request: Request, session, request_id: str):
    header = request.headers.get("authorization") or ""
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    node = nodes.authenticate(session, token)
    if node is None:
        raise HttpException(task_id=request_id, status_code=401, message=f"{request_id}: unknown node")
    return node


def _node_call(request: Request, fn):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        node = _node(request, session, request_id)
        try:
            return utils.get_response(200, fn(session, node))
        except service.TranscodeError as exc:
            raise _http(exc, request_id) from exc


@router.post("/ott/nodes/heartbeat", dependencies=_PACKAGING, summary="Node heartbeat (free space, cores)")
def node_heartbeat(request: Request, body: Heartbeat):
    return _node_call(request, lambda s, n: (nodes.heartbeat(s, n, free_gb=body.free_gb, cores=body.cores),
                                             {"live": nodes.is_live(n)})[1])


@router.post("/ott/nodes/claim", dependencies=_PACKAGING, summary="Claim the next job for this node")
def node_claim(request: Request):
    return _node_call(request, lambda s, n: {"job": mac_node.claim(s, n, storage(), api_base=api_base())})


@router.post("/ott/nodes/jobs/{job_id}/progress", dependencies=_PACKAGING, summary="Job still running")
def node_progress(request: Request, job_id: str = Path(..., max_length=32)):
    return _node_call(request, lambda s, n: (mac_node.progress(s, n, job_id), {"ok": True})[1])


@router.post("/ott/nodes/jobs/{job_id}/upload-urls", dependencies=_PACKAGING, summary="PUT URLs for outputs")
def node_upload_urls(request: Request, body: Files, job_id: str = Path(..., max_length=32)):
    return _node_call(request, lambda s, n: {"urls": mac_node.upload_urls(s, n, job_id, body.files, storage())})


@router.post("/ott/nodes/jobs/{job_id}/complete", dependencies=_PACKAGING, summary="Job finished")
def node_complete(request: Request, body: Complete, job_id: str = Path(..., max_length=32)):
    return _node_call(request, lambda s, n: mac_node.complete(s, n, job_id, cpu_seconds=body.cpu_seconds,
                                                              packager_sha256=body.packager_sha256,
                                                              files=body.files,
                                                              measured_seconds=body.measured_seconds))


@router.post("/ott/nodes/jobs/{job_id}/fail", dependencies=_PACKAGING, summary="Job failed on the node")
def node_fail(request: Request, body: Failed, job_id: str = Path(..., max_length=32)):
    return _node_call(request, lambda s, n: mac_node.failed(s, n, job_id, body.error))


@router.post("/admin/ott/nodes", tags=["Admin"], summary="Register a transcode node (staff; token shown once)")
def create_node(request: Request, body: NodeCreate):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        if not bool(getattr(user, "is_staff", False)):
            raise HttpException(task_id=request_id, status_code=403, message="staff access required")
        try:
            node, token = nodes.register(session, body.name, body.kind)
        except ValueError as exc:
            raise HttpException(task_id=request_id, status_code=400, message=f"{request_id}: {exc}") from exc
        return utils.get_response(200, {"id": node.id, "kind": node.kind, "token": token})


# --------------------------------------------------------------------------- #
# Upload review queue (Wave Q QM1.2): staff approve or reject held uploads
# --------------------------------------------------------------------------- #
class Review(BaseModel):
    approve: bool


def _staff(request: Request, session, request_id: str) -> str:
    user = _resolve_user(request, session, request_id)
    if not bool(getattr(user, "is_staff", False)):
        raise HttpException(task_id=request_id, status_code=403, message="staff access required")
    return str(user.id)


@router.get("/admin/ott/upload-checks", tags=["Admin"], dependencies=_UPLOAD, summary="Held uploads (staff)")
def held_uploads(request: Request):
    from app.domains.ott import upload_check

    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        _staff(request, session, request_id)
        return utils.get_response(200, {"items": upload_check.review_queue(session)})


@router.post("/admin/ott/upload-checks/{title_id}/review", tags=["Admin"], dependencies=_UPLOAD,
             summary="Approve or reject a held upload (staff)")
def review_upload(request: Request, body: Review, title_id: str = Path(..., max_length=32)):
    from app.domains.ott import upload_check

    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        staff_id = _staff(request, session, request_id)
        try:
            row = upload_check.review(session, title_id, approve=body.approve, staff_id=staff_id)
        except upload_check.CheckError as exc:
            raise _http(exc, request_id) from exc
        return utils.get_response(200, upload_check.check_view(row))
