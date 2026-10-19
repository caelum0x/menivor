"""Enterprise SSO v1 API controller (Identity & SSO, Epic 2).

Two surfaces, both under ``/api/v1`` and both import-safe (a missing service/DB
layer degrades to a clean ``503`` at request time, never an ``ImportError`` at
startup):

**1. The SAML login flow (UNAUTHENTICATED — this IS how a user signs in).**

* ``GET  /sso/{workspace_id}/metadata`` — the SP (service-provider) SAML metadata
  the IdP consumes to learn the ACS/entityID. Served as raw
  ``application/samlmetadata+xml``. No secret is ever included.
* ``GET  /sso/{workspace_id}/login``    — SP-initiated login: build the
  DEFLATE+base64 ``AuthnRequest`` redirect and 302 the browser to the IdP (pure
  python — no xmlsec). A missing/disabled connection is a clean ``404``.
* ``POST /sso/{workspace_id}/acs``      — the Assertion Consumer Service. The
  posted ``SAMLResponse`` is validated ENTIRELY by python3-saml through
  :func:`app.services.sso.process_acs` (signature / audience / ``NotOnOrAfter`` /
  replay / email-domain). On success a ReelForge session token is issued from the
  validated grant; **any** validation failure is a ``401`` and issues NOTHING — an
  unsigned or foreign assertion is NEVER trusted. When the native ``xmlsec`` lib
  is absent the endpoint degrades to ``503`` ("SSO unavailable").

**Availability (MN7a).** SSO is not sold yet (real SSO is MN7b, Wave F). Until
``MENIVOR_SSO_ENABLED=1`` (or ``[app] menivor_sso_enabled = true``), every route
below answers ``501`` with a "contact sales" message. The code stays in place
behind that flag; nothing is removed.

**2. Connection management (AUTHENTICATED + RBAC ``workspace.settings``).**

* ``GET    /me/workspaces/{id}/sso`` — the cert-free connection status.
* ``PUT    /me/workspaces/{id}/sso`` — configure the IdP connection (the signing
  cert / OIDC secret are encrypted at the service boundary, never returned).
* ``DELETE /me/workspaces/{id}/sso`` — remove the connection.

Every mutating operation writes an Epic-1 audit row. Tenant isolation: a
connection is scoped to ONE workspace and can never authenticate into another.
"""

from __future__ import annotations

import secrets
from contextlib import contextmanager
from typing import Any, Iterator, Optional
from xml.sax.saxutils import escape

from fastapi import Depends, Path, Query, Request
from loguru import logger
from starlette.responses import RedirectResponse, Response

from app.controllers import base
from app.controllers.v1.base import new_router

# Reuse the canonical persistence guard + auth helpers from jobs.py (the module
# that owns the guarded DB import). When the DB layer is absent these are ``None``
# and ``_require_db`` raises a clean 503 — this controller stays import-safe.
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.models.schema import (
    SSOConfigRequest,
    SSOConnectionResponse,
    SSOLoginResponse,
    SSOMetadataResponse,
    SSOSessionResponse,
)
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

# --------------------------------------------------------------------------- #
# Guarded imports of the SSO service + persistence (authored by sibling agents /
# depend on the DB layer). A partial environment degrades to a 503 rather than
# crashing at import time.
# --------------------------------------------------------------------------- #
try:  # pragma: no cover - exercised implicitly by the API tests
    from app.models.db.repositories import (
        SSOConnectionRepository,
        WorkspaceRepository,
    )
    from app.services import audit as audit_service
    from app.services import rbac, sso

    _SSO_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # noqa: BLE001 - import-safe: never crash the module
    SSOConnectionRepository = None  # type: ignore[assignment,misc]
    WorkspaceRepository = None  # type: ignore[assignment,misc]
    audit_service = None  # type: ignore[assignment]
    rbac = None  # type: ignore[assignment]
    sso = None  # type: ignore[assignment]
    _SSO_IMPORT_ERROR = exc

#: Where the 501 sends an interested team (the general inbox handles sales).
SSO_SALES_EMAIL: str = "hello@menivor.com"
SSO_FLAG_ENV: str = "MENIVOR_SSO_ENABLED"


