"""Customer webhook-subscription v1 API controller (Enterprise API Platform, Epic 4).

Mounted under ``/api/v1``. This is the TENANT-SCOPED management surface for the
webhook SUBSCRIPTIONS layer — a customer registers a callback ``url`` + the
``event_types`` they want pushed, and each delivery rides the EXISTING hardened,
HMAC-signed, SSRF-guarded :func:`app.services.webhooks.deliver_webhook` primitive
(this controller never re-implements or weakens those guards).

Routes (all gated by RBAC ``workspace.settings`` — owner/admin only)
--------------------------------------------------------------------
* ``POST   /me/workspaces/{id}/webhooks``                 — create a subscription;
  the HMAC signing ``secret`` is returned **exactly once** here.
* ``GET    /me/workspaces/{id}/webhooks``                 — list the workspace's
  subscriptions (the signing secret is NEVER returned).
* ``DELETE /me/workspaces/{id}/webhooks/{sub_id}``        — soft-revoke a subscription.
* ``POST   /me/workspaces/{id}/webhooks/{sub_id}/test``   — send a signed test event.
* ``GET    /me/workspaces/{id}/webhooks/{sub_id}/deliveries`` — recent deliveries + status.
* ``POST   /me/webhooks``                                 — subscribe with no
  workspace id; the caller's own workspace is used (``Personal`` is created
  when they own none). Any signed-in user; no RBAC beyond ownership.
* ``POST   /me/webhooks/workspace``                       — return (or create)
  that workspace, so the developer page can show webhooks to everyone.

Design notes
------------
* **Auth reused.** The canonical ``_resolve_user`` resolver from
  :mod:`app.controllers.v1.jobs` (Clerk JWT / ``x-api-key`` / per-user key) gates
  every route; a missing DB layer degrades to a clean ``503``.
* **Tenant isolation + RBAC.** Every route resolves the workspace (``404`` when
  unknown, so existence never leaks as a bare ``403``) then calls
  ``rbac.require_permission(..., workspace.settings)`` — a non-member or a viewer
  gets ``403`` and can never touch another tenant's subscriptions.
* **SSRF.** A subscription ``url`` is validated through the SAME guard the delivery
  primitive uses BEFORE any row is persisted (in the service); a rejection surfaces
  here as ``400``.
* **Secret hygiene.** The plaintext signing secret leaves the server ONLY in the
  create response; list/get/delivery views are secret-free.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Optional

from fastapi import Path, Query, Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.models.schema import (
    WEBHOOK_EVENT_TYPES,
    WebhookDeliveryListResponse,
    WebhookDeliveryResponse,
    WebhookSubscribeRequest,
    WebhookSubscriptionCreatedResponse,
    WebhookSubscriptionListResponse,
)
from app.utils import utils

# Guarded imports of the subscription service + RBAC + persistence. A partial
# environment degrades to a 503 rather than crashing at import time.
try:  # pragma: no cover - exercised implicitly by the API tests
    from app.models.db.repositories import WorkspaceRepository
    from app.services import rbac
    from app.services import webhook_subscriptions as subs_service

    _WEBHOOKS_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # noqa: BLE001 - import-safe: never crash the module
    WorkspaceRepository = None  # type: ignore[assignment,misc]
    rbac = None  # type: ignore[assignment]
    subs_service = None  # type: ignore[assignment]
    _WEBHOOKS_IMPORT_ERROR = exc

router = new_router()

#: Cap the deliveries page so an untrusted ``limit`` can never trigger a huge scan.
_MAX_DELIVERIES: int = 100
_DEFAULT_DELIVERIES: int = 50


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _require_backend(request_id: str) -> None:
    """Raise 503 when the DB layer or the subscription service is unavailable."""
    _require_db(request_id)
    if subs_service is None or rbac is None or WorkspaceRepository is None:
        logger.error(
            f"webhook-subscription service unavailable, request_id: {request_id}, "
            f"error: {_WEBHOOKS_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: webhook subscription service is not available",
        )


@contextmanager
def _map_service_errors(request_id: str) -> Iterator[None]:
    """Translate service-layer exceptions to HTTP errors.

    ``PermissionError`` (not a member / lacks ``workspace.settings``) -> ``403``;
    a subscription ``ValueError`` (blank/invalid/SSRF-blocked URL, no event types)
    -> ``400``. :class:`HttpException` passes through untouched.
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


