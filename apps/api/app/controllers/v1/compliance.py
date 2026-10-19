"""Caller-scoped GDPR compliance controller (Compliance, Epic 5).

The per-user, auth-gated data-governance surface mounted under ``/api/v1``. Every
route resolves the caller via ``_resolve_user`` and acts ONLY on that caller (or a
workspace the caller is RBAC-permitted to configure) — no path can ever export,
erase, read or write another user's data.

Routes
------
* ``POST /me/data-export``                    — assemble the caller's COMPLETE data
  package, upload it to R2 under an owner-scoped key, and return a SHORT-LIVED
  presigned download link (GDPR Art. 15 / 20). Strictly caller-scoped; audited.
* ``POST /me/erase``                          — request erasure of the CALLER'S OWN
  account (GDPR Art. 17). Requires an explicit ``confirm=true`` step; anonymizes
  PII in place while preserving financial/audit records; audited. No target id is
  accepted, so a caller can only ever erase themselves.
* ``GET  /me/consent``                        — the caller's consent trail (or, with
  ``?kind=``, the current decision for one dimension). Caller-scoped.
* ``PUT  /me/consent``                        — record a consent decision for the
  caller (append-only); audited.
* ``GET  /me/workspaces/{id}/retention``      — read a workspace's retention policy
  (RBAC ``workspace.settings`` — a viewer/non-member gets 403).
* ``PUT  /me/workspaces/{id}/retention``      — set a workspace's retention window
  (RBAC ``workspace.settings``); audited.

Design notes
------------
* **Auth + persistence guard reused.** ``_require_db`` / ``_resolve_user`` /
  ``get_session`` are imported from :mod:`app.controllers.v1.jobs` (the canonical
  guard), so both auth paths (Clerk JWT + ``x-api-key``) behave identically to the
  rest of the API and this module stays import-safe.
* **Import-safe compliance services.** The Epic-5 services are imported optionally;
  when absent every endpoint degrades to a clean ``503`` (never an ImportError at
  startup), mirroring :mod:`app.controllers.v1.admin`.
* Every response uses the MPT envelope ``utils.get_response`` and every error is
  raised as :class:`HttpException`.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Path, Query, Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.models.schema import (
    ConsentResponse,
    ConsentUpdateRequest,
    DataExportResponse,
    ErasureConfirmRequest,
    ErasureRequestResponse,
    RetentionPolicyResponse,
    RetentionUpdateRequest,
)
from app.utils import utils

# Guarded import of the Epic-5 compliance services (see admin.py for the
# import-safety rationale). A partial environment degrades to a clean 503.
try:  # pragma: no cover - exercised implicitly by the API tests
    from app.services.compliance import consent as consent_service
    from app.services.compliance import erasure as erasure_service
    from app.services.compliance import export as export_service
    from app.services.compliance import retention as retention_service

    _COMPLIANCE_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # noqa: BLE001 - import-safe: never crash the module
    consent_service = None  # type: ignore[assignment]
    erasure_service = None  # type: ignore[assignment]
    export_service = None  # type: ignore[assignment]
    retention_service = None  # type: ignore[assignment]
    _COMPLIANCE_IMPORT_ERROR = exc

router = new_router()


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _require_compliance(request_id: str) -> None:
    """Raise 503 when the DB layer or the compliance services are absent."""
    _require_db(request_id)
    if _COMPLIANCE_IMPORT_ERROR is not None or export_service is None:
        logger.error(
            f"compliance services unavailable, request_id: {request_id}, "
            f"error: {_COMPLIANCE_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: compliance service is not available",
        )


def _isoformat(value: Any) -> Optional[str]:
    """Best-effort ISO-8601 rendering of a timestamp; ``None`` stays ``None``."""
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:  # noqa: BLE001 - never fail a response on a timestamp
        return str(value)


def _erasure_data(request: Any) -> dict[str, Any]:
    """Serialize an :class:`ErasureRequest` row to its public envelope."""
    return {
        "id": request.id,
        "user_id": request.user_id,
        "status": request.status,
        "scope": request.scope,
        "requested_at": _isoformat(getattr(request, "requested_at", None)),
        "completed_at": _isoformat(getattr(request, "completed_at", None)),
    }


def _consent_data(record: Any) -> dict[str, Any]:
    """Serialize a :class:`ConsentRecord` row to its public envelope."""
    return {
        "id": record.id,
        "kind": record.kind,
        "granted": bool(record.granted),
        "version": record.version,
        "created_at": _isoformat(getattr(record, "created_at", None)),
    }


def _policy_data(workspace_id: str, policy: Any) -> dict[str, Any]:
    """Serialize a :class:`RetentionPolicy` (or an unset policy) to its envelope."""
    if policy is None:
        return {
            "workspace_id": workspace_id,
            "jobs_retention_days": None,
            "assets_retention_days": None,
            "created_at": None,
            "updated_at": None,
        }
    return {
        "workspace_id": policy.workspace_id,
        "jobs_retention_days": policy.jobs_retention_days,
        "assets_retention_days": policy.assets_retention_days,
        "created_at": _isoformat(getattr(policy, "created_at", None)),
        "updated_at": _isoformat(getattr(policy, "updated_at", None)),
    }


# --------------------------------------------------------------------------- #
# Data export (GDPR Art. 15 / 20) — strictly caller-scoped
# --------------------------------------------------------------------------- #
@router.post(
    "/me/data-export",
    response_model=DataExportResponse,
    summary="Export ALL of the caller's own data (short-lived download link)",
)
def me_data_export(request: Request):
    """Assemble the caller's COMPLETE data package and return a signed download URL.

    The package contains ONLY the requesting caller's own rows (profile, jobs,
    asset metadata, personal credit ledger, the financials of workspaces they own,
    consent trail, memberships). It is uploaded to R2 under an owner-scoped key and
    handed back as a SHORT-LIVED presigned GET link — never a public URL. Audited.
    """
    request_id = base.get_task_id(request)
    _require_compliance(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            url = export_service.build_export(
                session, user.id, actor_user_id=user.id
            )
        except HttpException:
            raise
        except Exception as exc:  # noqa: BLE001 - export/upload failure -> 502
            logger.error(
                f"data export failed for {user.id}, request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=502,
                message=f"{request_id}: failed to build data export",
            )
        data = {
            "download_url": url,
            "expires_in": int(
                getattr(export_service, "EXPORT_URL_EXPIRES", 900)
            ),
        }
    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# Right to erasure (GDPR Art. 17) — the caller's OWN account only
# --------------------------------------------------------------------------- #
@router.post(
    "/me/erase",
    response_model=ErasureRequestResponse,
    summary="Erase (anonymize) the caller's OWN account — requires confirmation",
)
def me_erase(request: Request, body: ErasureConfirmRequest):
    """Anonymize the CALLER'S OWN PII in place (irreversible; requires confirmation).

    A deliberate ``confirm=true`` step is required — a missing/false confirmation
    is a ``400`` and nothing is erased. On confirm, the caller's PII is tombstoned,
    their credentials revoked and their job scripts/prompts blanked, WHILE
    preserving financial/audit records and referential integrity. The action is
    audited. No target id is accepted, so a caller can only ever erase themselves.
    """
    request_id = base.get_task_id(request)
    _require_compliance(request_id)

    with get_session() as session:
        # Resolve auth FIRST so an unauthenticated caller gets 401 (not 400)
        # before the confirmation gate runs.
        user = _resolve_user(request, session, request_id)
        if not bool(getattr(body, "confirm", False)):
            raise HttpException(
                task_id=request_id,
                status_code=400,
                message=(
                    f"{request_id}: erasure requires confirm=true "
                    f"(this action is irreversible)"
                ),
            )
        try:
            erased = erasure_service.erase_user(
                session, user.id, actor_user_id=user.id
            )
        except HttpException:
            raise
        except Exception as exc:  # noqa: BLE001 - anonymization failure -> 502
            logger.error(
                f"erasure failed for {user.id}, request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=502,
                message=f"{request_id}: failed to erase account",
            )
        data = _erasure_data(erased)
    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# Consent (GDPR / SOC2) — caller-scoped
# --------------------------------------------------------------------------- #
@router.get(
    "/me/consent",
    response_model=ConsentResponse,
    summary="Read the caller's consent trail (or the current decision for a kind)",
)
def me_get_consent(
    request: Request,
    kind: Optional[str] = Query(
        default=None,
        max_length=60,
        description="When set, return the current (newest) decision for this kind.",
    ),
):
    """Return the caller's consent trail, or the current decision for one ``kind``.

    With no ``kind`` the full trail (oldest first) is returned as a list; with
    ``?kind=`` the current (newest) decision for that dimension is returned (or
    ``null`` when none exists). Strictly caller-scoped.
    """
    request_id = base.get_task_id(request)
    _require_compliance(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        selected = (kind or "").strip()
        if selected:
            record = consent_service.get_consent(session, user.id, selected)
            data: Any = _consent_data(record) if record is not None else None
        else:
            data = [
                _consent_data(c)
                for c in consent_service.list_consents(session, user.id)
            ]
    return utils.get_response(200, data)


@router.put(
    "/me/consent",
    response_model=ConsentResponse,
    summary="Record a consent decision for the caller (append-only, audited)",
)
def me_put_consent(request: Request, body: ConsentUpdateRequest):
    """Append an immutable consent decision for the caller and audit it.

    ``kind`` is the consent dimension (required); ``granted`` records
    grant/withdrawal; ``version`` is the policy version. The decision is always
    recorded for the CALLER — never another user.
    """
    request_id = base.get_task_id(request)
    _require_compliance(request_id)

    kind = (getattr(body, "kind", "") or "").strip()
    if not kind:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: consent kind is required",
        )

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            record = consent_service.record_consent(
                session,
                user.id,
                kind,
                bool(getattr(body, "granted", False)),
                version=str(getattr(body, "version", "") or ""),
            )
        except ValueError as exc:
            raise HttpException(
                task_id=request_id, status_code=400, message=f"{request_id}: {exc}"
            )
        except HttpException:
            raise
        except Exception as exc:  # noqa: BLE001 - persistence failure -> 502
            logger.error(
                f"record consent failed for {user.id}, "
                f"request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=502,
                message=f"{request_id}: failed to record consent",
            )
        data = _consent_data(record)
    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# Retention policy (RBAC ``workspace.settings``) — tenant-scoped
# --------------------------------------------------------------------------- #
@router.get(
    "/me/workspaces/{workspace_id}/retention",
    response_model=RetentionPolicyResponse,
    summary="Read a workspace's retention policy (RBAC workspace.settings)",
)
def me_get_retention(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Return a workspace's retention policy (``workspace.settings``-gated).

    A non-member or under-privileged caller (e.g. a viewer) gets ``403`` and never
    learns another tenant's retention posture. Returns the policy, or a
    keep-forever default when none is configured yet.
    """
    request_id = base.get_task_id(request)
    _require_compliance(request_id)
    wsid = (workspace_id or "").strip()

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            policy = retention_service.get_policy(session, user.id, wsid)
        except PermissionError as exc:
            raise HttpException(
                task_id=request_id, status_code=403, message=f"{request_id}: {exc}"
            )
        except HttpException:
            raise
        except Exception as exc:  # noqa: BLE001 - read failure -> 502
            logger.error(
                f"get retention failed for ws={wsid}, "
                f"request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=502,
                message=f"{request_id}: failed to read retention policy",
            )
        data = _policy_data(wsid, policy)
    return utils.get_response(200, data)


