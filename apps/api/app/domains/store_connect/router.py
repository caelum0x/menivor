"""HTTP surface for Phase 3 "Connect your store" (owner-scoped, credential-free reads).

    GET    /store-connect                         the caller's connected store accounts
    POST   /store-connect/appstore                connect: issuer ID + key ID + .p8 private key
    POST   /store-connect/play                    connect: Play service-account JSON
    DELETE /store-connect/{provider}               disconnect (appstore | play)
    GET    /store-connect/appstore/apps            every ASC app + current version + rating
    GET    /store-connect/play/apps                every registered Play package + version + rating
    POST   /store-connect/play/apps                register (and read) one more Play package name

A credential (the .p8 key, the service-account JSON) is written to the
request body exactly once, validated against the real provider, and never
echoed back — every read endpoint returns only non-secret fields
(``account_name``, status, package names) plus the app/version/rating data a
stored credential can fetch.
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

from . import service as store_service
from .clients import StoreConnectError

router = new_router()

_CONNECT_LIMIT = 20
_READ_LIMIT = 60
_WINDOW_S = 3600
_PROVIDER = Path(..., pattern=r"^(appstore|play)$")


def _caller(request: Request, request_id: str, *, bucket: str = "", limit: int = 0) -> str:
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        if bucket:
            enforce_rate_limit(request, f"{bucket}:{user.id}", limit=limit, window_s=_WINDOW_S)
        return str(user.id)


def _run(request_id: str, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except StoreConnectError as exc:
        raise HttpException(task_id=request_id, status_code=exc.status_code, message=f"{request_id}: {exc}") from exc
    except HttpException:
        raise
    except Exception as exc:  # noqa: BLE001 - storage/provider failure; never echo a credential
        logger.error(f"store_connect: {getattr(fn, '__name__', 'call')} failed, request_id: {request_id}: "
                     f"{type(exc).__name__}")
        raise HttpException(
            task_id=request_id, status_code=502, message=f"{request_id}: the store-connect request failed; try again",
        ) from exc


@router.get("/store-connect", summary="The caller's connected store accounts")
def list_connections(request: Request):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    return utils.get_response(200, {"connections": _run(request_id, store_service.list_connections, user_id)})


class AppStoreConnectBody(BaseModel):
    issuer_id: str = Field(..., min_length=1, max_length=100)
    key_id: str = Field(..., min_length=1, max_length=100)
    private_key_pem: str = Field(..., min_length=1, max_length=10_000)


@router.post("/store-connect/appstore", summary="Connect an App Store Connect API key")
def connect_appstore(request: Request, body: AppStoreConnectBody):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id, bucket="store_connect", limit=_CONNECT_LIMIT)
    return utils.get_response(
        200,
        _run(request_id, store_service.connect_appstore, user_id, body.issuer_id, body.key_id, body.private_key_pem),
    )


class PlayConnectBody(BaseModel):
    service_account_json: str = Field(..., min_length=1, max_length=20_000)


@router.post("/store-connect/play", summary="Connect a Google Play service account")
def connect_play(request: Request, body: PlayConnectBody):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id, bucket="store_connect", limit=_CONNECT_LIMIT)
    return utils.get_response(
        200, _run(request_id, store_service.connect_play, user_id, body.service_account_json),
    )


@router.delete("/store-connect/{provider}", summary="Disconnect a store account")
def disconnect(request: Request, provider: str = _PROVIDER):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id, bucket="store_connect", limit=_CONNECT_LIMIT)
    disconnected = _run(request_id, store_service.disconnect, user_id, provider)
    return utils.get_response(200, {"disconnected": disconnected})


@router.get("/store-connect/appstore/apps", summary="Apps + current version + rating (App Store Connect)")
def appstore_apps(request: Request):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id, bucket="store_connect_read", limit=_READ_LIMIT)
    return utils.get_response(200, {"apps": _run(request_id, store_service.list_appstore_apps, user_id)})


@router.get("/store-connect/play/apps", summary="Registered Play packages + version + rating")
def play_apps(request: Request):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id, bucket="store_connect_read", limit=_READ_LIMIT)
    return utils.get_response(200, {"apps": _run(request_id, store_service.list_play_apps, user_id)})


class PlayAppBody(BaseModel):
    package_name: str = Field(..., min_length=3, max_length=200, pattern=r"^[A-Za-z0-9_.]+$")


@router.post("/store-connect/play/apps", summary="Register (and read) one more Play package")
def add_play_app(request: Request, body: PlayAppBody):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id, bucket="store_connect", limit=_CONNECT_LIMIT)
    return utils.get_response(200, _run(request_id, store_service.add_play_app, user_id, body.package_name))