def _load_workspace_or_404(session: Any, workspace_id: str, request_id: str) -> None:
    """Raise a clean ``404`` when the workspace does not exist (never a bare 403)."""
    if WorkspaceRepository(session).get(workspace_id) is None:
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"{request_id}: workspace not found",
        )


def _require_settings(session: Any, request: Request, workspace_id: str, request_id: str):
    """Resolve the caller + enforce RBAC ``workspace.settings`` (owner/admin only).

    Resolves the workspace up front (``404`` when unknown), then delegates the
    membership + role decision to ``rbac.require_permission``. A non-member or a
    caller from another tenant is rejected with ``403`` before any subscription is
    touched. Returns the resolved ``User``.
    """
    user = _resolve_user(request, session, request_id)
    _load_workspace_or_404(session, workspace_id, request_id)
    with _map_service_errors(request_id):
        rbac.require_permission(
            session, user.id, workspace_id, rbac.PERM_WORKSPACE_SETTINGS
        )
    return user


def _validate_event_types(event_types: list[str], request_id: str) -> list[str]:
    """Return the requested event types, or raise ``400`` on an unknown one.

    A blank list, or any value outside :data:`WEBHOOK_EVENT_TYPES`, is a clean
    ``400`` so an untrusted event name can never be stored. Order/dedupe is left to
    the service/repository (which normalise on write).
    """
    catalog = set(WEBHOOK_EVENT_TYPES)
    normalized = [str(e or "").strip() for e in (event_types or []) if str(e or "").strip()]
    if not normalized:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: at least one event_type is required",
        )
    unknown = [e for e in normalized if e not in catalog]
    if unknown:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=(
                f"{request_id}: unsupported event_type(s): {', '.join(unknown)}; "
                f"supported: {', '.join(WEBHOOK_EVENT_TYPES)}"
            ),
        )
    return normalized


def _isoformat(value: Any) -> Optional[str]:
    """Best-effort ISO-8601 rendering of a timestamp; ``None`` stays ``None``."""
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:  # noqa: BLE001 - defensive
        return str(value)


def _subscription_data(row: Any) -> dict[str, Any]:
    """Serialise a subscription to its public, SECRET-FREE envelope.

    NEVER includes ``secret_enc`` (or any plaintext secret) — only the id, owning
    workspace, callback url, subscribed event types, the enabled flag, and
    timestamps.
    """
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "url": row.url,
        "event_types": list(getattr(row, "event_types", None) or []),
        "enabled": bool(getattr(row, "enabled", False)),
        "created_at": _isoformat(getattr(row, "created_at", None)),
        "updated_at": _isoformat(getattr(row, "updated_at", None)),
    }


def _delivery_data(row: Any) -> dict[str, Any]:
    """Serialise a delivery to its public metadata envelope (no signed payload)."""
    return {
        "id": row.id,
        "subscription_id": row.subscription_id,
        "event_type": getattr(row, "event_type", "") or "",
        "event_id": getattr(row, "event_id", "") or "",
        "status": getattr(row, "status", "pending") or "pending",
        "attempts": int(getattr(row, "attempts", 0) or 0),
        "last_attempt_at": _isoformat(getattr(row, "last_attempt_at", None)),
        "response_code": getattr(row, "response_code", None),
        "created_at": _isoformat(getattr(row, "created_at", None)),
    }


