"""BYOK HTTP domain — store / list / revoke customer provider keys.

Routes under ``/api/v1`` via :func:`app.controllers.v1.base.new_router`. The raw
secret is write-only: it is accepted on create, encrypted, and NEVER returned by
any endpoint (list/revoke return only the non-secret prefix + metadata). Import-
safe (guarded DB import -> clean 503 when the layer is absent).

Endpoints:
* ``POST   /byok/keys``          store a provider key (encrypted at rest)
* ``GET    /byok/keys``          list the caller's keys (no secrets)
* ``DELETE /byok/keys/{key_id}`` revoke one owned key (immediate)
"""

from __future__ import annotations

from typing import Any

from fastapi import Path, Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.utils import utils

from .schemas import AddProviderKeyRequest

try:
    from app.core.auth import resolve_principal
    from app.domains.byok.service import BYOKError, BYOKService
    from app.models.db.base import get_session

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before DB layer exists
    resolve_principal = None  # type: ignore[assignment]
    BYOKError = Exception  # type: ignore[assignment,misc]
    BYOKService = None  # type: ignore[assignment]
    get_session = None  # type: ignore[assignment]
    _DB_IMPORT_ERROR = exc


router = new_router()


def _require_db(request_id: str) -> None:
    if _DB_IMPORT_ERROR is not None or get_session is None or BYOKService is None:
        logger.error(
            f"byok persistence unavailable, request_id: {request_id}, "
            f"error: {_DB_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: persistence layer is not available",
        )


def _resolve_user(request: Request, session: Any, request_id: str):
    return resolve_principal(request, session, request_id)


def _map_error(exc: Exception, request_id: str) -> HttpException:
    status_code = int(getattr(exc, "status_code", 400) or 400)
    message = str(getattr(exc, "message", "") or "invalid byok request")
    return HttpException(
        task_id=request_id, status_code=status_code, message=f"{request_id}: {message}"
    )


@router.post("/byok/keys", summary="Store a customer provider key")
def add_provider_key(request: Request, body: AddProviderKeyRequest):
    """Store the caller's own provider API key, encrypted at rest.

    The secret is accepted here, encrypted, and never returned — the response
    carries only a non-secret prefix hint + metadata.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            data = BYOKService(session).add_key(
                user.id,
                provider_key=body.provider_key,
                secret=body.secret,
                label=body.label,
                priority=body.priority,
            )
        except BYOKError as exc:
            raise _map_error(exc, request_id) from exc
    return utils.get_response(200, data)


@router.get("/byok/keys", summary="List the caller's provider keys")
def list_provider_keys(request: Request):
    """List the caller's stored keys (never secrets)."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        keys = BYOKService(session).list_keys(user.id)
    return utils.get_response(200, {"keys": keys})


@router.delete("/byok/keys/{key_id}", summary="Revoke a provider key")
def revoke_provider_key(request: Request, key_id: str = Path(..., description="Key id")):
    """Revoke one owned key immediately (404 for unknown/foreign, no leak)."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            data = BYOKService(session).revoke_key(user.id, key_id)
        except BYOKError as exc:
            raise _map_error(exc, request_id) from exc
    return utils.get_response(200, data)
