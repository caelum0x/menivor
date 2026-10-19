"""Developer portal v1 API controller (Enterprise API Platform, Epic 4).

Mounted under ``/api/v1``. A single READ-only, strictly CALLER-SCOPED endpoint
that summarises everything a customer needs to integrate against the platform:

* ``GET /me/developer`` — the caller's API-key footprint (counts + current-month
  request usage — reusing the Epic-3 per-key usage counter), their webhook
  subscription footprint (aggregated across the workspaces they belong to), the
  number of workspaces they belong to, and static integration metadata (API base
  URL, OpenAPI/docs links, API version, supported webhook event types).

Design notes
------------
* **Read + link only.** Key mint/revoke stays in
  :mod:`app.controllers.v1.api_keys`; subscription management in
  :mod:`app.controllers.v1.webhooks_admin`. This endpoint only reports + links.
* **Auth reused.** The canonical ``_resolve_user`` resolver from
  :mod:`app.controllers.v1.jobs` (Clerk JWT / ``x-api-key`` / per-user key) gates
  the route; a missing DB layer degrades to a clean ``503``.
* **Caller-scoped, secret-free.** Every count is derived from rows owned by the
  resolved caller (their keys, their workspaces' subscriptions). NO raw key, hash,
  or signing secret is ever exposed.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Request
from loguru import logger

from app.config import config
from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.models.schema import WEBHOOK_EVENT_TYPES, DeveloperPortalResponse
from app.utils import utils

# Guarded imports of the persistence layer + the per-key usage helpers. A partial
# environment degrades to a 503 rather than crashing at import time.
try:  # pragma: no cover - exercised implicitly by the API tests
    from app.models.db.repositories import (
        ApiKeyUsageRepository,
        UserApiKeyRepository,
        WebhookSubscriptionRepository,
        WorkspaceRepository,
    )

    _DEV_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # noqa: BLE001 - import-safe: never crash the module
    ApiKeyUsageRepository = None  # type: ignore[assignment,misc]
    UserApiKeyRepository = None  # type: ignore[assignment,misc]
    WebhookSubscriptionRepository = None  # type: ignore[assignment,misc]
    WorkspaceRepository = None  # type: ignore[assignment,misc]
    _DEV_IMPORT_ERROR = exc

router = new_router()

#: The mounted OpenAPI schema + interactive docs paths (FastAPI defaults).
_OPENAPI_PATH: str = "openapi.json"
_DOCS_PATH: str = "docs"
#: The API prefix every v1 route is mounted under (mirrors ``new_router``).
_API_PREFIX: str = "api/v1"


def _require_backend(request_id: str) -> None:
    """Raise 503 when the DB layer or the developer-portal repositories are absent."""
    _require_db(request_id)
    if (
        UserApiKeyRepository is None
        or WorkspaceRepository is None
        or WebhookSubscriptionRepository is None
        or _DEV_IMPORT_ERROR is not None
    ):
        logger.error(
            f"developer-portal backend unavailable, request_id: {request_id}, "
            f"error: {_DEV_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: developer portal is not available",
        )


def _current_period_ym() -> str:
    """Return the current ``'YYYY-MM'`` month (delegates to the quota service).

    Import-safe: falls back to the UTC month directly if the quota service is
    unavailable, so the portal never 500s on a missing optional module.
    """
    try:
        from app.services import apikey_quota

        return apikey_quota.current_period_ym()
    except Exception as exc:  # noqa: BLE001 - degrade to a direct UTC month
        logger.debug(f"apikey_quota unavailable for period token: {exc}")
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).strftime("%Y-%m")


def _month_usage(session: Any, key_id: str, period_ym: str) -> int:
    """Best-effort current-month request count for a key (0 on any failure)."""
    if ApiKeyUsageRepository is None:
        return 0
    try:
        return int(ApiKeyUsageRepository(session).get_month(key_id, period_ym))
    except Exception as exc:  # noqa: BLE001 - usage telemetry is best-effort
        logger.debug(f"failed to read month usage for api key {key_id}: {exc}")
        return 0


def _api_keys_summary(session: Any, user_id: str, period_ym: str) -> dict[str, Any]:
    """Summarise the caller's API keys: total/active counts + month request usage.

    SECRET-FREE — never touches the raw key or hash, only counts and the aggregate
    request usage across the caller's keys for the current calendar month.
    """
    rows = UserApiKeyRepository(session).list_for_user(user_id)
    active = [r for r in rows if not bool(getattr(r, "revoked", False))]
    requests_this_month = sum(_month_usage(session, r.id, period_ym) for r in rows)
    return {
        "total": len(rows),
        "active": len(active),
        "period_ym": period_ym,
        "requests_this_month": int(requests_this_month),
    }


def _webhooks_summary(session: Any, user_id: str) -> dict[str, Any]:
    """Aggregate the caller's webhook subscriptions across their workspaces.

    Tenant-scoped per workspace: only subscriptions of workspaces the caller
    belongs to are counted. ``active`` counts only enabled subscriptions. No secret
    is exposed.
    """
    workspaces = WorkspaceRepository(session).list_for_user(user_id)
    sub_repo = WebhookSubscriptionRepository(session)
    total = 0
    active = 0
    for ws in workspaces:
        subs = sub_repo.list_for_workspace(ws.id, limit=_MAX_SUBS_PER_WS)
        total += len(subs)
        active += sum(1 for s in subs if bool(getattr(s, "enabled", False)))
    return {
        "total": total,
        "active": active,
        "event_types": list(WEBHOOK_EVENT_TYPES),
    }


#: Upper bound on subscriptions counted per workspace (a very high ceiling; keeps
#: the aggregate a bounded scan even for a pathological workspace).
_MAX_SUBS_PER_WS: int = 1000


def _integration_metadata(request: Request) -> dict[str, Any]:
    """Derive the static integration links from the incoming request + config.

    ``request.base_url`` is the mounted origin (scheme + host); the API base is that
    origin plus the ``api/v1`` prefix, and the OpenAPI/docs links are the FastAPI
    defaults. Best-effort: any failure degrades to empty strings rather than 500.
    """
    try:
        origin = str(request.base_url).rstrip("/")
    except Exception as exc:  # noqa: BLE001 - defensive: never 500 on URL parsing
        logger.debug(f"unable to derive base_url for developer portal: {exc}")
        origin = ""
    version = ""
    try:
        version = str(getattr(config, "project_version", "") or "")
    except Exception:  # noqa: BLE001 - config is always bound in practice
        version = ""
    return {
        "api_base_url": f"{origin}/{_API_PREFIX}" if origin else f"/{_API_PREFIX}",
        "openapi_url": f"{origin}/{_OPENAPI_PATH}" if origin else f"/{_OPENAPI_PATH}",
        "docs_url": f"{origin}/{_DOCS_PATH}" if origin else f"/{_DOCS_PATH}",
        "api_version": version,
    }


@router.get(
    "/me/developer",
    response_model=DeveloperPortalResponse,
    operation_id="getDeveloperPortal",
    tags=["Developer"],
    summary="The caller's developer-portal summary (keys, usage, webhooks, links)",
)
def get_developer_portal(request: Request):
    """Return the caller-scoped developer portal summary (READ-only, secret-free).

    Reports the caller's API-key footprint (counts + current-month request usage,
    reusing the per-key usage counter), their webhook-subscription footprint across
    the workspaces they belong to, the number of workspaces they belong to, and the
    static integration links (API base URL, OpenAPI/docs, version, supported webhook
    events). Never mints/revokes anything and never exposes a secret.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    period_ym = _current_period_ym()
    metadata = _integration_metadata(request)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        api_keys = _api_keys_summary(session, user.id, period_ym)
        webhooks = _webhooks_summary(session, user.id)
        workspaces = WorkspaceRepository(session).list_for_user(user.id)
        data = {
            "api_keys": api_keys,
            "webhooks": webhooks,
            "workspaces": len(workspaces),
            "webhook_event_types": list(WEBHOOK_EVENT_TYPES),
            **metadata,
        }

    return utils.get_response(200, data)
