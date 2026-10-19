"""Approvals feed: one owner-scoped list of actions waiting for a human.

* :func:`sync_user` pulls each adapter's pending rows into ``approval_items``
  (idempotent on ``UNIQUE(user_id, source, external_ref)``) and expires items
  whose source row was handled somewhere else.
* :func:`list_items` / :func:`get_item` read the feed.
* :func:`decide` applies approve/reject. It first claims the item with a
  guarded ``UPDATE ... WHERE status IN (pending, failed)`` so two concurrent
  decisions cannot both execute, then delegates to the source adapter, then
  records the outcome. Repeating the same decision returns the recorded item
  unchanged (idempotent); the opposite decision on a decided item is a 409.
* :func:`enqueue` lets producers (design, capture, catalog) push items.

Nothing here posts, sends or spends: approving delegates to the source's own
service, and rejecting a social reply draft never contacts the platform.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import func, select, update

from app.domains.approvals import adapters as _adapters
from app.domains.approvals import settings as _settings
from app.domains.approvals.adapters import ApprovalExecError, Candidate
from app.domains.approvals.models import (
    APPROVAL_SOURCES,
    APPROVAL_STATUSES,
    RISK_LEVELS,
    RISK_MEDIUM,
    SOURCE_AD_BUDGET,
    SOURCE_DESIGN_PUBLISH,
    SOURCE_PUBLISH_HOLD,
    STATUS_APPROVED,
    STATUS_EDITED,
    STATUS_EXECUTED,
    STATUS_EXPIRED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_REJECTED,
    ApprovalItem,
)

try:
    from app.models.db.base import get_session

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - reported as a 503
    get_session = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc

APPROVE = "approve"
REJECT = "reject"
DECISIONS = frozenset({APPROVE, REJECT})
#: Statuses a decision can be made from ("failed" = approved but the source failed; retryable).
DECIDABLE = frozenset({STATUS_PENDING, STATUS_FAILED})
_APPROVED_LIKE = frozenset({STATUS_APPROVED, STATUS_EXECUTED, STATUS_EDITED})
MAX_LIMIT = 100
VIA_VALUES = frozenset({"web", "api", "rally", "mobile", "slack"})
# Approving these schedules real posts, so they follow the publishing launch gate.
PUBLISHING_SOURCES = frozenset({SOURCE_PUBLISH_HOLD, SOURCE_DESIGN_PUBLISH})
PUBLISHING_CLOSED_MESSAGE = (
    "Posting is paused during the private beta, so this item cannot be approved yet. "
    "You can reject it, or leave it here until publishing opens."
)


def _publishing_open() -> bool:
    try:
        from app.core.launch.policy import publishing_enabled

        return bool(publishing_enabled())
    except Exception:  # noqa: BLE001 - a broken flag reads as closed (fail safe)
        return False


class ApprovalError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400, item: dict | None = None) -> None:
        self.status_code = status_code
        self.item = item
        super().__init__(message)


def _require_ready() -> None:
    if get_session is None:
        raise ApprovalError(f"approvals persistence unavailable: {_IMPORT_ERROR}", status_code=503)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    aware = _aware(value)
    return aware.isoformat() if aware else None


def _web_base() -> str:
    try:
        from app.domains.ads.config import web_url

        return web_url()
    except Exception:  # noqa: BLE001 - a missing config never breaks the feed
        return "https://menivor.com"


def item_view(row: ApprovalItem) -> dict:
    """Wire shape (the Rally approvals hub parses this contract)."""
    payload = dict(row.payload or {})
    open_path = str(payload.get("open_path") or "/approvals")
    return {
        "id": row.id,
        "source": row.source,
        "external_ref": row.external_ref,
        "title": row.title or "",
        "summary": row.summary or "",
        "risk": row.risk or RISK_MEDIUM,
        "payload": payload,
        "edited_payload": dict(row.edited_payload) if row.edited_payload else None,
        "status": row.status,
        "decided_by": row.decided_by,
        "decided_via": row.decided_via or "",
        "decided_at": _iso(row.decided_at),
        "decision_note": row.decision_note or "",
        "result": dict(row.result or {}),
        "error": row.error or "",
        "expires_at": _iso(row.expires_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "open_url": f"{_web_base()}{open_path}" if open_path.startswith("/") else None,
        "can_decide": row.status in DECIDABLE,
    }


# --------------------------------------------------------------------------- #
# Enqueue + sync
# --------------------------------------------------------------------------- #
def _upsert(session: Any, user_id: str, source: str, cand: Candidate, *, workspace_id: str | None = None,
            reopen_decided: bool = False) -> ApprovalItem:
    row = session.execute(
        select(ApprovalItem).where(ApprovalItem.user_id == user_id, ApprovalItem.source == source,
                                   ApprovalItem.external_ref == cand.external_ref)
    ).scalar_one_or_none()
    if row is None:
        row = ApprovalItem(
            user_id=user_id, workspace_id=workspace_id, source=source, external_ref=cand.external_ref,
            title=cand.title[:300], summary=cand.summary, risk=cand.risk if cand.risk in RISK_LEVELS else RISK_MEDIUM,
            payload=dict(cand.payload), status=STATUS_PENDING, expires_at=cand.expires_at, result={},
        )
        session.add(row)
        session.flush()
        return row
    if row.status == STATUS_PENDING:
        # Refresh what the reviewer sees (e.g. a draft the autopilot re-wrote).
        row.title = cand.title[:300]
        row.summary = cand.summary
        row.payload = dict(cand.payload)
        row.risk = cand.risk if cand.risk in RISK_LEVELS else row.risk
    elif row.status in (STATUS_EXPIRED, STATUS_EXECUTED) or (
        reopen_decided and row.status in (STATUS_REJECTED, STATUS_FAILED)
    ):
        # The source row is waiting again (e.g. a post was held a second time, or
        # the owner explicitly re-scheduled a design that was rejected before).
        row.status = STATUS_PENDING
        row.title = cand.title[:300]
        row.summary = cand.summary
        row.payload = dict(cand.payload)
        row.decided_at = None
        row.decided_by = None
        row.decided_via = ""
        row.decision_note = ""
        row.edited_payload = None
        row.error = ""
        row.result = {}
    return row


def enqueue(user_id: str, source: str, external_ref: str, *, title: str, summary: str = "",
            risk: str = RISK_MEDIUM, payload: dict | None = None, workspace_id: str | None = None,
            expires_at: datetime | None = None, session: Any = None) -> dict:
    """Push one item (idempotent per source + external_ref). Nothing is executed."""
    if source not in APPROVAL_SOURCES:
        raise ApprovalError(f"unknown approval source: {source}")
    ref = str(external_ref or "").strip()
    if not ref or len(ref) > 160:
        raise ApprovalError("external_ref must be 1-160 characters")
    cand = Candidate(external_ref=ref, title=title or source, summary=summary, risk=risk,
                     payload=dict(payload or {}), expires_at=expires_at)
    if session is not None:
        return item_view(_upsert(session, user_id, source, cand, workspace_id=workspace_id, reopen_decided=True))
    _require_ready()
    with get_session() as own:  # type: ignore[misc]
        return item_view(_upsert(own, user_id, source, cand, workspace_id=workspace_id, reopen_decided=True))


def _link_budget(session: Any, item: ApprovalItem) -> None:
    from app.domains.ads.allocation_models import AdAllocationProposal

    proposal = session.get(AdAllocationProposal, item.external_ref)
    if proposal is not None and proposal.approval_item_id is None:
        proposal.approval_item_id = item.id


def sync_user(user_id: str, *, now: datetime | None = None) -> dict[str, int]:
    """Mirror every adapter's pending rows into the feed. One broken source never breaks the rest."""
    _require_ready()
    moment = now or _utcnow()
    counts: dict[str, int] = {}
    opted_in = _settings.enabled_auto_sources(user_id)
    for source, adapter in _adapters.ADAPTERS.items():
        if source in _settings.AUTO_SOURCES and source not in opted_in:
            _retire_opted_out(user_id, source, moment, _settings.TURNED_OFF_NOTE)
            continue
        try:
            with get_session() as session:  # type: ignore[misc]
                candidates, complete = adapter.scan(session, user_id)
                seen = set()
                for cand in candidates:
                    item = _upsert(session, user_id, source, cand)
                    seen.add(cand.external_ref)
                    if source == SOURCE_AD_BUDGET:
                        _link_budget(session, item)
                if complete:
                    stale = session.execute(
                        select(ApprovalItem).where(ApprovalItem.user_id == user_id, ApprovalItem.source == source,
                                                   ApprovalItem.status == STATUS_PENDING)
                    ).scalars().all()
                    for row in stale:
                        if row.external_ref not in seen:
                            row.status = STATUS_EXPIRED
                            row.decision_note = "Handled outside the approvals feed."
                            row.decided_at = moment
                counts[source] = len(candidates)
        except Exception as exc:  # noqa: BLE001 - a missing table or a bad row in one source
            logger.warning(f"approvals sync: source {source} failed for user {user_id}: {exc}")
            counts[source] = -1
    _expire_overdue(user_id, moment)
    return counts


