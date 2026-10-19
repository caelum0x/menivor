"""SCIM 2.0 provisioning v1 API controller (Identity & SSO, Epic 2).

Two surfaces, both under ``/api/v1``:

**1. SCIM 2.0 provisioning (authenticated by a per-workspace SCIM BEARER token).**

``/scim/v2/{workspace_id}/Users`` (+ ``/Groups``) implement the SCIM 2.0 wire
contract an IdP (Okta / Azure AD / …) drives to provision + deprovision users. The
presented ``Authorization: Bearer`` token is resolved by
:func:`app.services.scim.auth_token`, which enforces the #1 invariant — TENANT
ISOLATION: a token minted for workspace *B* can NEITHER authenticate against, NOR
read/provision into, workspace *A* (a mismatch is a ``401``). Every read/write is
scoped to the token's workspace; every write records an Epic-1 audit row.
Responses use the SCIM 2.0 envelopes (``application/scim+json``: User / ListResponse
/ Error).

**2. SCIM token management (authenticated as a USER + RBAC ``workspace.settings``).**

``/me/workspaces/{id}/scim/tokens`` lets a workspace owner/admin mint, list, and
revoke the bearer tokens above. The raw token is revealed EXACTLY ONCE at mint
(only its SHA-256 digest is stored); a listing never carries a raw token.

Both surfaces are import-safe (a missing service/DB layer degrades to a clean
``503``) and the provisioning surface is rate-limited per workspace.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Path, Query, Request
from loguru import logger
from starlette.responses import JSONResponse

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.models.schema import (
    ScimTokenCreatedResponse,
    ScimTokenListResponse,
)
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

# Guarded imports of the SCIM service + persistence. A partial environment
# degrades to a 503 rather than crashing at import time.
try:  # pragma: no cover - exercised implicitly by the API tests
    from app.models.db.repositories import (
        ScimTokenRepository,
        WorkspaceRepository,
    )
    from app.services import rbac, scim

    _SCIM_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # noqa: BLE001 - import-safe: never crash the module
    ScimTokenRepository = None  # type: ignore[assignment,misc]
    WorkspaceRepository = None  # type: ignore[assignment,misc]
    rbac = None  # type: ignore[assignment]
    scim = None  # type: ignore[assignment]
    _SCIM_IMPORT_ERROR = exc

router = new_router()

_SCIM_ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
_SCIM_LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
_SCIM_GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
_SCIM_MEDIA_TYPE = "application/scim+json"

# The provisioning surface is IdP-facing; rate-limit per workspace so a flood of
# provisioning calls cannot DoS a tenant.
_DEFAULT_SCIM_RATE_LIMIT: int = 240
_DEFAULT_SCIM_RATE_WINDOW_S: int = 60


# --------------------------------------------------------------------------- #
# SCIM response helpers (SCIM-native envelopes, application/scim+json)
# --------------------------------------------------------------------------- #
def _scim_json(status: int, payload: dict[str, Any]) -> JSONResponse:
    """Return a SCIM resource/list payload with the SCIM media type + status."""
    return JSONResponse(
        status_code=status, content=payload, media_type=_SCIM_MEDIA_TYPE
    )


def _scim_error(
    status: int, detail: str, scim_type: Optional[str] = None
) -> JSONResponse:
    """Build a SCIM 2.0 Error envelope response (``schemas``/``status``/``detail``)."""
    body: dict[str, Any] = {
        "schemas": [_SCIM_ERROR_SCHEMA],
        "status": str(status),
        "detail": detail,
    }
    if scim_type:
        body["scimType"] = scim_type
    return JSONResponse(status_code=status, content=body, media_type=_SCIM_MEDIA_TYPE)


def _scim_backend_error(request_id: str) -> Optional[JSONResponse]:
    """Return a SCIM 503 error when the DB/SCIM layer is unavailable, else ``None``."""
    from app.controllers.v1.jobs import _DB_IMPORT_ERROR

    if _DB_IMPORT_ERROR is not None or get_session is None or scim is None:
        logger.error(
            f"scim service unavailable, request_id: {request_id}, "
            f"error: {_SCIM_IMPORT_ERROR or _DB_IMPORT_ERROR}"
        )
        return _scim_error(503, "SCIM provisioning is not available")
    return None


def _scim_rate_limit() -> int:
    """Max SCIM ops per window per workspace (``reelforge_scim_rate_limit``)."""
    from app.config import config

    return int(config.app.get("reelforge_scim_rate_limit", _DEFAULT_SCIM_RATE_LIMIT))


def _scim_rate_window_s() -> int:
    """SCIM rate-limit window in seconds (``reelforge_scim_rate_window_s``)."""
    from app.config import config

    return int(
        config.app.get("reelforge_scim_rate_window_s", _DEFAULT_SCIM_RATE_WINDOW_S)
    )


def _bearer(request: Request) -> str:
    """Read the raw ``Authorization`` header (the SCIM service strips ``Bearer``)."""
    return request.headers.get("Authorization") or request.headers.get(
        "authorization", ""
    )


async def _read_json(request: Request) -> dict[str, Any]:
    """Parse the request body as JSON regardless of ``application/scim+json`` type.

    IdPs send ``application/scim+json``; reading the raw body ourselves avoids
    FastAPI's content-type coupling. A non-object / unparseable body yields ``{}``.
    """
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001 - malformed body -> empty payload (SCIM 400 later)
        return {}
    return data if isinstance(data, dict) else {}


# =========================================================================== #
# SCIM 2.0 provisioning (BEARER-token authenticated; tenant-scoped)
# =========================================================================== #
@router.get(
    "/scim/v2/{workspace_id}/Users",
    summary="SCIM 2.0: list the workspace's provisioned users (tenant-scoped)",
)
def scim_list_users(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
    filter: str = Query(default="", description="SCIM filter (userName/email eq)"),
    startIndex: int = Query(default=1, ge=1),
    count: int = Query(default=100, ge=1, le=1000),
):
    """Return a SCIM ListResponse of the token's workspace users (tenant-scoped).

    Only the authenticated token's workspace is ever enumerated — a token for
    another workspace can never list these.
    """
    request_id = base.get_task_id(request)
    unavailable = _scim_backend_error(request_id)
    if unavailable is not None:
        return unavailable
    enforce_rate_limit(
        request,
        f"scim:{workspace_id}",
        limit=_scim_rate_limit(),
        window_s=_scim_rate_window_s(),
    )
    try:
        with get_session() as session:
            scim.auth_token(session, workspace_id, _bearer(request))
            result = scim.list_users(
                session,
                workspace_id,
                filter or None,
                start_index=startIndex,
                count=count,
            )
        return _scim_json(200, result)
    except scim.ScimAuthError as exc:
        return _scim_error(401, str(exc))
    except scim.ScimError as exc:  # noqa: BLE001 - map any SCIM failure to 400
        return _scim_error(400, str(exc))


@router.get(
    "/scim/v2/{workspace_id}/Users/{resource_id}",
    summary="SCIM 2.0: fetch one provisioned user (tenant-scoped)",
)
def scim_get_user(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
    resource_id: str = Path(..., description="SCIM user (ExternalIdentity) id"),
):
    """Return one SCIM User by id — ``404`` across tenants (never leaks existence)."""
    request_id = base.get_task_id(request)
    unavailable = _scim_backend_error(request_id)
    if unavailable is not None:
        return unavailable
    enforce_rate_limit(
        request,
        f"scim:{workspace_id}",
        limit=_scim_rate_limit(),
        window_s=_scim_rate_window_s(),
    )
    try:
        with get_session() as session:
            scim.auth_token(session, workspace_id, _bearer(request))
            result = scim.get_user(session, workspace_id, resource_id)
        return _scim_json(200, result)
    except scim.ScimAuthError as exc:
        return _scim_error(401, str(exc))
    except scim.ScimNotFoundError as exc:
        return _scim_error(404, str(exc), "notFound")
    except scim.ScimError as exc:
        return _scim_error(400, str(exc))


@router.post(
    "/scim/v2/{workspace_id}/Users",
    summary="SCIM 2.0: provision (create/link) a user (tenant-scoped; audited)",
)
async def scim_create_user(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Provision a user into the token's workspace (SCIM Create -> ``201``).

    Idempotent by ``(workspace_id, externalId)``: re-provisioning re-activates the
    existing identity. Every write is scoped to the token's workspace and audited.
    """
    request_id = base.get_task_id(request)
    unavailable = _scim_backend_error(request_id)
    if unavailable is not None:
        return unavailable
    enforce_rate_limit(
        request,
        f"scim:{workspace_id}",
        limit=_scim_rate_limit(),
        window_s=_scim_rate_window_s(),
    )
    payload = await _read_json(request)
    try:
        with get_session() as session:
            scim.auth_token(session, workspace_id, _bearer(request))
            result = scim.provision_user(session, workspace_id, payload)
        return _scim_json(201, result)
    except scim.ScimAuthError as exc:
        return _scim_error(401, str(exc))
    except scim.ScimError as exc:
        return _scim_error(400, str(exc), "invalidValue")


