"""Results page HTTP surface (owner-scoped).

    GET    /me/results                         winners, chart, tracked posts, platform status
    POST   /me/results/sync                    read the caller's posts now (bounded)
    POST   /me/tracked-posts                   {url}: track a post from its link and read it now
    POST   /me/tracked-posts/{post_id}/numbers type the numbers for a post the platform hides
    DELETE /me/tracked-posts/{post_id}         stop tracking a post
"""

from __future__ import annotations

from fastapi import Path, Request
from loguru import logger
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.api_dependencies import (
    get_session,
    require_database as _require_db,
    resolve_principal as _resolve_user,
)
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

from . import tracker
from .links import MAX_URL_LENGTH, LinkError
from .summary import build_results

router = new_router()

_SYNC_LIMIT = 12
_TRACK_LIMIT = 30
_NUMBERS_LIMIT = 60
_WINDOW_S = 3600
_POST_ID = Path(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")
_MAX_COUNT = tracker.MAX_TYPED_COUNT


class TrackLinkBody(BaseModel):
    url: str = Field(..., min_length=1, max_length=MAX_URL_LENGTH)


class NumbersBody(BaseModel):
    views: int | None = Field(default=None, ge=0, le=_MAX_COUNT)
    likes: int | None = Field(default=None, ge=0, le=_MAX_COUNT)
    comments: int | None = Field(default=None, ge=0, le=_MAX_COUNT)
    shares: int | None = Field(default=None, ge=0, le=_MAX_COUNT)
    saves: int | None = Field(default=None, ge=0, le=_MAX_COUNT)


def _error(request_id: str, status: int, message: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=status, message=message)


def _caller(request: Request, request_id: str) -> str:
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        return str(user.id)


def _connected(session, user_id: str) -> dict[str, str]:
    try:
        from app.domains.social_inbox.sync import connected_platforms

        return connected_platforms(session, user_id)
    except Exception as exc:  # noqa: BLE001 - the page still shows tracked posts
        logger.info(f"results: connections unavailable for {user_id}: {exc}")
        return {}


def _results(user_id: str) -> dict:
    with get_session() as session:
        return build_results(session, user_id, now=tracker.utcnow(), connected=_connected(session, user_id))


@router.get("/me/results", summary="Which hooks and styles win, from your posts' real numbers")
def get_results(request: Request):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    return utils.get_response(200, _results(user_id))


@router.post("/me/results/sync", summary="Read the numbers of your posts now")
def sync_results(request: Request):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    enforce_rate_limit(request, f"results_sync:{user_id}", limit=_SYNC_LIMIT, window_s=_WINDOW_S)
    try:
        tracker.sync_user(user_id)
    except Exception as exc:  # noqa: BLE001 - stored numbers are still returned
        logger.error(f"results sync failed for {user_id}: {exc}")
    return utils.get_response(200, _results(user_id))


@router.post("/me/tracked-posts", summary="Track a post from its link")
def track_post(request: Request, body: TrackLinkBody):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    enforce_rate_limit(request, f"results_track:{user_id}", limit=_TRACK_LIMIT, window_s=_WINDOW_S)
    try:
        post_id = tracker.track_link(user_id, body.url)
    except LinkError as exc:
        raise _error(request_id, 400, str(exc)) from exc
    except tracker.TrackingLimit as exc:
        raise _error(request_id, 409, str(exc)) from exc
    data = _results(user_id)
    return utils.get_response(200, {**data, "added_post_id": post_id})


@router.post("/me/tracked-posts/{post_id}/numbers", summary="Enter a post's numbers yourself")
def type_numbers(request: Request, body: NumbersBody, post_id: str = _POST_ID):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    enforce_rate_limit(request, f"results_numbers:{user_id}", limit=_NUMBERS_LIMIT, window_s=_WINDOW_S)
    try:
        tracker.add_numbers(user_id, post_id, body.model_dump())
    except tracker.PostNotFound as exc:
        raise _error(request_id, 404, "That post is not on your list.") from exc
    except ValueError as exc:
        raise _error(request_id, 400, str(exc)) from exc
    return utils.get_response(200, _results(user_id))


@router.delete("/me/tracked-posts/{post_id}", summary="Stop tracking a post")
def untrack_post(request: Request, post_id: str = _POST_ID):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    try:
        tracker.stop_tracking(user_id, post_id)
    except tracker.PostNotFound as exc:
        raise _error(request_id, 404, "That post is not on your list.") from exc
    return utils.get_response(200, _results(user_id))


__all__ = ["router"]
