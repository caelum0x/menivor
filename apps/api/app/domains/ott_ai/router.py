"""AI panel routes (MV16). 404 until OTT_ENABLED and OTT_AI_LIVE.

* ``POST /api/v1/ott/studio/titles/{id}/ai``   subtitles, chapters, metadata or dubs for a title (queued)
* ``GET  /api/v1/ott/studio/titles/{id}/ai``   what is done, with chapters and metadata suggestions
* ``GET  /api/v1/ott/titles/{id}/chapters``    chapters for players (public, cached)
"""

from __future__ import annotations

from fastapi import Depends, Path, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.domains.ott import catalog_public, flags, roles
from app.domains.ott.models import OttChannel, OttTitle
from app.models.exception import HttpException
from app.utils import utils

from . import pipeline
from .models import DONE, OttAiOutput

router = new_router()
_AI = [Depends(flags.require("ai"))]


class AiRequest(BaseModel):
    kinds: list[str] = Field(..., min_length=1, max_length=4)
    languages: list[str] = Field(default_factory=list, max_length=8)
    source_language: str = Field("en", max_length=12)


def enqueue(title_id: str, source_language: str) -> None:
    from .tasks import run_ai_task

    run_ai_task.apply_async(args=[title_id, source_language], queue="render_bulk")


def _title_for(session, request: Request, request_id: str, title_id: str) -> OttTitle:
    user = _resolve_user(request, session, request_id)
    title = session.get(OttTitle, title_id)
    channel = session.get(OttChannel, title.channel_id) if title is not None else None
    if title is None or channel is None or not roles.can(session, str(user.id), channel, "use_ai"):
        raise HttpException(task_id=request_id, status_code=404, message="title not found")
    return title


@router.post("/ott/studio/titles/{title_id}/ai", dependencies=_AI, summary="Run the AI panel on a title")
def request_ai(request: Request, body: AiRequest, title_id: str = Path(..., max_length=32)):
    from app.services.billing import ott_plans

    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        title = _title_for(session, request, request_id, title_id)
        channel = session.get(OttChannel, title.channel_id)
        try:
            if flags.enabled("plans"):
                ott_plans.require_under_cap(session, str(channel.user_id), "ai_minutes")
            pipeline.queue(session, title, body.kinds, body.languages, body.source_language)
        except (pipeline.AiError, ott_plans.OttPlanError) as exc:
            raise HttpException(task_id=request_id, status_code=exc.status_code, message=str(exc),
                                data={"code": exc.code}) from exc
        view = pipeline.view(session, title)
    enqueue(title_id, body.source_language)
    return utils.get_response(200, view)


@router.get("/ott/studio/titles/{title_id}/ai", dependencies=_AI, summary="AI panel results for a title")
def get_ai(request: Request, title_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        return utils.get_response(200, pipeline.view(session, _title_for(session, request, request_id, title_id)))


@router.get("/ott/titles/{title_id}/chapters", dependencies=_AI, summary="Chapters of a title (public)")
def public_chapters(request: Request, response: Response, title_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        title = session.get(OttTitle, title_id)
        if not catalog_public.watchable(session, title):
            raise HttpException(task_id=request_id, status_code=404, message="title not found")
        row = session.execute(select(OttAiOutput).where(OttAiOutput.title_id == title_id,
                                                        OttAiOutput.kind == "chapters",
                                                        OttAiOutput.status == DONE)).scalars().first()
        chapters = (row.data or {}).get("chapters", []) if row else []
    response.headers["Cache-Control"] = "public, max-age=60, s-maxage=300"
    return utils.get_response(200, {"chapters": chapters})
