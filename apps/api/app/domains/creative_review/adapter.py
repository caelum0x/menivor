"""Approvals-feed adapter for source ``creative_review``.

``scan`` turns the user's generated creatives (Brand Agent library images and
videos) that have no decision yet into approval candidates. ``approve`` /
``reject`` only record the decision on :class:`CreativeReview`; nothing is
posted or spent here (regenerating is a separate, priced Brand Agent action).

Module-level imports must not import ``app.domains.approvals.service`` or
``adapters`` (the approvals package registers this module while it loads).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.domains.brand_agent.models import AgentLibraryItem
from app.domains.creative_review.models import (
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REGENERATED,
    STATUS_REJECTED,
    CreativeReview,
)

try:
    from app.models.db.base import get_session
except Exception:  # pragma: no cover - reported by the approvals service
    get_session = None  # type: ignore[assignment]

REVIEW_KINDS = ("image", "video")
SCAN_LIMIT = 200
OPEN_PATH = "/review"


def _decided_ids(session: Any, user_id: str) -> set[str]:
    rows = session.execute(select(CreativeReview.library_item_id).where(
        CreativeReview.user_id == user_id, CreativeReview.status != STATUS_PENDING)).scalars().all()
    return set(rows)


def payload_for(row: AgentLibraryItem) -> dict[str, Any]:
    from app.domains.brand_agent import gate

    estimate = gate.CREDIT_ESTIMATES[gate.KIND_VIDEO if row.kind == "video" else gate.KIND_IMAGE]
    return {"library_item_id": row.id, "space_id": row.space_id, "kind": row.kind, "media_url": row.url,
            "ref": row.ref, "action_id": row.action_id, "regenerate_credits": estimate, "open_path": OPEN_PATH}


def scan(session: Any, user_id: str) -> tuple[list, bool]:
    from app.domains.approvals.adapters import Candidate
    from app.domains.approvals.models import RISK_LOW

    decided = _decided_ids(session, user_id)
    rows = session.execute(
        select(AgentLibraryItem).where(AgentLibraryItem.user_id == user_id,
                                       AgentLibraryItem.kind.in_(REVIEW_KINDS))
        .order_by(AgentLibraryItem.created_at.desc(), AgentLibraryItem.id).limit(SCAN_LIMIT + 1)
    ).scalars().all()
    complete = len(rows) <= SCAN_LIMIT
    out = []
    for row in rows[:SCAN_LIMIT]:
        if row.id in decided:
            continue
        noun = "video" if row.kind == "video" else "image"
        out.append(Candidate(external_ref=row.id, title=row.title or f"New {noun}",
                             summary=f"Review this {noun} before it is used.", risk=RISK_LOW,
                             payload=payload_for(row)))
    # Decided items leave the scan; a complete scan would expire them, which is right (handled here).
    return out, complete


def _record(user_id: str, ref: str, status: str) -> dict:
    from app.domains.approvals.adapters import ApprovalExecError

    with get_session() as session:  # type: ignore[misc]
        item = session.get(AgentLibraryItem, ref)
        if item is None or item.user_id != user_id:
            raise ApprovalExecError("this creative no longer exists", status_code=404, gone=True)
        row = session.execute(select(CreativeReview).where(CreativeReview.library_item_id == ref)).scalar_one_or_none()
        if row is None:
            row = CreativeReview(user_id=user_id, library_item_id=ref, space_id=item.space_id)
            session.add(row)
        if not (status == STATUS_REJECTED and row.status == STATUS_REGENERATED):
            row.status = status
        row.decided_at = datetime.now(timezone.utc)
        session.flush()
        return {"action": f"creative_{status}", "library_item_id": ref, "reason": row.reason}


def approve(user_id: str, ref: str, _edits: dict) -> dict:
    return _record(user_id, ref, STATUS_APPROVED)


def reject(user_id: str, ref: str) -> dict:
    return _record(user_id, ref, STATUS_REJECTED)


__all__ = ["OPEN_PATH", "REVIEW_KINDS", "approve", "payload_for", "reject", "scan"]