@router.put(
    "/scim/v2/{workspace_id}/Users/{resource_id}",
    summary="SCIM 2.0: replace a provisioned user (tenant-scoped; audited)",
)
async def scim_put_user(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
    resource_id: str = Path(..., description="SCIM user (ExternalIdentity) id"),
):
    """Apply a SCIM PUT (e.g. toggle ``active``, update email) — tenant-scoped."""
    return await _scim_update(request, workspace_id, resource_id)


@router.patch(
    "/scim/v2/{workspace_id}/Users/{resource_id}",
    summary="SCIM 2.0: patch a provisioned user (tenant-scoped; audited)",
)
async def scim_patch_user(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
    resource_id: str = Path(..., description="SCIM user (ExternalIdentity) id"),
):
    """Apply a SCIM PatchOp (e.g. deactivate via ``active=false``) — tenant-scoped."""
    return await _scim_update(request, workspace_id, resource_id)


async def _scim_update(
    request: Request, workspace_id: str, resource_id: str
) -> JSONResponse:
    """Shared PUT/PATCH body: authenticate then apply the update (tenant-scoped)."""
    request_id = base.get_task_id(request)
    unavailable = _scim_backend_error(request_id)
    if unavailable is not None:
        return unavailable
    enforce_rate_limit(
        request,
        f"scim:{workspace_id}",
        limit=_scim_rate_limit(),
        window_s=_scim_rate_window_s(),
    )
    payload = await _read_json(request)
    try:
        with get_session() as session:
            scim.auth_token(session, workspace_id, _bearer(request))
            result = scim.update_user(session, workspace_id, resource_id, payload)
        return _scim_json(200, result)
    except scim.ScimAuthError as exc:
        return _scim_error(401, str(exc))
    except scim.ScimNotFoundError as exc:
        return _scim_error(404, str(exc), "notFound")
    except scim.ScimError as exc:
        return _scim_error(400, str(exc), "invalidValue")