def _retire_opted_out(user_id: str, source: str, moment: datetime, note: str) -> None:
    """Expire leftover suggestions from an opt-in source that is off (a later opt-in reopens them)."""
    try:
        with get_session() as session:  # type: ignore[misc]
            rows = session.execute(
                select(ApprovalItem).where(ApprovalItem.user_id == user_id, ApprovalItem.source == source,
                                           ApprovalItem.status == STATUS_PENDING)
            ).scalars().all()
            for row in rows:
                row.status = STATUS_EXPIRED
                row.decision_note = note
                row.decided_at = moment
    except Exception as exc:  # noqa: BLE001 - never break the feed over housekeeping
        logger.warning(f"approvals sync: could not retire {source} items for user {user_id}: {exc}")


def _expire_overdue(user_id: str, moment: datetime) -> None:
    with get_session() as session:  # type: ignore[misc]
        rows = session.execute(
            select(ApprovalItem).where(ApprovalItem.user_id == user_id, ApprovalItem.status == STATUS_PENDING,
                                       ApprovalItem.expires_at.is_not(None))
        ).scalars().all()
        for row in rows:
            if _aware(row.expires_at) and _aware(row.expires_at) <= moment:
                row.status = STATUS_EXPIRED
                row.decision_note = "Expired before a decision."
                row.decided_at = moment


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #
def list_items(user_id: str, *, status: str = STATUS_PENDING, source: str = "", limit: int = 50,
               offset: int = 0, sync: bool = True) -> dict:
    _require_ready()
    if status and status not in APPROVAL_STATUSES and status != "all":
        raise ApprovalError(f"status must be one of {sorted(APPROVAL_STATUSES)} or 'all'")
    if source and source not in APPROVAL_SOURCES:
        raise ApprovalError(f"source must be one of {sorted(APPROVAL_SOURCES)}")
    sync_counts = sync_user(user_id) if sync else {}
    limit = max(1, min(int(limit or 50), MAX_LIMIT))
    offset = max(0, int(offset or 0))
    conditions = [ApprovalItem.user_id == user_id]
    if status and status != "all":
        conditions.append(ApprovalItem.status == status)
    if source:
        conditions.append(ApprovalItem.source == source)
    with get_session() as session:  # type: ignore[misc]
        total = int(session.execute(select(func.count()).select_from(ApprovalItem).where(*conditions)).scalar() or 0)
        rows = session.execute(
            select(ApprovalItem).where(*conditions)
            .order_by(ApprovalItem.created_at.desc(), ApprovalItem.id.desc()).limit(limit).offset(offset)
        ).scalars().all()
        by_source = dict(session.execute(
            select(ApprovalItem.source, func.count()).where(ApprovalItem.user_id == user_id,
                                                            ApprovalItem.status == STATUS_PENDING)
            .group_by(ApprovalItem.source)
        ).all())
        items = [item_view(r) for r in rows]
    unavailable = sorted(s for s, n in sync_counts.items() if n < 0)
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "pending_count": int(sum(by_source.values())),
        "pending_by_source": {k: int(v) for k, v in by_source.items()},
        "unavailable_sources": unavailable,
    }


