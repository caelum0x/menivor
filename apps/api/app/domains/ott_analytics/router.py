"""QoE and team routes (MV12). 404 until OTT_ENABLED and OTT_ANALYTICS_LIVE.

* ``POST   /api/v1/ott/beacons``              player beacons (batches of 50 at most), first-party only
* ``GET    /api/v1/ott/studio/analytics``     my channel's plays, watch time, startup, stalls, errors
* ``GET    /api/v1/ott/studio/team``          who else can see or edit my channel
* ``POST   /api/v1/ott/studio/team``          add an editor or an analyst by email (same answer either way)
* ``DELETE /api/v1/ott/studio/team/{id}``     remove them
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Path, Query, Request, Response
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.domains.ott import flags, roles
from app.domains.ott.models import OttChannel
from app.domains.ott.service import ensure_channel
from app.domains.ott_access import geo, service as access
from app.domains.ott_viewers import session as viewer_session
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

from . import service

router = new_router()
_LIVE = [Depends(flags.require("analytics"))]
BEACON_LIMIT = 120


class Beacons(BaseModel):
    events: list[dict[str, Any]] = Field(..., min_length=1, max_length=service.MAX_BATCH)
    device_id: str = Field("", max_length=64)


class Member(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    role: str = Field(..., max_length=12)


@router.post("/ott/beacons", dependencies=_LIVE, summary="Player quality beacons (first-party)")
def beacons(request: Request, body: Beacons):
    enforce_rate_limit(request, "ott:beacons", BEACON_LIMIT, 60)
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        account = viewer_session.from_request(session, request)
        identity = f"viewer:{account.id}" if account else f"device:{body.device_id or access.client_fingerprint(request)}"
        service.ingest(session, body.events, identity=identity, country=geo.country(request.headers))
    return Response(status_code=204)


def _channel_for(session, user_id: str, handle: str, action: str) -> OttChannel:
    if not handle:
        return ensure_channel(session, user_id)
    for channel in roles.channels_for(session, user_id, action):
        if channel.handle == handle:
            return channel
    raise roles.RoleError(403, "role", "You do not have access to this on the channel.")


def _studio(request: Request, fn):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            return utils.get_response(200, fn(session, str(user.id)))
        except roles.RoleError as exc:
            raise HttpException(task_id=request_id, status_code=exc.status_code, message=str(exc),
                                data={"code": exc.code}) from exc


@router.get("/ott/studio/analytics", dependencies=_LIVE, summary="Channel quality and watch time")
def analytics(request: Request, days: int = Query(7, ge=1, le=90), channel: str = Query("", max_length=40)):
    def _read(s, uid):
        target = _channel_for(s, uid, channel, "view_analytics")
        roles.require(s, uid, target, "view_analytics")
        return {"channel": target.handle, **service.dashboard(s, target, days=days)}

    return _studio(request, _read)


@router.get("/ott/studio/team", dependencies=_LIVE, summary="My channel team")
def get_team(request: Request):
    return _studio(request, lambda s, uid: {"members": roles.team(s, ensure_channel(s, uid))})


@router.post("/ott/studio/team", dependencies=_LIVE, summary="Add an editor or an analyst")
def add_member(request: Request, body: Member):
    def _add(s, uid):
        channel = ensure_channel(s, uid)
        added = roles.add_member(s, channel, email=body.email, role=body.role)
        # P-M15: one answer whether or not the email has an account; the seat applies when they sign in.
        return {"added": added, "members": roles.team(s, channel)}

    return _studio(request, _add)


@router.delete("/ott/studio/team/{member_id}", dependencies=_LIVE, summary="Remove a team member")
def remove_member(request: Request, member_id: str = Path(..., max_length=32)):
    def _remove(s, uid):
        channel = ensure_channel(s, uid)
        roles.remove_member(s, channel, member_id)
        return {"members": roles.team(s, channel)}

    return _studio(request, _remove)
