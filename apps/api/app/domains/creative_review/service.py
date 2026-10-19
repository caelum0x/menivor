"""Swipe-to-approve review queue over the approvals feed (source ``creative_review``).

* :func:`queue` - pending creatives (newest first), the reason chips and counts.
* :func:`decide` - approve / reject / regenerate one creative with a reason chip.
  Approve and reject go through :func:`app.domains.approvals.service.decide`
  (guarded claim, idempotent). Regenerate rejects the creative and creates a
  Brand Agent gate action that remakes it with the reason as the change request;
  with ``confirm_spend`` (the user pressed the button that shows the credit price)
  that action is approved in the same step, otherwise it waits in the Agent queue.
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy import func, select

from app.domains.approvals.models import SOURCE_CREATIVE_REVIEW
from app.domains.creative_review import reasons
from app.domains.creative_review.models import STATUS_REGENERATED, CreativeReview

try:
    from app.models.db.base import get_session
except Exception:  # pragma: no cover
    get_session = None  # type: ignore[assignment]

DECISIONS = ("approve", "reject", "regenerate")
MAX_NOTE = 500


class ReviewError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _approvals():
    from app.domains.approvals import service as approvals

    return approvals


def queue(user_id: str, *, space_id: str | None = None, limit: int = 30) -> dict[str, Any]:
    approvals = _approvals()
    listing = approvals.list_items(user_id, status="pending", source=SOURCE_CREATIVE_REVIEW, limit=limit)
    items = [i for i in listing["items"] if not space_id or i["payload"].get("space_id") == space_id]
    return {"items": items, "pending": listing["total"], "reasons": reasons.catalog(), "stats": stats(user_id)}


def stats(user_id: str) -> dict[str, Any]:
    with get_session() as session:  # type: ignore[misc]
        by_status = dict(session.execute(
            select(CreativeReview.status, func.count()).where(CreativeReview.user_id == user_id)
            .group_by(CreativeReview.status)).all())
        top = session.execute(
            select(CreativeReview.reason, func.count()).where(CreativeReview.user_id == user_id,
                                                              CreativeReview.reason != "")
            .group_by(CreativeReview.reason).order_by(func.count().desc()).limit(3)).all()
    return {"by_status": {k: int(v) for k, v in by_status.items()},
            "top_reasons": [{"id": r, "label": reasons.label(r), "count": int(n)} for r, n in top]}


def _item(user_id: str, item_id: str) -> dict[str, Any]:
    approvals = _approvals()
    try:
        item = approvals.get_item(user_id, item_id)
    except approvals.ApprovalError as exc:
        raise ReviewError(str(exc), exc.status_code) from exc
    if item["source"] != SOURCE_CREATIVE_REVIEW:
        raise ReviewError("this item is not a creative", 404)
    return item


def _remember(user_id: str, item: dict[str, Any], reason: str, note: str) -> CreativeReview:
    ref = item["external_ref"]
    with get_session() as session:  # type: ignore[misc]
        row = session.execute(select(CreativeReview).where(CreativeReview.user_id == user_id,
                                                           CreativeReview.library_item_id == ref)).scalar_one_or_none()
        if row is None:
            row = CreativeReview(user_id=user_id, library_item_id=ref,
                                 space_id=str(item["payload"].get("space_id") or ""))
            session.add(row)
        row.reason, row.note = reason, note
        session.flush()
        return row


def _review_view(user_id: str, ref: str) -> dict[str, Any] | None:
    with get_session() as session:  # type: ignore[misc]
        row = session.execute(select(CreativeReview).where(CreativeReview.user_id == user_id,
                                                           CreativeReview.library_item_id == ref)).scalar_one_or_none()
        if row is None:
            return None
        return {"status": row.status, "reason": row.reason, "reason_label": reasons.label(row.reason),
                "note": row.note, "regenerate_action_id": row.regenerate_action_id}


def _change_request(item: dict[str, Any], reason: str, note: str) -> str:
    parts = [f"Remake: {item['title']}", f"Change: {reasons.CHANGE_REQUEST[reason]}"]
    if note:
        parts.append(f"Note: {note}")
    return ". ".join(parts)


def _regenerate(user_id: str, item: dict[str, Any], reason: str, note: str, *, confirm_spend: bool,
                deps_factory: Callable[[], Any]) -> dict[str, Any]:
    from app.domains.brand_agent import gate

    payload = item["payload"]
    ref = item["external_ref"]
    with get_session() as session:  # type: ignore[misc]
        row = session.execute(select(CreativeReview).where(CreativeReview.user_id == user_id,
                                                           CreativeReview.library_item_id == ref)).scalar_one()
        if row.regenerate_action_id:  # a repeated tap never pays twice
            return gate.views_by_id(session, user_id, [row.regenerate_action_id]).get(row.regenerate_action_id, {})
        kind = gate.KIND_VIDEO if payload.get("kind") == "video" else gate.KIND_IMAGE
        action = gate.propose(session, user_id, str(payload.get("space_id") or ""), None, kind=kind,
                              title=f"Regenerate: {item['title']}"[:300],
                              payload={"prompt": _change_request(item, reason, note), "regenerate_of": ref,
                                       "reason": reason})
        row.status, row.regenerate_action_id = STATUS_REGENERATED, action["id"]
        session.flush()
        if confirm_spend:
            action = gate.decide(session, deps_factory(), user_id, action["id"], gate.APPROVE)
        return action


def decide(user_id: str, item_id: str, decision: str, *, reason: str = "", note: str = "",
           confirm_spend: bool = False, deps_factory: Callable[[], Any] | None = None,
           via: str = "web") -> dict[str, Any]:
    if decision not in DECISIONS:
        raise ReviewError("decision must be approve, reject or regenerate")
    try:
        reason_id = reasons.check(decision, reason)
    except reasons.ReasonError as exc:
        raise ReviewError(exc.message, exc.status_code) from exc
    clean_note = " ".join(str(note or "").split())[:MAX_NOTE]
    item = _item(user_id, item_id)
    _remember(user_id, item, reason_id, clean_note)
    approvals = _approvals()
    verdict = approvals.APPROVE if decision == "approve" else approvals.REJECT
    label = reasons.label(reason_id)
    try:
        outcome = approvals.decide(user_id, item_id, verdict, actor=user_id, via=via,
                                   note=f"{decision}: {label}".strip(": ") if label else decision)
    except approvals.ApprovalError as exc:
        raise ReviewError(str(exc), exc.status_code) from exc
    action = None
    if decision == "regenerate":
        if deps_factory is None:
            from app.domains.brand_agent.deps import default_deps as deps_factory  # noqa: N813
        action = _regenerate(user_id, item, reason_id, clean_note, confirm_spend=confirm_spend,
                             deps_factory=deps_factory)
    return {"item": outcome["item"], "idempotent": outcome["idempotent"],
            "review": _review_view(user_id, item["external_ref"]), "regenerate_action": action}


__all__ = ["DECISIONS", "ReviewError", "decide", "queue", "stats"]
