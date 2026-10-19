"""Channel viewer routes (MV6). 404 until OTT_ENABLED and OTT_VIEWERS_LIVE.

* ``POST   /api/v1/ott/viewers/{handle}/session``            Scribase Auth token -> channel session
* ``GET    /api/v1/ott/viewers/{handle}/me``                 my viewer profile on this channel
* ``PATCH  /api/v1/ott/viewers/{handle}/me``                 rename
* ``DELETE /api/v1/ott/viewers/{handle}/me``                 delete me and my history
* ``POST   /api/v1/ott/viewers/{handle}/sign-out``           sign out on every device
* ``GET    /api/v1/ott/viewers/{handle}/continue``           continue watching
* ``GET    /api/v1/ott/viewers/{handle}/progress/{title}``   where to resume
* ``PUT    /api/v1/ott/viewers/{handle}/progress/{title}``   save the position (any device)
* ``GET    /api/v1/ott/viewers/{handle}/watchlist``          my list on this channel (QM1.5)
* ``PUT    /api/v1/ott/viewers/{handle}/watchlist/{title}``  add a title to my list
* ``DELETE /api/v1/ott/viewers/{handle}/watchlist/{title}``  remove it
* ``GET    /api/v1/ott/viewers/{handle}/ratings/{title}``    average, count and my stars
* ``PUT    /api/v1/ott/viewers/{handle}/ratings/{title}``    rate 1 to 5 stars
* ``DELETE /api/v1/ott/viewers/{handle}/ratings/{title}``    take my rating back
* ``PUT    /api/v1/ott/viewers/{handle}/push``               opt in to new episodes and/or live starts
* ``DELETE /api/v1/ott/viewers/{handle}/push``               opt out

The channel session rides in ``X-OTT-Viewer``; it never appears in a URL.
"""

from __future__ import annotations

from typing import Callable

from fastapi import Depends, Path, Request, Response
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, get_session
from app.domains.ott import flags
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit, rate_limit
from app.utils import utils

from . import retention, service, session as viewer_session

router = new_router()
_LIVE = [Depends(flags.require("viewers"))]
NO_STORE = {"Cache-Control": "no-store, private"}
SIGN_IN_LIMIT = 10
SIGN_IN_WINDOW_S = 60
TV_APPROVE_LIMIT = 10


class SignIn(BaseModel):
    access_token: str = Field(..., min_length=10, max_length=4096)
    device: str = Field("web", max_length=16)


class Rename(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=60)


class Progress(BaseModel):
    position_s: float = Field(..., ge=0, le=86400)
    duration_s: float = Field(0, ge=0, le=86400)
    device: str = Field("web", max_length=16)


def _http(exc: service.ViewerError | retention.RetentionError, request_id: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=exc.status_code, message=str(exc), data={"code": exc.code})


def _with_viewer(request: Request, response: Response, handle: str, fn: Callable):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    token = request.headers.get(viewer_session.HEADER) or ""
    with get_session() as session:
        try:
            viewer = service.resolve(session, token, handle)
            result = fn(session, viewer)
        except (service.ViewerError, retention.RetentionError) as exc:
            raise _http(exc, request_id) from exc
    response.headers.update(NO_STORE)
    return utils.get_response(200, result)


_HANDLE = Path(..., min_length=1, max_length=40)
_TITLE = Path(..., max_length=32)


@router.post("/ott/viewers/{handle}/session", dependencies=_LIVE, summary="Sign in to a channel")
def sign_in(request: Request, body: SignIn, response: Response, handle: str = _HANDLE):
    enforce_rate_limit(request, "ott:viewer-sign-in", SIGN_IN_LIMIT, SIGN_IN_WINDOW_S)
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        try:
            result = service.sign_in(session, handle, body.access_token, device=body.device)
        except service.ViewerError as exc:
            raise _http(exc, request_id) from exc
    response.headers.update(NO_STORE)
    return utils.get_response(200, result)


@router.get("/ott/viewers/{handle}/me", dependencies=_LIVE, summary="My viewer profile on this channel")
def me(request: Request, response: Response, handle: str = _HANDLE):
    return _with_viewer(request, response, handle, lambda s, v: service.viewer_view(v))