def sso_enabled() -> bool:
    """Whether SSO routes are live. Off by default until real SSO ships (MN7b)."""
    import os

    raw = os.environ.get(SSO_FLAG_ENV)
    if raw is None:
        from app.config import config

        raw = str(config.app.get("menivor_sso_enabled", ""))
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _require_sso_available(request: Request) -> None:
    """Answer 501 "contact sales" on every SSO route while the flag is off."""
    if sso_enabled():
        return
    request_id = base.get_task_id(request)
    raise HttpException(
        task_id=request_id,
        status_code=501,
        message=(
            f"{request_id}: Single sign-on is available on Enterprise plans. "
            f"Contact sales at {SSO_SALES_EMAIL}."
        ),
    )


router = new_router(dependencies=[Depends(_require_sso_available)])

# ACS is a public, IdP-facing endpoint: rate-limit it per workspace so a flood of
# forged assertions cannot be used to probe/DoS the validator.
_DEFAULT_ACS_RATE_LIMIT: int = 60
_DEFAULT_ACS_RATE_WINDOW_S: int = 60


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _require_backend(request_id: str) -> None:
    """Raise 503 when the DB layer or the SSO service is unavailable."""
    _require_db(request_id)
    if sso is None or rbac is None or SSOConnectionRepository is None:
        logger.error(
            f"sso service unavailable, request_id: {request_id}, "
            f"error: {_SSO_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: SSO service is not available",
        )


@contextmanager
def _map_service_errors(request_id: str) -> Iterator[None]:
    """Translate service-layer exceptions to HTTP errors for the config surface.

    ``PermissionError`` (not a member / lacks ``workspace.settings``) -> ``403``;
    ``ValueError`` (invalid protocol, etc.) -> ``400``. :class:`HttpException`
    passes through untouched.
    """
    try:
        yield
    except HttpException:
        raise
    except PermissionError as exc:
        raise HttpException(
            task_id=request_id, status_code=403, message=f"{request_id}: {exc}"
        )
    except ValueError as exc:
        raise HttpException(
            task_id=request_id, status_code=400, message=f"{request_id}: {exc}"
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


def _connection_public_data(connection: Any) -> dict[str, Any]:
    """Serialise an :class:`SSOConnection` to its CERT-FREE public envelope.

    NEVER includes ``idp_x509_cert_enc`` / ``oidc_client_secret_enc`` (or any
    decrypted secret) — only booleans reporting whether a secret is configured,
    plus the non-secret protocol/URL/status fields.
    """
    return {
        "workspace_id": connection.workspace_id,
        "protocol": connection.protocol,
        "idp_entity_id": connection.idp_entity_id or "",
        "idp_sso_url": connection.idp_sso_url or "",
        "sp_acs_url": connection.sp_acs_url or "",
        "sp_metadata_url": "",
        "oidc_client_id": connection.oidc_client_id,
        "enabled": bool(connection.enabled),
        "has_certificate": bool(getattr(connection, "idp_x509_cert_enc", None)),
        "has_client_secret": bool(getattr(connection, "oidc_client_secret_enc", None)),
        "created_at": _isoformat(getattr(connection, "created_at", None)),
        "updated_at": _isoformat(getattr(connection, "updated_at", None)),
    }


def _sp_metadata_xml(connection: Any) -> str:
    """Build the SP (service-provider) SAML 2.0 metadata XML for a connection.

    Pure string construction (no xmlsec): advertises the SP entityID (the ACS URL,
    mirroring the validator settings) and the HTTP-POST AssertionConsumerService so
    an IdP admin can wire the connection. All values are XML-escaped.
    """
    acs = escape(connection.sp_acs_url or "")
    entity_id = escape(connection.sp_acs_url or "")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<md:EntityDescriptor '
        'xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" '
        f'entityID="{entity_id}">'
        '<md:SPSSODescriptor '
        'protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol" '
        'AuthnRequestsSigned="false" WantAssertionsSigned="true">'
        '<md:NameIDFormat>'
        'urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress'
        '</md:NameIDFormat>'
        '<md:AssertionConsumerService '
        'Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" '
        f'Location="{acs}" index="0" isDefault="true"/>'
        '</md:SPSSODescriptor>'
        '</md:EntityDescriptor>'
    )


def _acs_rate_limit() -> int:
    """Max ACS posts per window per workspace (``reelforge_sso_acs_rate_limit``)."""
    from app.config import config

    return int(config.app.get("reelforge_sso_acs_rate_limit", _DEFAULT_ACS_RATE_LIMIT))


def _acs_rate_window_s() -> int:
    """ACS rate-limit window in seconds (``reelforge_sso_acs_rate_window_s``)."""
    from app.config import config

    return int(
        config.app.get("reelforge_sso_acs_rate_window_s", _DEFAULT_ACS_RATE_WINDOW_S)
    )