@router.delete(
    "/scim/v2/{workspace_id}/Users/{resource_id}",
    summary="SCIM 2.0: deactivate (soft-deprovision) a user (tenant-scoped; audited)",
)
def scim_delete_user(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
    resource_id: str = Path(..., description="SCIM user (ExternalIdentity) id"),
):
    """Soft-deactivate a user (SCIM Delete -> ``provisioned=False``; row retained).

    Membership is removed but the :class:`ExternalIdentity` is kept for audit /
    re-activation. Returns the deactivated resource (``200``); ``404`` across
    tenants.
    """
    request_id = base.get_task_id(request)
    unavailable = _scim_backend_error(request_id)
    if unavailable is not None:
        return unavailable
    enforce_rate_limit(
        request,
        f"scim:{workspace_id}",
        limit=_scim_rate_limit(),
        window_s=_scim_rate_window_s(),
    )
    try:
        with get_session() as session:
            scim.auth_token(session, workspace_id, _bearer(request))
            result = scim.deactivate_user(session, workspace_id, resource_id)
        return _scim_json(200, result)
    except scim.ScimAuthError as exc:
        return _scim_error(401, str(exc))
    except scim.ScimNotFoundError as exc:
        return _scim_error(404, str(exc), "notFound")
    except scim.ScimError as exc:
        return _scim_error(400, str(exc))


