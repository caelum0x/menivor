"""Private-beta HTTP surface.

* ``POST /beta/request``           public waitlist signup (rate-limited, deduped)
* ``GET  /beta/requests``          operator list (``x-admin-token`` required)
* ``POST /beta/requests/approve``  operator approve/revoke (``x-admin-token``)

The public endpoint always answers with the same neutral body whether the email
is new, a duplicate, pending or already approved, so it cannot be used to
enumerate who is on the list. The operator token is read from
``REELFORGE_BETA_ADMIN_TOKEN`` (or ``[app].reelforge_beta_admin_token``); when it
is unset or too short the admin endpoints fail closed with 503.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

from fastapi import Query, Request
from loguru import logger
from pydantic import BaseModel, Field

from app.config import config
from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit, rate_limit
from app.utils import utils

try:
    from app.domains.beta import service as beta_service
    from app.models.db.base import get_session

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - import-safe degrade to 503
    beta_service = None  # type: ignore[assignment]
    get_session = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc

router = new_router()

_ADMIN_HEADER = "x-admin-token"
_MIN_ADMIN_TOKEN_LEN = 24
# Per-caller and whole-endpoint ceilings for the unauthenticated waitlist form.
_REQUEST_LIMIT_PER_CALLER = 5
_REQUEST_LIMIT_GLOBAL = 300
_REQUEST_LIMIT_PER_EMAIL = 3
_REQUEST_WINDOW_S = 3600


class BetaRequestBody(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    use_case: str = Field(default="", max_length=2000)
    source: str = Field(default="", max_length=40)


class BetaApproveBody(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    approved: bool = True


def _require_backend(request_id: str) -> None:
    if _IMPORT_ERROR is not None or get_session is None or beta_service is None:
        logger.error(f"beta waitlist unavailable, request_id: {request_id}, error: {_IMPORT_ERROR}")
        raise HttpException(task_id=request_id, status_code=503,
                            message=f"{request_id}: beta waitlist is not available")


def _admin_token() -> str:
    return str(
        os.getenv("REELFORGE_BETA_ADMIN_TOKEN", config.app.get("reelforge_beta_admin_token", "")) or ""
    ).strip()


def _require_admin(request: Request, request_id: str) -> None:
    expected = _admin_token()
    if len(expected) < _MIN_ADMIN_TOKEN_LEN:
        raise HttpException(task_id=request_id, status_code=503,
                            message=f"{request_id}: beta admin is not configured")
    supplied = str(request.headers.get(_ADMIN_HEADER, "") or "").strip()
    if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HttpException(task_id=request_id, status_code=403,
                            message=f"{request_id}: admin token required")


def _map_error(exc: Exception, request_id: str) -> HttpException:
    status_code = int(getattr(exc, "status_code", 422) or 422)
    message = str(getattr(exc, "message", "") or "invalid beta request")
    return HttpException(task_id=request_id, status_code=status_code, message=f"{request_id}: {message}")


def _limit_or_429(key: str, limit: int, request_id: str) -> None:
    if not rate_limit(key, limit, _REQUEST_WINDOW_S).allowed:
        raise HttpException(task_id=request_id, status_code=429,
                            message=f"{request_id}: too many beta requests, try again later")


@router.post("/beta/request", summary="Request private-beta access")
def request_beta_access(request: Request, body: BetaRequestBody):
    request_id = base.get_task_id(request)
    _require_backend(request_id)
    enforce_rate_limit(request, "beta_request", limit=_REQUEST_LIMIT_PER_CALLER, window_s=_REQUEST_WINDOW_S)
    # A global ceiling keeps one rotating source from flooding the table.
    _limit_or_429("beta_request:global", _REQUEST_LIMIT_GLOBAL, request_id)
    try:
        email = beta_service.normalize_email(body.email)
    except beta_service.BetaError as exc:
        raise _map_error(exc, request_id) from exc
    # Per-email bucket (hashed, never the raw address in Redis): repeated
    # submissions for one address from many sources stay cheap no-ops.
    email_digest = hashlib.sha256(email.encode("utf-8")).hexdigest()[:24]
    _limit_or_429(f"beta_request:email:{email_digest}", _REQUEST_LIMIT_PER_EMAIL, request_id)
    with get_session() as session:
        _, created = beta_service.request_access(
            session, email=email, use_case=body.use_case, source=body.source
        )
    logger.info(f"beta waitlist request recorded (new={created}), request_id: {request_id}")
    return utils.get_response(200, {
        "status": "received",
        "message": "Thanks, you are on the Menivor private beta list. We will email you when your access is approved.",
    })


@router.get("/beta/requests", summary="List private-beta requests (operator)")
def list_beta_requests(
    request: Request,
    status: str = Query(default="", max_length=16),
    limit: int = Query(default=100, ge=1, le=500),
):
    request_id = base.get_task_id(request)
    _require_admin(request, request_id)
    _require_backend(request_id)
    with get_session() as session:
        try:
            rows = beta_service.list_requests(session, status=status.strip().lower(), limit=limit)
        except beta_service.BetaError as exc:
            raise _map_error(exc, request_id) from exc
        items: list[dict[str, Any]] = [beta_service.request_view(r) for r in rows]
    return utils.get_response(200, {"items": items, "count": len(items)})


@router.post("/beta/requests/approve", summary="Approve or revoke a private-beta email (operator)")
def approve_beta_request(request: Request, body: BetaApproveBody):
    request_id = base.get_task_id(request)
    _require_admin(request, request_id)
    _require_backend(request_id)
    with get_session() as session:
        try:
            row = beta_service.set_status(session, email=body.email, approved=body.approved)
        except beta_service.BetaError as exc:
            raise _map_error(exc, request_id) from exc
        view = beta_service.request_view(row)
    logger.info(f"beta access {'approved' if body.approved else 'revoked'}, request_id: {request_id}")
    return utils.get_response(200, view)
