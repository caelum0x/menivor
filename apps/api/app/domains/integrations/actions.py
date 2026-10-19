"""Ad delivery behind an explicit approval (approval source ``ad_action``).

* :func:`propose` records what would change (pause/resume one ad or ad group) as
  an approval item. Nothing is sent to the ad platform.
* :func:`approve` is the approvals adapter: it runs only after
  ``approvals.service.decide(..., "approve")`` claimed the item, re-checks that
  the proposer still manages the workspace and the account is still connected,
  then makes exactly one platform call. :func:`reject` never contacts a platform.
* :func:`decide` is the entry point for the web page, the Brand Agent and Slack:
  it checks the approver's own scope (owner/admin of the same workspace) and then
  delegates to the shared approvals API, which is idempotent per item.

Module-level imports must not import ``app.domains.approvals.service`` or
``adapters`` (the approvals package registers this module while it loads).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.domains.approvals.models import RISK_HIGH, RISK_MEDIUM, SOURCE_AD_ACTION, ApprovalItem
from app.domains.integrations import onboarding
from app.domains.integrations.connectors import get_connector
from app.domains.integrations.connectors.base import ACTIONS, AccountInfo, ConnectorError, RequestsTransport
from app.domains.integrations.errors import IntegrationError
from app.domains.integrations.models import IntegrationAdAccount, IntegrationConnection
from app.domains.integrations.scope import Scope, resolve

try:
    from app.models.db.base import get_session
except Exception:  # pragma: no cover - reported by the approvals service
    get_session = None  # type: ignore[assignment]

_TRANSPORT: Any = RequestsTransport()


def set_transport(transport: Any) -> None:
    """Swap the network seam (tests, or a shared instrumented client)."""
    global _TRANSPORT
    _TRANSPORT = transport


def _verb(action: str) -> str:
    return "Pause" if action == "pause" else "Resume"


def propose(session: Any, scope: Scope, *, ad_account_id: str, action: str, entity_id: str, entity_name: str = "",
            reason: str = "", evidence: dict | None = None) -> dict:
    """Queue one pause/resume for approval. Returns the approval item view."""
    from app.domains.approvals import service as approvals
    from app.domains.integrations.service import get_account

    scope.require_manage()
    if action not in ACTIONS:
        raise IntegrationError(400, "Only pause and resume can be proposed.")
    account = get_account(session, scope, ad_account_id)
    connector = get_connector(account.provider)
    if not connector.supports_delivery:
        raise IntegrationError(400, f"{connector.label} changes are not available from Menivor yet.")
    target = str(entity_id or "").strip()[:128]
    if not target:
        raise IntegrationError(400, "Choose which ad to change.")
    name = (entity_name or target)[:200]
    payload = {
        "owner_scope": scope.owner_scope, "workspace_id": scope.workspace_id, "ad_account_id": account.id,
        "ad_account_name": account.name, "provider": account.provider, "action": action, "entity_id": target,
        "entity_level": connector.delivery_level, "entity_name": name, "reason": (reason or "")[:1000],
        "evidence": dict(evidence or {}), "open_path": "/settings/integrations",
    }
    try:
        return approvals.enqueue(
            scope.user_id, SOURCE_AD_ACTION, f"{account.id}:{action}:{target}"[:160],
            title=f"{_verb(action)} \"{name}\" on {connector.label}", summary=(reason or "")[:2000],
            risk=RISK_HIGH if action == "resume" else RISK_MEDIUM, payload=payload,
            workspace_id=scope.workspace_id, session=session)
    except approvals.ApprovalError as exc:
        raise IntegrationError(exc.status_code, str(exc)) from exc


# --------------------------------------------------------------------------- #
# Approvals adapter (called only by approvals.service.decide)
# --------------------------------------------------------------------------- #
def scan(_session: Any, _user_id: str) -> tuple[list, bool]:
    """Proposals are pushed with :func:`propose`; never expire them on sync."""
    return [], False


def _exec_error(message: str, *, status_code: int = 400, gone: bool = False) -> Exception:
    from app.domains.approvals.adapters import ApprovalExecError

    return ApprovalExecError(message, status_code=status_code, gone=gone)


def approve(user_id: str, ref: str, _edits: dict) -> dict:
    from app.domains.integrations.service import valid_token

    with get_session() as session:  # type: ignore[misc]
        item = session.execute(select(ApprovalItem).where(
            ApprovalItem.user_id == user_id, ApprovalItem.source == SOURCE_AD_ACTION,
            ApprovalItem.external_ref == ref)).scalar_one_or_none()
        if item is None:
            raise _exec_error("this proposal no longer exists", status_code=404, gone=True)
        payload = dict(item.payload or {})
        try:
            scope = resolve(session, user_id, workspace_id=payload.get("workspace_id"))
            scope.require_manage()
        except IntegrationError as exc:
            raise _exec_error(exc.message, status_code=403) from exc
        account = session.get(IntegrationAdAccount, payload.get("ad_account_id") or "")
        if account is None or account.owner_scope != scope.owner_scope:
            raise _exec_error("the ad account was disconnected", status_code=409, gone=True)
        conn = session.get(IntegrationConnection, account.connection_id)
        try:
            token = valid_token(session, conn, transport=_TRANSPORT)
            info = AccountInfo(external_id=account.external_id, name=account.name, currency=account.currency,
                               timezone=account.timezone)
            result = get_connector(account.provider).execute(
                _TRANSPORT, token, info, str(payload.get("action")), str(payload.get("entity_id")))
        except IntegrationError as exc:
            raise _exec_error(exc.message, status_code=exc.status_code) from exc
        except ConnectorError as exc:
            raise _exec_error(exc.message, status_code=502) from exc
        granted = onboarding.grant_once(session, scope, "first_approved_action")
    return {**result, "action": payload.get("action"), "credits_granted": granted}


def reject(_user_id: str, _ref: str) -> dict:
    return {"action": "rejected"}


# --------------------------------------------------------------------------- #
# Decide (web, Brand Agent, Slack)
# --------------------------------------------------------------------------- #
def decide(scope: Scope, item_id: str, decision: str, *, via: str = "web", note: str = "") -> dict:
    """Approve or reject an ``ad_action`` item as ``scope`` (owner/admin of the item's workspace)."""
    from app.domains.approvals import service as approvals

    with get_session() as session:  # type: ignore[misc]
        item = session.get(ApprovalItem, item_id)
        if item is None or item.source != SOURCE_AD_ACTION or \
                (item.payload or {}).get("owner_scope") != scope.owner_scope:
            raise IntegrationError(404, "Proposal not found.")
        owner = item.user_id
        # Re-read the approver's role now (the caller's Scope may be from an earlier session).
        try:
            current = resolve(session, scope.user_id, workspace_id=scope.workspace_id)
        except IntegrationError as exc:
            raise IntegrationError(403, exc.message) from exc
    current.require_manage()
    try:
        return approvals.decide(owner, item_id, decision, actor=scope.user_id, via=via, note=note)
    except approvals.ApprovalError as exc:
        raise IntegrationError(exc.status_code, str(exc)) from exc


def list_proposals(session: Any, scope: Scope, *, status: str = "pending", limit: int = 50) -> list[dict]:
    from app.domains.approvals.service import item_view

    stmt = select(ApprovalItem).where(ApprovalItem.source == SOURCE_AD_ACTION)
    if scope.workspace_id:
        stmt = stmt.where(ApprovalItem.workspace_id == scope.workspace_id)
    else:
        stmt = stmt.where(ApprovalItem.user_id == scope.user_id, ApprovalItem.workspace_id.is_(None))
    if status:
        stmt = stmt.where(ApprovalItem.status == status)
    rows = session.execute(stmt.order_by(ApprovalItem.created_at.desc()).limit(max(1, min(limit, 100)))).scalars()
    return [item_view(r) for r in rows if (r.payload or {}).get("owner_scope") == scope.owner_scope]


__all__ = ["approve", "decide", "list_proposals", "propose", "reject", "scan", "set_transport"]