# --------------------------------------------------------------------------- #
# SCIM 2.0 Groups (minimal — membership sync over the tenant's identities)
# --------------------------------------------------------------------------- #
@router.get(
    "/scim/v2/{workspace_id}/Groups",
    summary="SCIM 2.0: list groups (minimal — membership is synced, not stored)",
)
def scim_list_groups(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Return an empty SCIM ListResponse.

    ReelForge does not model SCIM Groups as first-class resources; group
    membership is applied via PUT/PATCH (:func:`app.services.scim.sync_group_members`)
    but there is no group store to enumerate.
    """
    request_id = base.get_task_id(request)
    unavailable = _scim_backend_error(request_id)
    if unavailable is not None:
        return unavailable
    try:
        with get_session() as session:
            scim.auth_token(session, workspace_id, _bearer(request))
        return _scim_json(
            200,
            {
                "schemas": [_SCIM_LIST_SCHEMA],
                "totalResults": 0,
                "startIndex": 1,
                "itemsPerPage": 0,
                "Resources": [],
            },
        )
    except scim.ScimAuthError as exc:
        return _scim_error(401, str(exc))
    except scim.ScimError as exc:
        return _scim_error(400, str(exc))


@router.put(
    "/scim/v2/{workspace_id}/Groups/{resource_id}",
    summary="SCIM 2.0: sync a group's members (tenant-scoped)",
)
async def scim_put_group(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
    resource_id: str = Path(..., description="SCIM group id (opaque)"),
):
    """Sync a SCIM group's members over the tenant's provisioned identities."""
    return await _scim_group_sync(request, workspace_id, resource_id)


@router.patch(
    "/scim/v2/{workspace_id}/Groups/{resource_id}",
    summary="SCIM 2.0: patch a group's members (tenant-scoped)",
)
async def scim_patch_group(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
    resource_id: str = Path(..., description="SCIM group id (opaque)"),
):
    """Patch a SCIM group's members over the tenant's provisioned identities."""
    return await _scim_group_sync(request, workspace_id, resource_id)


async def _scim_group_sync(
    request: Request, workspace_id: str, resource_id: str
) -> JSONResponse:
    """Authenticate, extract member subjects, and sync membership (tenant-scoped)."""
    request_id = base.get_task_id(request)
    unavailable = _scim_backend_error(request_id)
    if unavailable is not None:
        return unavailable
    enforce_rate_limit(
        request,
        f"scim:{workspace_id}",
        limit=_scim_rate_limit(),
        window_s=_scim_rate_window_s(),
    )
    payload = await _read_json(request)
    subjects = _group_member_subjects(payload)
    display = str(payload.get("displayName") or resource_id)
    try:
        with get_session() as session:
            scim.auth_token(session, workspace_id, _bearer(request))
            summary = scim.sync_group_members(session, workspace_id, subjects)
        return _scim_json(
            200,
            {
                "schemas": [_SCIM_GROUP_SCHEMA],
                "id": resource_id,
                "displayName": display,
                "members": [
                    {"value": s} for s in (summary.get("updated") or [])
                ],
            },
        )
    except scim.ScimAuthError as exc:
        return _scim_error(401, str(exc))
    except scim.ScimError as exc:
        return _scim_error(400, str(exc))


def _group_member_subjects(payload: dict[str, Any]) -> list[str]:
    """Extract member subject ids from a SCIM Group PUT or PatchOp body."""
    subjects: list[str] = []
    members = payload.get("members")
    if isinstance(members, list):
        for m in members:
            if isinstance(m, dict) and m.get("value"):
                subjects.append(str(m["value"]))
    operations = payload.get("Operations") or payload.get("operations")
    if isinstance(operations, list):
        for op in operations:
            if not isinstance(op, dict):
                continue
            value = op.get("value")
            if isinstance(value, list):
                for m in value:
                    if isinstance(m, dict) and m.get("value"):
                        subjects.append(str(m["value"]))
    return subjects


# =========================================================================== #
# SCIM token management (USER-authenticated + RBAC workspace.settings)
# =========================================================================== #
def _require_backend(request_id: str) -> None:
    """Raise 503 (MPT envelope) when the DB layer or SCIM service is unavailable."""
    _require_db(request_id)
    if scim is None or rbac is None or ScimTokenRepository is None:
        logger.error(
            f"scim token service unavailable, request_id: {request_id}, "
            f"error: {_SCIM_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: SCIM service is not available",
        )


def _load_workspace_or_404(session: Any, workspace_id: str, request_id: str):
    """Return the workspace row, or raise a clean ``404`` when it does not exist."""
    workspace = WorkspaceRepository(session).get(workspace_id)
    if workspace is None:
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"{request_id}: workspace not found",
        )
    return workspace


def _client_ip(request: Request) -> Optional[str]:
    """Best-effort source IP of the caller for the audit row (never raises)."""
    try:
        client = getattr(request, "client", None)
        return getattr(client, "host", None) if client is not None else None
    except Exception:  # noqa: BLE001 - IP is best-effort telemetry
        return None


def _isoformat(value: Any) -> Optional[str]:
    """Best-effort ISO-8601 rendering of a timestamp; ``None`` stays ``None``."""
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:  # noqa: BLE001 - defensive
        return str(value)


def _token_public_data(row: Any, raw_token: Optional[str] = None) -> dict[str, Any]:
    """Serialise a :class:`ScimToken` row; include the raw ``token`` ONLY on mint."""
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "prefix": getattr(row, "prefix", "") or "",
        "token": raw_token,
        "revoked": bool(getattr(row, "revoked", False)),
        "last_used_at": _isoformat(getattr(row, "last_used_at", None)),
        "created_at": _isoformat(getattr(row, "created_at", None)),
    }


def _require_settings(session: Any, request: Request, workspace_id: str, request_id: str):
    """Resolve the caller + gate on ``workspace.settings`` (403 non-admin / 404 unknown ws)."""
    user = _resolve_user(request, session, request_id)
    _load_workspace_or_404(session, workspace_id, request_id)
    try:
        rbac.require_permission(
            session, user.id, workspace_id, rbac.PERM_WORKSPACE_SETTINGS
        )
    except PermissionError as exc:
        raise HttpException(
            task_id=request_id, status_code=403, message=f"{request_id}: {exc}"
        )
    return user


@router.post(
    "/me/workspaces/{workspace_id}/scim/tokens",
    response_model=ScimTokenCreatedResponse,
    summary="Mint a SCIM bearer token (workspace.settings; shown once; audited)",
)
def create_scim_token(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Mint a per-workspace SCIM bearer token (RBAC ``workspace.settings``).

    The raw token is returned EXACTLY ONCE here (store it now — only its SHA-256
    digest is persisted). Writes a ``scim.token_created`` audit row.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        user = _require_settings(session, request, workspace_id, request_id)
        row, raw_token = scim.create_token(
            session,
            workspace_id,
            actor_user_id=user.id,
            actor_ip=_client_ip(request),
        )
        data = _token_public_data(row, raw_token=raw_token)

    return utils.get_response(200, data)


@router.get(
    "/me/workspaces/{workspace_id}/scim/tokens",
    response_model=ScimTokenListResponse,
    summary="List a workspace's SCIM tokens (workspace.settings; never a raw token)",
)
def list_scim_tokens(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """List the workspace's SCIM tokens (ids/prefixes/status; NEVER a raw token)."""
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        _require_settings(session, request, workspace_id, request_id)
        rows = ScimTokenRepository(session).list_for_workspace(workspace_id)
        data = [_token_public_data(r) for r in rows]

    return utils.get_response(200, data)


@router.delete(
    "/me/workspaces/{workspace_id}/scim/tokens/{token_id}",
    summary="Revoke a SCIM token (workspace.settings; audited)",
)
def revoke_scim_token(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
    token_id: str = Path(..., description="SCIM token id"),
):
    """Revoke a workspace's SCIM token (RBAC ``workspace.settings``). ``404`` when unknown.

    Workspace-scoped: a caller can never revoke another workspace's token. Writes a
    ``scim.token_revoked`` audit row on a real revocation.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        user = _require_settings(session, request, workspace_id, request_id)
        revoked = scim.revoke_token(
            session,
            workspace_id,
            token_id,
            actor_user_id=user.id,
            actor_ip=_client_ip(request),
        )
        if not revoked:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: SCIM token not found",
            )

    return utils.get_response(200, {"revoked": True, "token_id": token_id})