@router.patch("/ott/viewers/{handle}/me", dependencies=_LIVE, summary="Rename me on this channel")
def rename(request: Request, body: Rename, response: Response, handle: str = _HANDLE):
    return _with_viewer(request, response, handle, lambda s, v: service.rename(s, v, body.display_name))


@router.delete("/ott/viewers/{handle}/me", dependencies=_LIVE, summary="Delete me and my watch history")
def delete_me(request: Request, response: Response, handle: str = _HANDLE):
    return _with_viewer(request, response, handle, lambda s, v: {"deleted": True, **service.delete_viewer(s, v)})


@router.post("/ott/viewers/{handle}/sign-out", dependencies=_LIVE, summary="Sign out on every device")
def sign_out(request: Request, response: Response, handle: str = _HANDLE):
    def _run(s, v):
        service.sign_out_everywhere(s, v)
        return {"signed_out": True}

    return _with_viewer(request, response, handle, _run)


@router.get("/ott/viewers/{handle}/continue", dependencies=_LIVE, summary="Continue watching")
def continue_watching(request: Request, response: Response, handle: str = _HANDLE):
    return _with_viewer(request, response, handle, lambda s, v: {"items": service.continue_watching(s, v)})


@router.get("/ott/viewers/{handle}/progress/{title_id}", dependencies=_LIVE, summary="Where to resume a title")
def get_progress(request: Request, response: Response, handle: str = _HANDLE, title_id: str = _TITLE):
    return _with_viewer(request, response, handle, lambda s, v: service.resume_point(s, v, title_id))


@router.put("/ott/viewers/{handle}/progress/{title_id}", dependencies=_LIVE, summary="Save where I stopped")
def put_progress(request: Request, body: Progress, response: Response, handle: str = _HANDLE,
                 title_id: str = _TITLE):
    return _with_viewer(request, response, handle, lambda s, v: service.save_progress(
        s, v, title_id, position_s=body.position_s, duration_s=body.duration_s, device=body.device))


# --------------------------------------------------------------------------- #
# Wave Q QM1.5 (U37): watchlist, ratings and push opt-in, per channel viewer
# --------------------------------------------------------------------------- #
class Stars(BaseModel):
    stars: int = Field(..., ge=1, le=5)


class PushOptIn(BaseModel):
    token: str = Field(..., min_length=20, max_length=200)
    platform: str = Field("ios", max_length=16)
    topics: list[str] = Field(..., min_length=1, max_length=2)


class PushOptOut(BaseModel):
    token: str = Field("", max_length=200)


@router.get("/ott/viewers/{handle}/watchlist", dependencies=_LIVE, summary="My list on this channel")
def get_watchlist(request: Request, response: Response, handle: str = _HANDLE):
    from app.domains.ott_access import geo

    country = geo.country(request.headers)
    return _with_viewer(request, response, handle, lambda s, v: {"items": retention.watchlist(s, v, country=country)})


@router.put("/ott/viewers/{handle}/watchlist/{title_id}", dependencies=_LIVE, summary="Add to my list")
def add_watchlist(request: Request, response: Response, handle: str = _HANDLE, title_id: str = _TITLE):
    return _with_viewer(request, response, handle,
                        lambda s, v: {"added": retention.add_to_watchlist(s, v, title_id), "title_id": title_id})


@router.delete("/ott/viewers/{handle}/watchlist/{title_id}", dependencies=_LIVE, summary="Remove from my list")
def remove_watchlist(request: Request, response: Response, handle: str = _HANDLE, title_id: str = _TITLE):
    return _with_viewer(request, response, handle,
                        lambda s, v: {"removed": retention.remove_from_watchlist(s, v, title_id), "title_id": title_id})


@router.get("/ott/viewers/{handle}/ratings/{title_id}", dependencies=_LIVE, summary="Ratings of a title")
def get_rating(request: Request, response: Response, handle: str = _HANDLE, title_id: str = _TITLE):
    return _with_viewer(request, response, handle, lambda s, v: retention.title_rating(s, v, title_id))