# =========================================================================== #
# SAML login flow (UNAUTHENTICATED)
# =========================================================================== #
@router.get(
    "/sso/{workspace_id}/metadata",
    response_model=SSOMetadataResponse,
    summary="SP SAML metadata for a workspace (served as XML; no secrets)",
)
def sso_metadata(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Return the workspace's SP SAML metadata (raw ``application/samlmetadata+xml``).

    Public by design — the IdP admin consumes it to learn the SP entityID + ACS
    URL. A workspace with no SSO connection is a clean ``404`` (nothing to
    describe). No certificate or secret is ever included.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        connection = SSOConnectionRepository(session).get_for_workspace(workspace_id)
        if connection is None:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: no SSO connection for this workspace",
            )
        xml = _sp_metadata_xml(connection)

    return Response(content=xml, media_type="application/samlmetadata+xml")


@router.get(
    "/sso/{workspace_id}/login",
    response_model=SSOLoginResponse,
    summary="SP-initiated SAML login: redirect the browser to the IdP",
)
def sso_login(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
    relay_state: str = Query(default="", max_length=2000, description="Opaque RelayState"),
):
    """Build the SP-initiated ``AuthnRequest`` redirect and 302 the browser to the IdP.

    Pure-python (DEFLATE+base64) — works WITHOUT the native ``xmlsec`` lib. A
    missing or disabled connection (nothing to log in against) is a clean ``404``.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        connection = SSOConnectionRepository(session).get_for_workspace(workspace_id)
        if connection is None or not connection.enabled:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: SSO is not configured for this workspace",
            )
        try:
            redirect_url = sso.build_login_redirect(connection, relay_state)
        except sso.SsoConfigError as exc:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: {exc}",
            )

    return RedirectResponse(url=redirect_url, status_code=302)


@router.post(
    "/sso/{workspace_id}/acs",
    response_model=SSOSessionResponse,
    summary="SAML Assertion Consumer Service: validate the assertion, issue a session",
)
async def sso_acs(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Consume a posted ``SAMLResponse``: validate it, then issue a session token.

    The assertion is validated ENTIRELY by python3-saml via
    :func:`app.services.sso.process_acs` (signature / audience / ``NotOnOrAfter`` /
    replay / email-domain). Mapping of a failure to HTTP:

    * validation failed (bad signature / unsigned / foreign assertion) -> ``401``
      — NEVER trusted, no session issued;
    * ``xmlsec`` lib absent (cannot validate) -> ``503`` ("SSO unavailable");
    * replay of an already-consumed assertion -> ``409``;
    * email domain not permitted -> ``403``;
    * no/disabled SSO connection -> ``404``.

    On success a ReelForge session token is minted from the validated grant and
    returned; the token is derived only from a VALIDATED assertion.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    try:
        form = await request.form()
    except Exception:  # noqa: BLE001 - malformed body -> treat as a validation failure
        form = {}
    saml_response = str(form.get("SAMLResponse") or "").strip()
    relay_state = str(form.get("RelayState") or "")
    if not saml_response:
        raise HttpException(
            task_id=request_id,
            status_code=401,
            message=f"{request_id}: missing SAMLResponse",
        )

    enforce_rate_limit(
        request,
        f"sso_acs:{workspace_id}",
        limit=_acs_rate_limit(),
        window_s=_acs_rate_window_s(),
    )

    with get_session() as session:
        try:
            grant = sso.process_acs(
                session,
                workspace_id,
                saml_response,
                relay_state,
                actor_ip=_client_ip(request),
            )
        except sso.SsoUnavailableError as exc:
            logger.error(f"sso acs unavailable, request_id: {request_id}: {exc}")
            raise HttpException(
                task_id=request_id,
                status_code=503,
                message=f"{request_id}: SSO is unavailable",
            )
        except sso.SsoConfigError as exc:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: {exc}",
            )
        except sso.SsoReplayError as exc:
            raise HttpException(
                task_id=request_id,
                status_code=409,
                message=f"{request_id}: {exc}",
            )
        except sso.SsoDomainError as exc:
            raise HttpException(
                task_id=request_id,
                status_code=403,
                message=f"{request_id}: {exc}",
            )
        except sso.SsoValidationError as exc:
            # A bad / unsigned / foreign assertion is NEVER trusted -> 401.
            logger.warning(
                f"sso assertion rejected, request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=401,
                message=f"{request_id}: SAML assertion is not valid",
            )
        except sso.SsoError as exc:
            # Any other SSO failure defaults to a hard reject (never a soft grant).
            logger.warning(f"sso acs failed, request_id: {request_id}: {exc}")
            raise HttpException(
                task_id=request_id,
                status_code=401,
                message=f"{request_id}: SAML assertion is not valid",
            )

        # SESSION ISSUANCE — mint an opaque bearer session token from the validated
        # grant. It is derived only from a VALIDATED assertion (every failure above
        # short-circuits before reaching here), never from unsigned/foreign input.
        session_token = secrets.token_urlsafe(32)
        data = {
            "session_token": session_token,
            "token_type": "Bearer",
            "user_id": grant.user_id,
            "workspace_id": grant.workspace_id,
            "email": grant.email,
            "role": grant.role,
            "is_new_user": bool(grant.is_new_user),
        }

    return utils.get_response(200, data)


# =========================================================================== #
# Connection management (AUTHENTICATED + RBAC workspace.settings)
# =========================================================================== #
@router.get(
    "/me/workspaces/{workspace_id}/sso",
    response_model=SSOConnectionResponse,
    summary="Read a workspace's SSO connection status (cert-free; workspace.settings)",
)
def get_sso_connection(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Return the workspace's cert-free SSO connection (``data: null`` when unset).

    Gated by ``workspace.settings`` (admin/owner) — a non-member or viewer gets a
    ``403`` (real workspace) / ``404`` (unknown id). The IdP signing cert / OIDC
    secret are NEVER returned — only ``has_certificate`` / ``has_client_secret``.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        _load_workspace_or_404(session, workspace_id, request_id)
        with _map_service_errors(request_id):
            rbac.require_permission(
                session, user.id, workspace_id, rbac.PERM_WORKSPACE_SETTINGS
            )
        connection = SSOConnectionRepository(session).get_for_workspace(workspace_id)
        data = _connection_public_data(connection) if connection is not None else None

    return utils.get_response(200, data)


@router.put(
    "/me/workspaces/{workspace_id}/sso",
    response_model=SSOConnectionResponse,
    summary="Configure a workspace's SSO connection (workspace.settings; audited)",
)
def put_sso_connection(
    request: Request,
    body: SSOConfigRequest,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Create/update the workspace's IdP connection (cert/secret encrypted at rest).

    Gated by ``workspace.settings``. ``protocol`` must be ``saml`` | ``oidc``
    (``400`` otherwise). The IdP signing cert / OIDC secret are Fernet-encrypted at
    the service boundary and NEVER echoed back; the response is the cert-free
    connection. Writes an ``sso.configured`` audit row.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        _load_workspace_or_404(session, workspace_id, request_id)
        with _map_service_errors(request_id):
            rbac.require_permission(
                session, user.id, workspace_id, rbac.PERM_WORKSPACE_SETTINGS
            )
            connection = sso.configure_connection(
                session,
                workspace_id,
                protocol=(body.protocol or "saml").strip().lower(),
                idp_entity_id=body.idp_entity_id or "",
                idp_sso_url=body.idp_sso_url or "",
                idp_x509_cert=body.idp_x509_cert or "",
                sp_acs_url=body.sp_acs_url or "",
                oidc_client_id=body.oidc_client_id or "",
                oidc_client_secret=body.oidc_client_secret or "",
                enabled=bool(body.enabled),
                actor_user_id=user.id,
                actor_ip=_client_ip(request),
            )
        data = _connection_public_data(connection)

    return utils.get_response(200, data)


@router.delete(
    "/me/workspaces/{workspace_id}/sso",
    summary="Delete a workspace's SSO connection (workspace.settings; audited)",
)
def delete_sso_connection(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Remove the workspace's SSO connection. ``404`` when none is configured.

    Gated by ``workspace.settings``. Writes an ``sso.deleted`` audit row on a real
    deletion.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        _load_workspace_or_404(session, workspace_id, request_id)
        with _map_service_errors(request_id):
            rbac.require_permission(
                session, user.id, workspace_id, rbac.PERM_WORKSPACE_SETTINGS
            )
        deleted = SSOConnectionRepository(session).delete(workspace_id)
        if not deleted:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: no SSO connection to delete",
            )
        audit_service.record(
            session,
            actor_user_id=user.id,
            action="sso.deleted",
            workspace_id=workspace_id,
            target_type="sso_connection",
            target_id=workspace_id,
            metadata={},
            ip=_client_ip(request),
        )

    return utils.get_response(200, {"deleted": True, "workspace_id": workspace_id})
