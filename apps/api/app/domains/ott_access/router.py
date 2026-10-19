"""OTT playback routes (MV5 tier 1). 404 until OTT_ENABLED and OTT_STOREFRONT_LIVE (keys: OTT_ACCESS_LIVE).

* ``POST /api/v1/ott/play/{title_id}``          start a stream (geo, access, stream limit), short token
* ``GET  /api/v1/ott/stream/{token}/{path}``    manifests (key tags carry the token); segments 302 to R2
* ``GET  /api/v1/ott/keys/{title_id}?t=``       the AES-128 key for a valid token, never cached
"""

from __future__ import annotations

from fastapi import Depends, Path, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.domains.ott import flags
from app.domains.ott.models import OttTitle
from app.domains.ott_viewers import session as viewer_session
from app.models.exception import HttpException
from app.utils import utils

from . import geo, keys, service

router = new_router()
_PLAY = [Depends(flags.require("storefront"))]
NO_STORE = {"Cache-Control": "no-store, private"}


class PlayRequest(BaseModel):
    viewer_id: str = Field("", max_length=64)
    # QM verify: a refresh passes its current playback token, so the new grant keeps the same
    # stream session and does not take a second slot under the stream limit mid-title.
    previous_token: str = Field("", max_length=2048)


def _carried_session(previous_token: str, title_id: str, viewer: str) -> str | None:
    """The stream session of a still-valid token for this title and viewer, else ``None``."""
    if not previous_token:
        return None
    from . import tokens

    try:
        grant = tokens.verify(previous_token, title_id=title_id)
    except tokens.TokenError:
        return None
    return grant.session_id if grant.viewer == viewer else None


def storage():
    from app.services.ott_transcode.uploads import R2Storage

    return R2Storage()


def _raise(exc: service.AccessError, request_id: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=exc.status_code, message=str(exc), data={"code": exc.code})


def _optional_user(request: Request, session, request_id: str) -> str | None:
    if not (request.headers.get("authorization") or request.headers.get("x-api-key")):
        return None
    try:
        return str(_resolve_user(request, session, request_id).id)
    except HttpException:
        return None


@router.post("/ott/play/{title_id}", dependencies=_PLAY, summary="Start watching a title")
def play(request: Request, body: PlayRequest, response: Response, title_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user_id = _optional_user(request, session, request_id)
        # Wave P PM3.1 (MV6): a signed-in channel viewer (X-OTT-Viewer) streams as that viewer.
        account = viewer_session.from_request(session, request)
        viewer = (f"user:{user_id}" if user_id else f"viewer:{account.id}" if account is not None
                  else f"device:{body.viewer_id or service.client_fingerprint(request)}")
        try:
            view = service.start(session, session.get(OttTitle, title_id), viewer=viewer,
                                 country=geo.country(request.headers), viewer_user_id=user_id,
                                 viewer_account_id=account.id if account is not None else None,
                                 session_id=_carried_session(body.previous_token, title_id, viewer))
        except service.AccessError as exc:
            raise _raise(exc, request_id) from exc
    response.headers.update(NO_STORE)
    return utils.get_response(200, view)


@router.get("/ott/stream/{token}/{path:path}", dependencies=_PLAY, summary="Tokenized manifest or segment")
def stream(request: Request, token: str = Path(..., max_length=2048), path: str = Path(..., max_length=200)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    store = storage()
    with get_session() as session:
        try:
            if path.endswith(service.MANIFEST_SUFFIXES):
                body, media_type = service.manifest(session, token, path, store.read)
                return Response(content=body, media_type=media_type, headers=NO_STORE)
            url = service.segment_url(session, token, path, store.presign_get,
                                      client=service.client_fingerprint(request))
        except service.AccessError as exc:
            raise _raise(exc, request_id) from exc
    return RedirectResponse(url, status_code=302, headers=NO_STORE)


@router.get("/ott/keys/{title_id}", dependencies=[Depends(flags.require("access"))], summary="Tier-1 content key")
def content_key(request: Request, title_id: str = Path(..., max_length=32), t: str = Query(..., max_length=2048),
                kv: str = Query("", max_length=6)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        try:
            key = keys.release(session, title_id, t, kv)
        except keys.KeyRefused as exc:
            raise HttpException(task_id=request_id, status_code=403, message="key refused",
                                data={"code": "key_refused", "reason": str(exc)}) from exc
    return Response(content=key, media_type="application/octet-stream", headers=NO_STORE)