@router.put("/ott/viewers/{handle}/ratings/{title_id}", dependencies=_LIVE, summary="Rate a title")
def put_rating(request: Request, body: Stars, response: Response, handle: str = _HANDLE, title_id: str = _TITLE):
    return _with_viewer(request, response, handle, lambda s, v: retention.rate(s, v, title_id, body.stars))


@router.delete("/ott/viewers/{handle}/ratings/{title_id}", dependencies=_LIVE, summary="Take my rating back")
def delete_rating(request: Request, response: Response, handle: str = _HANDLE, title_id: str = _TITLE):
    return _with_viewer(request, response, handle, lambda s, v: retention.unrate(s, v, title_id))


@router.put("/ott/viewers/{handle}/push", dependencies=_LIVE, summary="Opt in to push from this channel")
def push_opt_in(request: Request, body: PushOptIn, response: Response, handle: str = _HANDLE):
    return _with_viewer(request, response, handle, lambda s, v: retention.opt_in(
        s, v, token=body.token, platform=body.platform, topics=body.topics))


@router.delete("/ott/viewers/{handle}/push", dependencies=_LIVE, summary="Opt out of push from this channel")
def push_opt_out(request: Request, response: Response, handle: str = _HANDLE, body: PushOptOut | None = None):
    return _with_viewer(request, response, handle, lambda s, v: retention.opt_out(s, v, body.token if body else ""))


# --------------------------------------------------------------------------- #
# Wave P PM3.3 (MV9): sign in on a TV with a phone. 404 until OTT_VIEWERS_LIVE and OTT_TV_LIVE.
# --------------------------------------------------------------------------- #
_TV = [Depends(flags.require("viewers")), Depends(flags.require("tv"))]
POLL_LIMIT = 30


class TvApprove(BaseModel):
    user_code: str = Field(..., min_length=6, max_length=12)


class TvPoll(BaseModel):
    device_token: str = Field(..., min_length=20, max_length=100)


def _tv_error(exc: Exception, request_id: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=getattr(exc, "status_code", 400), message=str(exc),
                         data={"code": getattr(exc, "code", "error")})


@router.post("/ott/viewers/{handle}/tv-codes", dependencies=_TV, summary="A code to show on the TV")
def tv_code(request: Request, response: Response, handle: str = _HANDLE):
    from . import tv_codes

    enforce_rate_limit(request, "ott:tv-code", SIGN_IN_LIMIT, SIGN_IN_WINDOW_S)
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        try:
            channel = service.published_channel(session, handle)
        except service.ViewerError as exc:
            raise _http(exc, request_id) from exc
    response.headers.update(NO_STORE)
    return utils.get_response(200, tv_codes.start(channel.id))


@router.post("/ott/viewers/{handle}/tv-codes/approve", dependencies=_TV, summary="Approve the TV code on my phone")
def tv_approve(request: Request, body: TvApprove, response: Response, handle: str = _HANDLE):
    from . import tv_codes

    def _run(s, v):
        # QM1.0: 10 approvals a minute per viewer, so a signed-in viewer cannot guess codes.
        if not rate_limit(f"ott:tv-approve:{v.id}", TV_APPROVE_LIMIT, SIGN_IN_WINDOW_S).allowed:
            raise service.ViewerError(429, "rate_limited", "Too many tries. Wait a minute and try again.")
        try:
            return tv_codes.approve(v, body.user_code)
        except tv_codes.CodeError as exc:
            raise service.ViewerError(exc.status_code, exc.code, str(exc)) from exc

    return _with_viewer(request, response, handle, _run)


@router.post("/ott/viewers/{handle}/tv-codes/poll", dependencies=_TV, summary="The TV asks whether it was approved")
def tv_poll(request: Request, body: TvPoll, response: Response, handle: str = _HANDLE):
    from . import tv_codes

    enforce_rate_limit(request, "ott:tv-poll", POLL_LIMIT, SIGN_IN_WINDOW_S)
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        try:
            channel = service.published_channel(session, handle)
            result = tv_codes.poll(session, channel.id, body.device_token)
        except (service.ViewerError, tv_codes.CodeError) as exc:
            raise _tv_error(exc, request_id) from exc
    response.headers.update(NO_STORE)
    return utils.get_response(200, result)
