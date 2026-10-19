"""Discovery routes (MV19). 404 until OTT_ENABLED and OTT_DISCOVERY_LIVE.

* ``GET  /api/v1/ott/search?q=&channel=``    search published titles (public, cached 30 s)
* ``POST /api/v1/ott/titles/{id}/ask``        ask this video; answers cite a time or say they do not know
* ``GET  /api/v1/ott/titles/{id}/related``    titles like this one on the same channel (public, cached 60 s)
"""

from __future__ import annotations

from fastapi import Depends, Path, Query, Request, Response
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, get_session
from app.domains.ott import catalog_public, flags
from app.domains.ott.models import OttTitle
from app.domains.ott_access import geo
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

from . import ask as asking, search as searching

router = new_router()
_LIVE = [Depends(flags.require("discovery"))]
ASK_LIMIT = 10


class Question(BaseModel):
    question: str = Field(..., min_length=3, max_length=300)


@router.get("/ott/search", dependencies=_LIVE, summary="Search titles (public)")
def search(request: Request, response: Response, q: str = Query(..., min_length=2, max_length=200),
           channel: str = Query("", max_length=40)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        channel_id = None
        if channel:
            row = catalog_public.channel_by_handle(session, channel)
            if row is None:
                raise HttpException(task_id=request_id, status_code=404, message="channel not found")
            channel_id = row.id
        data = searching.search(session, q, channel_id=channel_id, country=geo.country(request.headers))
    response.headers["Cache-Control"] = "public, max-age=15, s-maxage=30"
    response.headers["Vary"] = "CF-IPCountry"
    return utils.get_response(200, data)


@router.get("/ott/titles/{title_id}/related", dependencies=_LIVE, summary="Titles like this one (public)")
def related(request: Request, response: Response, title_id: str = Path(..., max_length=32),
            limit: int = Query(searching.RELATED_LIMIT, ge=1, le=24)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        try:
            data = searching.related(session, title_id, limit=limit, country=geo.country(request.headers))
        except searching.NotFound as exc:
            raise HttpException(task_id=request_id, status_code=404, message="title not found") from exc
    response.headers["Cache-Control"] = "public, max-age=30, s-maxage=60"
    response.headers["Vary"] = "CF-IPCountry"
    return utils.get_response(200, data)


def _may_watch(request: Request, session, request_id: str, title: OttTitle) -> bool:
    from app.domains.ott_access import router as access_router, service as access
    from app.domains.ott_viewers import session as viewer_session

    user_id = access_router._optional_user(request, session, request_id)
    account = viewer_session.from_request(session, request)
    return access.has_access(session, title, user_id, account.id if account is not None else None)


@router.post("/ott/titles/{title_id}/ask", dependencies=_LIVE, summary="Ask this video")
def ask(request: Request, body: Question, title_id: str = Path(..., max_length=32)):
    enforce_rate_limit(request, "ott:ask", ASK_LIMIT, 60)
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        title = session.get(OttTitle, title_id)
        if not catalog_public.watchable(session, title):
            raise HttpException(task_id=request_id, status_code=404, message="title not found")
        if title.access_tier != "free" and not _may_watch(request, session, request_id, title):
            # Verifier fix: answers quote the transcript, so a paid title needs the same access as playback.
            raise HttpException(task_id=request_id, status_code=402, message="This title is for members of the channel.",
                                data={"code": "members_only"})
        try:
            return utils.get_response(200, asking.ask(session, title, body.question))
        except asking.AskError as exc:
            raise HttpException(task_id=request_id, status_code=exc.status_code, message=str(exc),
                                data={"code": exc.code}) from exc
