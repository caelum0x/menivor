"""Content Month HTTP surface (owner-scoped).

    GET    /month/plans                      the caller's plans (newest first)
    POST   /month/plans                      website URL -> plan with ~30 ideas
    GET    /month/plans/{id}                 one plan with its ideas
    DELETE /month/plans/{id}                 delete a plan
    POST   /month/ideas/{id}/decision        swipe: kept | skipped | pending
    PATCH  /month/ideas/{id}                 edit hook / slides / caption
    POST   /month/ideas/{id}/render          kept carousel -> design doc + PNG pages + PDF (+ queued MP4)
    POST   /month/ideas/{id}/video           queue the slideshow MP4 again
    POST   /month/ideas/{id}/job             link the reel job made from ``reel_job``
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Path, Request
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session, require_database, resolve_principal
from app.domains.content_month import service
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

router = new_router()

def _id() -> Any:
    """A fresh ``Path`` per parameter: one shared instance pins its alias to the first name used."""
    return Path(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")
_HOUR = 3600


class PlanBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., min_length=3, max_length=2000)
    count: int = Field(default=30, ge=5, le=40)


class DecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(..., pattern=r"^(kept|skipped|pending)$")


class EditBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hook: Optional[str] = Field(default=None, max_length=300)
    slides: Optional[list[str]] = Field(default=None, max_length=8)
    caption: Optional[str] = Field(default=None, max_length=2200)


class RenderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    size: str = Field(default="tiktok", pattern=r"^(tiktok|instagram)$")
    video: bool = True


class JobBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")


def _err(request_id: str, status: int, message: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=status, message=f"{request_id}: {message}")


def _caller(request: Request, *, bucket: str = "", limit: int = 0) -> tuple[str, str]:
    request_id = base.get_task_id(request)
    require_database(request_id)
    with get_session() as session:
        user_id = str(resolve_principal(request, session, request_id).id)
    if bucket:
        enforce_rate_limit(request, f"month:{bucket}:{user_id}", limit=limit, window_s=_HOUR)
    return request_id, user_id


def _run(request_id: str, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except service.MonthError as exc:
        raise _err(request_id, exc.status_code, str(exc)) from exc
    except HttpException:
        raise
    except Exception as exc:  # noqa: BLE001 - unexpected failure -> 500 with a stable message
        logger.error(f"content month request failed, request_id: {request_id}: {exc}")
        raise _err(request_id, 500, "the content plan request failed") from exc


@router.get("/month/plans", summary="List content plans")
def list_plans(request: Request):
    request_id, user_id = _caller(request)
    return utils.get_response(200, _run(request_id, service.list_plans, user_id))


@router.post("/month/plans", summary="Website -> a month of post ideas")
def create_plan(request: Request, body: PlanBody):
    request_id, user_id = _caller(request, bucket="plan", limit=12)
    return utils.get_response(200, _run(request_id, service.create_plan, user_id, body.url, count=body.count))


@router.get("/month/plans/{plan_id}", summary="One content plan with its ideas")
def get_plan(request: Request, plan_id: str = _id()):
    request_id, user_id = _caller(request)
    return utils.get_response(200, _run(request_id, service.get_plan, user_id, plan_id))


@router.delete("/month/plans/{plan_id}", summary="Delete a content plan")
def delete_plan(request: Request, plan_id: str = _id()):
    request_id, user_id = _caller(request)
    return utils.get_response(200, _run(request_id, service.delete_plan, user_id, plan_id))


@router.post("/month/ideas/{idea_id}/decision", summary="Keep or skip a post idea")
def decide(request: Request, body: DecisionBody, idea_id: str = _id()):
    request_id, user_id = _caller(request, bucket="swipe", limit=3000)
    return utils.get_response(200, _run(request_id, service.decide, user_id, idea_id, body.decision))


@router.patch("/month/ideas/{idea_id}", summary="Edit a post idea")
def edit_idea(request: Request, body: EditBody, idea_id: str = _id()):
    request_id, user_id = _caller(request, bucket="edit", limit=2000)
    return utils.get_response(200, _run(request_id, service.edit_idea, user_id, idea_id, hook=body.hook,
                                        slides_in=body.slides, caption=body.caption))


@router.post("/month/ideas/{idea_id}/render", summary="Make the carousel: PNG slides, PDF and video")
def render(request: Request, body: RenderBody, idea_id: str = _id()):
    request_id, user_id = _caller(request, bucket="render", limit=120)
    return utils.get_response(200, _run(request_id, service.render_carousel, user_id, idea_id, size=body.size,
                                        with_video=body.video))


@router.post("/month/ideas/{idea_id}/video", summary="Make the carousel video again")
def retry_video(request: Request, idea_id: str = _id()):
    request_id, user_id = _caller(request, bucket="render", limit=120)
    return utils.get_response(200, _run(request_id, service.retry_video, user_id, idea_id))


@router.post("/month/ideas/{idea_id}/job", summary="Link the reel made from this idea")
def attach_job(request: Request, body: JobBody, idea_id: str = _id()):
    request_id, user_id = _caller(request, bucket="edit", limit=2000)
    return utils.get_response(200, _run(request_id, service.attach_job, user_id, idea_id, body.job_id))