# --------------------------------------------------------------------------- #
# POST /me/workspaces/{id}/webhooks  (create — one-time secret reveal)
# --------------------------------------------------------------------------- #
@router.post(
    "/me/workspaces/{workspace_id}/webhooks",
    response_model=WebhookSubscriptionCreatedResponse,
    operation_id="createWebhookSubscription",
    tags=["Webhooks"],
    summary="Create a webhook subscription (the signing secret is revealed once)",
)
def create_webhook_subscription(
    request: Request,
    body: WebhookSubscribeRequest,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Register a subscription and return the HMAC signing ``secret`` **once**.

    Gated by ``workspace.settings`` (owner/admin) — a non-member or viewer gets a
    ``403`` (real workspace) / ``404`` (unknown id). The ``url`` is SSRF-validated
    through the SAME guard the delivery primitive uses BEFORE any row is persisted
    (a loopback / private / link-local / metadata target -> ``400``); the signing
    secret is minted server-side and returned in this response only — it is stored
    only encrypted and is never returned again.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    event_types = _validate_event_types(body.event_types, request_id)

    with get_session() as session:
        user = _require_settings(session, request, workspace_id, request_id)
        with _map_service_errors(request_id):
            subscription, secret = subs_service.create(
                session,
                workspace_id,
                body.url,
                event_types,
                actor_user_id=user.id,
            )
        data = _subscription_data(subscription)
        # The ONLY place the plaintext signing secret ever leaves the server.
        data["secret"] = secret

    logger.info(
        f"created webhook subscription {data['id']} for workspace "
        f"{workspace_id} ({request_id})"
    )
    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# POST /me/webhooks  (no workspace needed — one call subscribes)
# --------------------------------------------------------------------------- #
@router.post(
    "/me/webhooks",
    response_model=WebhookSubscriptionCreatedResponse,
    operation_id="createMyWebhookSubscription",
    tags=["Webhooks"],
    summary="Subscribe without a workspace (a personal one is used or created)",
)
def create_my_webhook_subscription(request: Request, body: WebhookSubscribeRequest):
    """Create a subscription in the caller's own workspace.

    For a user who belongs to no workspace (or owns none), a ``Personal``
    workspace is created with them as owner, so any signed-in user can
    subscribe in one call. The URL is SSRF-checked before anything is created.
    The response carries ``workspace_id`` and the signing ``secret`` (once).
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)
    event_types = _validate_event_types(body.event_types, request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        with _map_service_errors(request_id):
            subscription, secret = subs_service.create_for_user(
                session, user.id, body.url, event_types
            )
        data = _subscription_data(subscription)
        data["secret"] = secret

    logger.info(f"created personal webhook subscription {data['id']} ({request_id})")
    return utils.get_response(200, data)


@router.post(
    "/me/webhooks/workspace",
    operation_id="ensureMyWebhookWorkspace",
    tags=["Webhooks"],
    summary="Return (or create) the workspace that holds your webhooks",
)
def ensure_my_webhook_workspace(request: Request):
    """Return the id of a workspace the caller owns, creating ``Personal`` if none."""
    request_id = base.get_task_id(request)
    _require_backend(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        with _map_service_errors(request_id):
            workspace_id = subs_service.ensure_personal_workspace(session, user.id)
    return utils.get_response(200, {"workspace_id": workspace_id})


# --------------------------------------------------------------------------- #
# GET /me/workspaces/{id}/webhooks  (list — secret never returned)
# --------------------------------------------------------------------------- #
@router.get(
    "/me/workspaces/{workspace_id}/webhooks",
    response_model=WebhookSubscriptionListResponse,
    operation_id="listWebhookSubscriptions",
    tags=["Webhooks"],
    summary="List a workspace's webhook subscriptions (secret never returned)",
)
def list_webhook_subscriptions(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Return the workspace's subscriptions (newest first), SECRET-FREE.

    Gated by ``workspace.settings``; tenant-scoped so a caller only ever sees their
    own workspace's subscriptions. The signing secret (plaintext or encrypted) is
    never included.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        _require_settings(session, request, workspace_id, request_id)
        rows = subs_service.list_(session, workspace_id)
        data = [_subscription_data(r) for r in rows]

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# DELETE /me/workspaces/{id}/webhooks/{sub_id}  (revoke — tenant-scoped)
# --------------------------------------------------------------------------- #
@router.delete(
    "/me/workspaces/{workspace_id}/webhooks/{subscription_id}",
    operation_id="deleteWebhookSubscription",
    tags=["Webhooks"],
    summary="Revoke a webhook subscription (tenant-scoped; audited)",
)
def delete_webhook_subscription(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
    subscription_id: str = Path(..., description="Webhook subscription ID"),
):
    """Soft-revoke one of the workspace's subscriptions. ``404`` for a foreign/missing id.

    Gated by ``workspace.settings``. Tenant-scoped in the service (``revoke`` filters
    on the workspace), so a subscription from another tenant is indistinguishable
    from a missing one (``404``). The revoke is audited.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        user = _require_settings(session, request, workspace_id, request_id)
        with _map_service_errors(request_id):
            row = subs_service.revoke(
                session, workspace_id, subscription_id, actor_user_id=user.id
            )
        if row is None:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: webhook subscription not found",
            )

    return utils.get_response(200, {"id": subscription_id, "revoked": True})


