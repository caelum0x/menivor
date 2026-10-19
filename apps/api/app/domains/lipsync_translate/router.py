"""Lip-sync translation HTTP surface (owner-scoped).

    GET  /translate/options     languages, engines, my videos and my actors with designed voices
    POST /translate/plan        price a translation into one or more languages (planned render, $0)

Submitting for approval is ``POST /studio-renders/{id}/submit``; approving in the
approvals feed spends the AI-video credits and starts the worker.
"""

from __future__ import annotations

from typing import Literal

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session
from app.domains._http import Call
from app.domains.lipsync_translate import engines, languages, pipeline
from app.domains.studio_render.service import RenderError
from app.utils import utils

router = new_router()
_ERRORS = (pipeline.TranslateError, RenderError)


class PlanBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # no voice samples or other extras, ever

    video_url: str = Field(..., min_length=8, max_length=2000)
    actor_id: str = Field(..., min_length=1, max_length=32)
    targets: list[str] = Field(..., min_length=1, max_length=languages.MAX_TARGETS)
    seconds: float = Field(..., gt=0, le=pipeline.MAX_SECONDS)
    source_language: str = Field(default="en", max_length=4)
    engine: Literal["kling", "infinitetalk"] = "kling"
    captions: bool = True
    transcript: str = Field(default="", max_length=8000)


@router.get("/translate/options", summary="Languages, lip-sync engines, my videos and designed voices")
def options(request: Request):
    from sqlalchemy import select

    from app.domains.actors.models import AiActor
    from app.domains.brand_agent.models import AgentLibraryItem

    with Call(request, _ERRORS, "", get_session) as (session, user_id):
        videos = session.execute(select(AgentLibraryItem).where(
            AgentLibraryItem.user_id == user_id, AgentLibraryItem.kind == "video", AgentLibraryItem.url != "")
            .order_by(AgentLibraryItem.created_at.desc()).limit(50)).scalars().all()
        actors = session.execute(select(AiActor).where(AiActor.user_id == user_id)).scalars().all()
        return utils.get_response(200, {
            "languages": languages.catalog(),
            "engines": [{"id": e, "label": "Kling lip-sync" if e == "kling" else "InfiniteTalk (RunPod)",
                         "configured": engines.configured(e)} for e in engines.ENGINES],
            "videos": [{"id": v.id, "title": v.title, "url": v.url} for v in videos],
            "voices": [{"actor_id": a.id, "name": a.name, "ready": bool(a.voice_id)} for a in actors],
            "rules": ["Only your own videos.", "Only your AI actors' designed voices; no voice is ever cloned."],
        })


@router.post("/translate/plan", summary="Price a lip-sync translation (nothing is spent)")
def make_plan(request: Request, body: PlanBody):
    with Call(request, _ERRORS, "translate:plan", get_session, limit=120) as (session, user_id):
        return utils.get_response(200, {"render": pipeline.plan(session, user_id, **body.model_dump())})


__all__ = ["router"]
