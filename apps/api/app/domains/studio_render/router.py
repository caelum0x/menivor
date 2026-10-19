"""Studio renders HTTP surface: list, read, and send a priced render to the approvals feed.

    GET  /studio-renders               my renders (?kind=actor_shot|lipsync_translation)
    GET  /studio-renders/{id}
    POST /studio-renders/{id}/submit   queue for approval (approve in /approvals spends the credits)
"""

from __future__ import annotations

from fastapi import Path, Query, Request

from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session
from app.domains._http import Call
from app.domains.studio_render import models as _models  # noqa: F401  (registers tables)
from app.domains.studio_render import service
from app.utils import utils

router = new_router()
_ERRORS = (service.RenderError,)


def _id():
    return Path(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")


@router.get("/studio-renders", summary="My actor shots and lip-sync translations")
def list_renders(request: Request, kind: str = Query(default="", pattern=r"^(|actor_shot|lipsync_translation)$")):
    with Call(request, _ERRORS, "", get_session) as (session, user_id):
        return utils.get_response(200, {"renders": service.list_renders(session, user_id, kind or None)})


@router.get("/studio-renders/{render_id}", summary="One studio render")
def get_render(request: Request, render_id: str = _id()):
    with Call(request, _ERRORS, "", get_session) as (session, user_id):
        return utils.get_response(200, {"render": service.view(service.get(session, user_id, render_id))})


@router.post("/studio-renders/{render_id}/submit", summary="Send a priced render for approval (nothing spent yet)")
def submit(request: Request, render_id: str = _id()):
    with Call(request, _ERRORS, "renders:submit", get_session, limit=120) as (session, user_id):
        return utils.get_response(200, {"render": service.submit(session, user_id, render_id)})


__all__ = ["router"]
