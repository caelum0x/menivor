"""Gallery routes (MH3).

Public (edge-cached for 30 s, so a takedown is gone from caches within 60 s):
* ``GET  /api/v1/gallery``                    opt-in items, newest first
* ``GET  /api/v1/gallery/wall``               up to 6 owner-approved items for the landing wall
* ``GET  /api/v1/gallery/{id}``               one item

Signed in:
* ``POST   /api/v1/gallery``                  publish your own finished, kept output
* ``DELETE /api/v1/gallery/{id}``             unpublish your item
* ``POST   /api/v1/gallery/{id}/recreate``    the Create body with the item's settings and your topic
* ``POST   /api/v1/gallery/{id}/remixes``     link the job you made with Recreate
* ``GET    /api/v1/gallery/remixes/{job_id}`` whether that remix has counted

Staff:
* ``POST /api/v1/admin/gallery/{id}/wall``    approve an item for the landing wall
"""

from __future__ import annotations

from fastapi import Path, Request, Response
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.utils import utils

from . import service

router = new_router()
CACHE_CONTROL = "public, max-age=15, s-maxage=30"


class PublishRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=32)
    title: str = Field("", max_length=200)


class RecreateRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=600)
    image_key: str | None = Field(default=None, max_length=512)


class RemixRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=32)


class WallRequest(BaseModel):
    approved: bool = True


def _raise(exc: service.GalleryError, request_id: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=exc.status_code, message=f"{request_id}: {exc}",
                         data={"code": exc.code})


def _require_staff(request: Request, request_id: str) -> None:
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        if not bool(getattr(user, "is_staff", False)):
            raise HttpException(task_id=request_id, status_code=403, message="staff access required")


@router.get("/gallery", summary="Gallery of opt-in outputs (public)")
def list_gallery(request: Request, response: Response):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        items = service.list_public(session)
    response.headers["Cache-Control"] = CACHE_CONTROL
    return utils.get_response(200, {"items": items})


@router.get("/gallery/wall", summary="Owner-approved gallery items for the landing wall (public)")
def gallery_wall(request: Request, response: Response):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        items = service.wall(session)
    response.headers["Cache-Control"] = CACHE_CONTROL
    return utils.get_response(200, {"items": items})


@router.get("/gallery/remixes/{job_id}", summary="Whether a Recreate remix has counted")
def get_remix(request: Request, job_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            view = service.remix_view(session, user_id=str(user.id), job_id=job_id)
        except service.GalleryError as exc:
            raise _raise(exc, request_id) from exc
    return utils.get_response(200, view)


@router.get("/gallery/{item_id}", summary="One gallery item (public)")
def get_item(request: Request, response: Response, item_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        try:
            view = service.get_public(session, item_id)
        except service.GalleryError as exc:
            raise _raise(exc, request_id) from exc
    response.headers["Cache-Control"] = CACHE_CONTROL
    return utils.get_response(200, view)


@router.post("/gallery", summary="Publish your own finished output (opt-in)")
def publish_item(request: Request, body: PublishRequest):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            item = service.publish(session, user_id=str(user.id), job_id=body.job_id, title=body.title)
        except service.GalleryError as exc:
            raise _raise(exc, request_id) from exc
        data = {"id": item.id, "job_id": item.job_id, "preset_id": item.preset_id, "title": item.title}
    return utils.get_response(200, data)


@router.delete("/gallery/{item_id}", summary="Unpublish your gallery item")
def unpublish_item(request: Request, item_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            service.unpublish(session, user_id=str(user.id), item_id=item_id)
        except service.GalleryError as exc:
            raise _raise(exc, request_id) from exc
    return utils.get_response(200, {"id": item_id, "published": False})


@router.post("/gallery/{item_id}/recreate", summary="Create prefilled from a gallery item")
def recreate(request: Request, body: RecreateRequest, item_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        _resolve_user(request, session, request_id)
        try:
            plan = service.recreate_plan(session, item_id, subject=body.subject, image_key=body.image_key)
        except service.GalleryError as exc:
            raise _raise(exc, request_id) from exc
    return utils.get_response(200, plan)


@router.post("/gallery/{item_id}/remixes", summary="Link the job you made with Recreate")
def link_remix(request: Request, body: RemixRequest, item_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            remix = service.link_remix(session, item_id=item_id, user_id=str(user.id), job_id=body.job_id)
        except service.GalleryError as exc:
            raise _raise(exc, request_id) from exc
        data = {"item_id": remix.item_id, "job_id": remix.job_id}
    return utils.get_response(200, data)


@router.post("/admin/gallery/{item_id}/wall", tags=["Admin"], summary="Approve a gallery item for the wall (staff)")
def approve_wall(request: Request, body: WallRequest, item_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_staff(request, request_id)
    with get_session() as session:
        try:
            service.set_wall(session, item_id, body.approved)
        except service.GalleryError as exc:
            raise _raise(exc, request_id) from exc
    return utils.get_response(200, {"id": item_id, "wall_approved": body.approved})
