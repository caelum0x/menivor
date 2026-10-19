"""FAST channel routes (MV15). 404 until OTT_ENABLED and OTT_FAST_LIVE.

* ``GET  /api/v1/ott/studio/linear``               my linear channels
* ``POST /api/v1/ott/studio/linear``               create or change one (titles in order, ad break every N)
* ``GET  /api/v1/ott/linear/{slug}/now``           what is on now and next (public)
* ``GET  /api/v1/ott/linear/{slug}/epg.xml``       XMLTV guide for the next 24 h (public)
* ``GET  /api/v1/ott/linear/{slug}/items/{n}``     the playout engine's n-th item (engine key)
"""

from __future__ import annotations

from fastapi import Depends, Path, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.domains.ott import flags
from app.domains.ott.service import ensure_channel
from app.domains.ott_live.models import OttLinearChannel
from app.models.exception import HttpException
from app.utils import utils

from . import service

router = new_router()
_FAST = [Depends(flags.require("fast"))]
PUBLIC_CACHE = "public, max-age=15, s-maxage=30"
EPG_CACHE = "public, max-age=300, s-maxage=600"


class LinearSave(BaseModel):
    slug: str | None = Field(None, max_length=40)
    name: str | None = Field(None, max_length=80)
    title_ids: list[str] = Field(..., min_length=1, max_length=200)
    ad_break_every: int = Field(0, ge=0, le=20)


def _http(exc: service.LinearError, request_id: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=exc.status_code, message=str(exc), data={"code": exc.code})


@router.get("/ott/studio/linear", dependencies=_FAST, summary="My linear channels")
def mine(request: Request):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        channel = ensure_channel(session, str(_resolve_user(request, session, request_id).id))
        rows = session.execute(select(OttLinearChannel).where(OttLinearChannel.channel_id == channel.id)).scalars()
        return utils.get_response(200, {"linear": [service.view(r) for r in rows]})


@router.post("/ott/studio/linear", dependencies=_FAST, summary="Create or change a linear channel")
def save(request: Request, body: LinearSave):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        channel = ensure_channel(session, str(_resolve_user(request, session, request_id).id))
        try:
            return utils.get_response(200, service.view(service.save(session, channel, body.model_dump())))
        except service.LinearError as exc:
            raise _http(exc, request_id) from exc


def _public(request: Request, slug: str, fn):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        try:
            return fn(session, service.by_slug(session, slug))
        except service.LinearError as exc:
            raise _http(exc, request_id) from exc


@router.get("/ott/linear/{slug}/now", dependencies=_FAST, summary="On now and next (public)")
def on_now(request: Request, response: Response, slug: str = Path(..., max_length=40)):
    data = _public(request, slug, lambda s, row: service.now_playing(s, row))
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return utils.get_response(200, data)


@router.get("/ott/linear/{slug}/epg.xml", dependencies=_FAST, summary="XMLTV guide (public)")
def guide(request: Request, slug: str = Path(..., max_length=40)):
    body = _public(request, slug, lambda s, row: service.epg(s, row))
    return Response(content=body, media_type="application/xml", headers={"Cache-Control": EPG_CACHE})


@router.get("/ott/linear/{slug}/items/{index}", dependencies=_FAST, summary="Playout engine: the n-th item")
def engine_item(request: Request, slug: str = Path(..., max_length=40), index: int = Path(..., ge=0)):
    request_id = base.get_task_id(request)
    try:
        service.check_engine(request.headers.get("x-engine-key") or "")
    except service.LinearError as exc:
        raise _http(exc, request_id) from exc
    data = _public(request, slug, lambda s, row: service.engine_item(s, row, index))
    return utils.get_response(200, data)
