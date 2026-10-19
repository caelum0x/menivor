"""OTT creator studio routes (MV1). Signed in; every route 404s until OTT_ENABLED and OTT_CMS_LIVE.

* ``GET   /api/v1/ott/studio``                         my channel, titles, series, rails
* ``POST  /api/v1/ott/studio/publish-all``             one click: my finished reels become a live channel
* ``PATCH /api/v1/ott/studio/channel``                 name, handle, layout, colours
* ``POST  /api/v1/ott/studio/titles``                  add finished renders as titles
* ``PATCH /api/v1/ott/studio/titles/{id}``             metadata, availability, access, geo
* ``POST  /api/v1/ott/studio/titles/{id}/publish``     publish (compliance gate)
* ``POST  /api/v1/ott/studio/titles/{id}/unpublish``   hide at once
* ``POST  /api/v1/ott/studio/series``, ``/collections``
"""

from __future__ import annotations

from fastapi import Depends, Path, Request

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.utils import utils

from . import flags, publish, service
from .schemas import AddTitles, ChannelUpdate, CollectionCreate, PublishAll, SeriesCreate, TitleUpdate

router = new_router()
_CMS = [Depends(flags.require("cms"))]


def _http(exc: service.OttError, request_id: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=exc.status_code, message=f"{request_id}: {exc}",
                         data={"code": exc.code})


def _run(request: Request, fn):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            return utils.get_response(200, fn(session, str(user.id)))
        except service.OttError as exc:
            raise _http(exc, request_id) from exc


@router.get("/ott/studio", dependencies=_CMS, summary="My channel, titles, series and rails")
def get_studio(request: Request):
    return _run(request, lambda s, uid: service.channel_view(s, service.ensure_channel(s, uid)))


@router.post("/ott/studio/publish-all", dependencies=_CMS, summary="Publish my finished reels as a channel")
def publish_all(request: Request, body: PublishAll):
    return _run(request, lambda s, uid: publish.publish_all(s, uid, limit=body.limit))


@router.patch("/ott/studio/channel", dependencies=_CMS, summary="Edit my channel")
def patch_channel(request: Request, body: ChannelUpdate):
    return _run(request, lambda s, uid: service.channel_view(
        s, service.update_channel(s, uid, body.model_dump(exclude_none=True))))


@router.post("/ott/studio/titles", dependencies=_CMS, summary="Add finished renders as titles")
def add_titles(request: Request, body: AddTitles):
    return _run(request, lambda s, uid: {"titles": [service.title_view(service.add_title(s, uid, j))
                                                    for j in body.job_ids]})


@router.patch("/ott/studio/titles/{title_id}", dependencies=_CMS, summary="Edit a title")
def patch_title(request: Request, body: TitleUpdate, title_id: str = Path(..., max_length=32)):
    return _run(request, lambda s, uid: service.title_view(
        service.update_title(s, uid, title_id, body.model_dump(exclude_none=True))))


@router.post("/ott/studio/titles/{title_id}/publish", dependencies=_CMS, summary="Publish a title")
def publish_title(request: Request, title_id: str = Path(..., max_length=32)):
    return _run(request, lambda s, uid: service.title_view(service.publish_title(s, uid, title_id)))


@router.post("/ott/studio/titles/{title_id}/unpublish", dependencies=_CMS, summary="Hide a title now")
def unpublish_title(request: Request, title_id: str = Path(..., max_length=32)):
    return _run(request, lambda s, uid: service.title_view(service.unpublish_title(s, uid, title_id)))


@router.post("/ott/studio/series", dependencies=_CMS, summary="Create a series")
def create_series(request: Request, body: SeriesCreate):
    def make(s, uid):
        row = service.create_series(s, uid, body.title, body.synopsis)
        return {"id": row.id, "title": row.title}

    return _run(request, make)


@router.post("/ott/studio/collections", dependencies=_CMS, summary="Create a home rail")
def create_collection(request: Request, body: CollectionCreate):
    def make(s, uid):
        row = service.create_collection(s, uid, body.title, body.title_ids)
        return {"id": row.id, "title": row.title, "title_ids": list(row.title_ids)}

    return _run(request, make)