# --------------------------------------------------------------------------- #
# POST /me/workspaces/{id}/webhooks/{sub_id}/test  (send a signed test event)
# --------------------------------------------------------------------------- #
@router.post(
    "/me/workspaces/{workspace_id}/webhooks/{subscription_id}/test",
    response_model=WebhookDeliveryResponse,
    operation_id="testWebhookSubscription",
    tags=["Webhooks"],
    summary="Send a signed test event to a webhook subscription",
)
def test_webhook_subscription(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
    subscription_id: str = Path(..., description="Webhook subscription ID"),
):
    """Send a signed ``webhook.test`` event to the subscription's URL.

    Gated by ``workspace.settings``; tenant-scoped (a foreign/missing subscription
    is ``404``). The event is HMAC-signed with the subscription's secret and
    delivered via the EXISTING SSRF-guarded delivery primitive; a
    :class:`WebhookDelivery` record is returned (and appears in the deliveries view)
    reflecting the attempt outcome.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        _require_settings(session, request, workspace_id, request_id)
        with _map_service_errors(request_id):
            delivery = subs_service.send_test(
                session, workspace_id, subscription_id
            )
        if delivery is None:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: webhook subscription not found",
            )
        data = _delivery_data(delivery)

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# GET /me/workspaces/{id}/webhooks/{sub_id}/deliveries  (recent deliveries)
# --------------------------------------------------------------------------- #
@router.get(
    "/me/workspaces/{workspace_id}/webhooks/{subscription_id}/deliveries",
    response_model=WebhookDeliveryListResponse,
    operation_id="listWebhookDeliveries",
    tags=["Webhooks"],
    summary="List a subscription's recent deliveries + status (tenant-scoped)",
)
def list_webhook_deliveries(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
    subscription_id: str = Path(..., description="Webhook subscription ID"),
    limit: int = Query(
        default=_DEFAULT_DELIVERIES,
        ge=1,
        le=_MAX_DELIVERIES,
        description="Max deliveries to return (newest first).",
    ),
):
    """Return a subscription's recent deliveries (newest first) with their status.

    Gated by ``workspace.settings``; tenant-scoped in the service (ownership is
    verified before any delivery is read), so a foreign/missing subscription is a
    ``404`` and another tenant's deliveries never leak. The signed payload body is
    omitted — only delivery metadata (status/attempts/response) is returned.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        _require_settings(session, request, workspace_id, request_id)
        deliveries = subs_service.list_deliveries(
            session, workspace_id, subscription_id, limit=limit
        )
        if deliveries is None:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: webhook subscription not found",
            )
        data = [_delivery_data(d) for d in deliveries]

    return utils.get_response(200, data)
