"""HTTP API for the caller's Buffer and Typefully connections.

* ``GET    /scheduler/connections``
* ``PUT    /scheduler/connections/{provider}``   body ``{api_key}`` (write-only)
* ``DELETE /scheduler/connections/{provider}``
* ``GET    /scheduler/connections/{provider}/targets``
* ``POST   /scheduler/posts``

The API key is accepted once, encrypted, and never returned.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import Path, Request
from pydantic import BaseModel, ConfigDict, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.utils import utils

try:
    from app.core.auth import resolve_principal
    from app.domains.x_scheduler.errors import SchedulerError
    from app.domains.x_scheduler.service import (
        connect,
        disconnect,
        list_connections,
        list_targets,
        schedule_post,
    )
    from app.models.db.base import get_session

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - before the DB layer exists
    resolve_principal = None  # type: ignore[assignment]
    SchedulerError = Exception  # type: ignore[assignment,misc]
    connect = disconnect = list_connections = list_targets = schedule_post = None  # type: ignore[assignment]
    get_session = None  # type: ignore[assignment]
    _DB_IMPORT_ERROR = exc

router = new_router()


class SaveKeyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = Field(..., min_length=1, max_length=512)


class ScheduleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    target_id: str = Field(..., max_length=128)
    source: str
    source_id: str = Field(..., max_length=64)
    caption: str = Field(default="", max_length=280)
    when: str
    scheduled_at: datetime | None = None


def _require_db(request_id: str) -> None:
    if _DB_IMPORT_ERROR is not None or get_session is None:
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: persistence layer is not available",
        )


def _map(exc: SchedulerError, request_id: str) -> HttpException:
    return HttpException(
        task_id=request_id,
        status_code=int(exc.status_code),
        message=f"{request_id}: {exc.message}",
        data={"code": exc.code},
    )


@router.get("/scheduler/connections", summary="Buffer and Typefully connection status")
def get_connections(request: Request):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = resolve_principal(request, session, request_id)
        data = {"connections": list_connections(session, user.id)}
    return utils.get_response(200, data)


@router.put("/scheduler/connections/{provider}", summary="Save a Buffer or Typefully API key")
def put_connection(request: Request, body: SaveKeyBody, provider: str = Path(...)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = resolve_principal(request, session, request_id)
        try:
            data = connect(session, user.id, provider, body.api_key)
        except SchedulerError as exc:
            raise _map(exc, request_id) from exc
    return utils.get_response(200, data)


@router.delete("/scheduler/connections/{provider}", summary="Disconnect Buffer or Typefully")
def delete_connection(request: Request, provider: str = Path(...)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = resolve_principal(request, session, request_id)
        try:
            data = disconnect(session, user.id, provider)
        except SchedulerError as exc:
            raise _map(exc, request_id) from exc
    return utils.get_response(200, data)


@router.get("/scheduler/connections/{provider}/targets", summary="X accounts on Buffer or Typefully")
def get_targets(request: Request, provider: str = Path(...)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = resolve_principal(request, session, request_id)
        try:
            data = list_targets(session, user.id, provider)
        except SchedulerError as exc:
            raise _map(exc, request_id) from exc
    return utils.get_response(200, data)


@router.post("/scheduler/posts", summary="Send a finished render to Buffer or Typefully")
def post_render(request: Request, body: ScheduleBody):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = resolve_principal(request, session, request_id)
        try:
            data: Any = schedule_post(
                session,
                user.id,
                provider=body.provider,
                target_id=body.target_id,
                source=body.source,
                source_id=body.source_id,
                caption=body.caption,
                when=body.when,
                scheduled_at=body.scheduled_at,
            )
        except SchedulerError as exc:
            raise _map(exc, request_id) from exc
    return utils.get_response(200, data)
