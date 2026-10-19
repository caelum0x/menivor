"""Reel styles HTTP domain.

* ``GET /styles`` - the public one-click style catalog (no per-user data).
* ``POST /styles/hooks`` - write one opening hook per format of a style's hook
  family from a pasted page's extracted facts (authenticated, rate limited:
  it calls the LLM).
"""

from __future__ import annotations

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.domains.experiments.hook_styles import HookStyleError
from app.domains.styles.catalog import UnknownStyleError, list_styles, require_style
from app.domains.styles.hooks import MAX_FORMATS, write_hooks
from app.models.exception import HttpException
from app.utils import utils

router = new_router()

_HOOKS_RATE_LIMIT = 30
_HOOKS_RATE_WINDOW_S = 3600


class StyleHooksRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    style: str = Field(default="", max_length=40)
    formats: list[str] = Field(default_factory=list, max_length=MAX_FORMATS)
    title: str = Field(..., min_length=1, max_length=300)
    description: str = Field(default="", max_length=2000)
    features: list[str] = Field(default_factory=list, max_length=8)
    language: str = Field(default="auto", max_length=8)


@router.get("/styles", summary="List one-click reel styles")
def list_styles_catalog(request: Request):
    base.get_task_id(request)
    return utils.get_response(200, {"styles": [style.to_public() for style in list_styles()]})


def _authenticate(request: Request, request_id: str) -> str:
    from app.core.auth import resolve_principal
    from app.models.db.base import get_session

    with get_session() as session:
        user = resolve_principal(request, session, request_id)
        return str(getattr(user, "id", "") or "")


@router.post("/styles/hooks", summary="Write hooks for a link in a style's formats")
def style_hooks(request: Request, body: StyleHooksRequest):
    request_id = base.get_task_id(request)
    user_id = _authenticate(request, request_id)
    from app.services.ratelimit import enforce_rate_limit

    enforce_rate_limit(
        request,
        f"style-hooks:{user_id or 'anon'}",
        limit=_HOOKS_RATE_LIMIT,
        window_s=_HOOKS_RATE_WINDOW_S,
    )
    try:
        style = require_style(body.style)
    except UnknownStyleError as exc:
        raise HttpException(task_id=request_id, status_code=400, message=f"{request_id}: {exc}")
    formats = (list(body.formats) or (list(style.hook_family) if style else []))[:MAX_FORMATS]
    if not formats:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: pass a style or at least one hook format",
        )
    try:
        hooks = write_hooks(
            title=body.title,
            description=body.description,
            features=[str(item)[:200] for item in body.features],
            formats=formats,
            language=body.language,
        )
    except HookStyleError as exc:
        raise HttpException(task_id=request_id, status_code=400, message=f"{request_id}: {exc}")
    return utils.get_response(200, {"style": style.id if style else "", "hooks": hooks})