def get_item(user_id: str, item_id: str) -> dict:
    _require_ready()
    with get_session() as session:  # type: ignore[misc]
        row = session.get(ApprovalItem, item_id)
        if row is None or row.user_id != user_id:
            raise ApprovalError("approval item not found", status_code=404)
        return item_view(row)


def pending_count(user_id: str) -> int:
    _require_ready()
    with get_session() as session:  # type: ignore[misc]
        return int(session.execute(
            select(func.count()).select_from(ApprovalItem)
            .where(ApprovalItem.user_id == user_id, ApprovalItem.status == STATUS_PENDING)
        ).scalar() or 0)


# --------------------------------------------------------------------------- #
# Decide
# --------------------------------------------------------------------------- #
def _same_decision(status: str, decision: str) -> bool:
    return (decision == APPROVE and status in _APPROVED_LIKE) or (decision == REJECT and status == STATUS_REJECTED)


def _clean_edits(edits: dict | None, payload: dict) -> dict:
    """Only fields the source declared editable, as short strings."""
    allowed = set(payload.get("editable_fields") or [])
    out: dict = {}
    for key, value in (edits or {}).items():
        if key in allowed and isinstance(value, str):
            out[key] = value.strip()[:2000]
    return out


def decide(user_id: str, item_id: str, decision: str, *, actor: str = "", via: str = "api",
           note: str = "", edits: dict | None = None, now: datetime | None = None) -> dict:
    """Approve or reject one item. Returns ``{"item", "idempotent"}``."""
    _require_ready()
    if decision not in DECISIONS:
        raise ApprovalError("decision must be approve or reject")
    moment = now or _utcnow()
    via = via if via in VIA_VALUES else "api"
    note = (note or "").strip()[:1000]

    # 1) Claim (guarded transition) or answer idempotently.
    with get_session() as session:  # type: ignore[misc]
        row = session.get(ApprovalItem, item_id)
        if row is None or row.user_id != user_id:
            raise ApprovalError("approval item not found", status_code=404)
        if row.status not in DECIDABLE:
            if _same_decision(row.status, decision):
                return {"item": item_view(row), "idempotent": True}
            raise ApprovalError(f"this item was already decided ({row.status})", status_code=409, item=item_view(row))
        if decision == APPROVE and row.source in PUBLISHING_SOURCES and not _publishing_open():
            raise ApprovalError(PUBLISHING_CLOSED_MESSAGE, status_code=403, item=item_view(row))
        clean = _clean_edits(edits, dict(row.payload or {})) if decision == APPROVE else {}
        claimed_status = (STATUS_EDITED if clean else STATUS_APPROVED) if decision == APPROVE else STATUS_REJECTED
        claimed = session.execute(
            update(ApprovalItem)
            .where(ApprovalItem.id == item_id, ApprovalItem.status.in_(tuple(DECIDABLE)))
            .values(status=claimed_status, decided_by=(actor or user_id)[:64], decided_via=via,
                    decided_at=moment, decision_note=note, edited_payload=clean or None, error="")
            .execution_options(synchronize_session=False)
        ).rowcount
        source, ref = row.source, row.external_ref
    if not claimed:
        # Lost a race with a concurrent decision: report whatever won.
        current = get_item(user_id, item_id)
        if _same_decision(current["status"], decision):
            return {"item": current, "idempotent": True}
        raise ApprovalError(f"this item was already decided ({current['status']})", status_code=409, item=current)

    # 2) Delegate to the source service.
    adapter = _adapters.ADAPTERS.get(source)
    final_status = claimed_status if (decision == REJECT or adapter is None) else STATUS_EXECUTED
    result: dict = {"action": "recorded"} if adapter is None else {}
    error = ""
    failure: ApprovalExecError | None = None
    if adapter is not None:
        try:
            result = adapter.approve(user_id, ref, clean) if decision == APPROVE else adapter.reject(user_id, ref)
        except ApprovalExecError as exc:
            failure = exc
        except Exception as exc:  # noqa: BLE001 - never leave an item stuck in "approved"
            logger.error(f"approvals: {source} {decision} failed for {item_id}: {exc}")
            failure = ApprovalExecError("the source service failed; try again", status_code=502)
    if failure is not None:
        error = str(failure)[:1000]
        final_status = STATUS_EXPIRED if failure.gone else STATUS_FAILED if decision == APPROVE else STATUS_PENDING

    # 3) Record the outcome.
    with get_session() as session:  # type: ignore[misc]
        row = session.get(ApprovalItem, item_id)
        row.status = final_status
        row.result = dict(result or {})
        row.error = error
        if final_status == STATUS_PENDING:
            row.decided_at = None
            row.decided_by = None
            row.decided_via = ""
        session.flush()
        view = item_view(row)
    if failure is not None:
        raise ApprovalError(str(failure), status_code=failure.status_code, item=view)
    return {"item": view, "idempotent": False}


__all__ = [
    "APPROVE",
    "ApprovalError",
    "DECISIONS",
    "REJECT",
    "decide",
    "enqueue",
    "get_item",
    "item_view",
    "list_items",
    "pending_count",
    "sync_user",
]
