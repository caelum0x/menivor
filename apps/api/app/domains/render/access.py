"""Authorization for spending a workspace's shared wallet on GPU renders.

The render (``POST /render/jobs``) and film shot-render routes accept an optional
``workspace_id``; when present the wallet hold is taken against that team's
shared pool. Membership is the spend gate (every member may spend, mirroring the
reels path's ``_resolve_workspace_pool``), so this helper MUST run before any
``WalletServiceGateway`` is built with a caller-supplied workspace id.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.models.exception import HttpException


def resolve_spend_workspace(
    session: Any, user_id: str, workspace_id: str | None, request_id: str
) -> str | None:
    """Return the validated workspace id, ``None`` for the personal wallet.

    * blank / missing id -> ``None`` (personal wallet);
    * workspaces layer unavailable -> ``503``;
    * caller not a member (or unknown workspace, which has no membership) ->
      ``403`` with no existence leak.
    """
    normalized = str(workspace_id or "").strip()
    if not normalized:
        return None
    try:
        from app.services import workspaces as ws_service
    except Exception as exc:  # pragma: no cover - import guard
        logger.error(f"workspaces service unavailable, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id, status_code=503,
            message=f"{request_id}: workspaces service is not available",
        ) from exc
    if ws_service.get_membership(session, normalized, user_id) is None:
        raise HttpException(
            task_id=request_id, status_code=403,
            message=f"{request_id}: not a member of this workspace",
        )
    return normalized