@router.put(
    "/me/workspaces/{workspace_id}/retention",
    response_model=RetentionPolicyResponse,
    summary="Set a workspace's retention window (RBAC workspace.settings, audited)",
)
def me_put_retention(
    request: Request,
    body: RetentionUpdateRequest,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Set a workspace's retention window (``workspace.settings``-gated; audited).

    A full replace of both windows: ``None`` means keep-forever; a negative value
    is a ``400``. Only a workspace owner/admin may set it — a viewer/non-member
    gets ``403`` BEFORE any write, and no other tenant's data is ever touched.
    """
    request_id = base.get_task_id(request)
    _require_compliance(request_id)
    wsid = (workspace_id or "").strip()

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            policy = retention_service.set_policy(
                session,
                user.id,
                wsid,
                jobs_retention_days=body.jobs_retention_days,
                assets_retention_days=body.assets_retention_days,
            )
        except PermissionError as exc:
            raise HttpException(
                task_id=request_id, status_code=403, message=f"{request_id}: {exc}"
            )
        except ValueError as exc:
            raise HttpException(
                task_id=request_id, status_code=400, message=f"{request_id}: {exc}"
            )
        except HttpException:
            raise
        except Exception as exc:  # noqa: BLE001 - write failure -> 502
            logger.error(
                f"set retention failed for ws={wsid}, "
                f"request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=502,
                message=f"{request_id}: failed to set retention policy",
            )
        data = _policy_data(wsid, policy)
    return utils.get_response(200, data)
