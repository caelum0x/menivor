"""Approval gate: every agent action that spends credits or publishes waits for a human.

* :func:`propose` records a ``pending`` :class:`AgentAction`. Nothing runs.
* :func:`decide` applies approve / reject. Approve first claims the row with a
  guarded ``UPDATE ... WHERE status IN (pending, failed)`` so two concurrent
  approvals cannot both execute; then the action runs through its port and the
  row ends ``executed`` or ``failed`` (failed is retryable). Repeating the same
  decision returns the recorded action; the opposite decision on a decided
  action is a 409.
* Errors stored on the row are user-facing reasons only, never raw exceptions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from loguru import logger
from sqlalchemy import select, update

from app.domains.adstudio.extract import clean_text
from app.domains.brand_agent import library, memory
from app.domains.brand_agent.models import AgentAction
from app.domains.brand_agent.ports.base import PortUnavailable

KIND_IMAGE = "generate_image"
KIND_VIDEO = "generate_video"
KIND_CLONE = "clone_ad"
KIND_PUBLISH = "publish"
KIND_ROUTINE_BATCH = "routine_batch"
GATED_KINDS = frozenset({KIND_IMAGE, KIND_VIDEO, KIND_CLONE, KIND_PUBLISH, KIND_ROUTINE_BATCH})

#: Shown before approval; the real charge is made by the generation service. A clone is a
#: priced plan ($0); its paid render is approved separately on the Ad Clone page.
CREDIT_ESTIMATES = {KIND_IMAGE: 1, KIND_VIDEO: 5, KIND_CLONE: 0, KIND_PUBLISH: 0}

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_EXECUTED = "executed"
STATUS_REJECTED = "rejected"
STATUS_FAILED = "failed"
#: Something is missing (sign-in, credits, a product, an account): no Approve until it is fixed.
STATUS_BLOCKED = "blocked"
STATUSES = frozenset({STATUS_PENDING, STATUS_APPROVED, STATUS_EXECUTED, STATUS_REJECTED, STATUS_FAILED,
                      STATUS_BLOCKED})
DECIDABLE = (STATUS_PENDING, STATUS_FAILED)

APPROVE = "approve"
REJECT = "reject"
MAX_ROUTINE_BATCH = 10
MAX_LIST = 100


class GateError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def estimate(kind: str, payload: dict[str, Any]) -> int:
    if kind == KIND_ROUTINE_BATCH:
        media = KIND_VIDEO if payload.get("media") == "video" else KIND_IMAGE
        return CREDIT_ESTIMATES[media] * max(1, int(payload.get("count") or 1))
    return CREDIT_ESTIMATES.get(kind, 0)


def view(row: AgentAction) -> dict[str, Any]:
    return {
        "id": row.id,
        "space_id": row.space_id,
        "session_id": row.session_id,
        "routine_id": row.routine_id,
        "kind": row.kind,
        "status": row.status,
        "title": row.title,
        "payload": dict(row.payload or {}),
        "credits_estimate": row.credits_estimate,
        "spends_credits": row.kind != KIND_PUBLISH,
        "publishes": row.kind == KIND_PUBLISH,
        "result": dict(row.result) if row.result and row.status != STATUS_BLOCKED else None,
        "needs": list((row.result or {}).get("needs") or []) if row.status == STATUS_BLOCKED else [],
        "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
    }


def propose(session: Any, user_id: str, space_id: str, session_id: str | None, *, kind: str, title: str,
            payload: dict[str, Any], routine_id: str | None = None,
            needs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A pending action, or a blocked one when ``needs`` lists what is missing before Approve."""
    if kind not in GATED_KINDS:
        raise GateError(f"unknown action kind: {kind}")
    row = AgentAction(user_id=user_id, space_id=space_id, session_id=session_id, routine_id=routine_id, kind=kind,
                      status=STATUS_BLOCKED if needs else STATUS_PENDING, title=clean_text(title, 300),
                      payload=dict(payload), credits_estimate=estimate(kind, payload),
                      result={"needs": list(needs)} if needs else None)
    session.add(row)
    session.flush()
    return view(row)


def open_blocked(session: Any, user_id: str, session_id: str, kind: str) -> AgentAction | None:
    """The blocked action of this kind already waiting in this chat, if any (never show it twice)."""
    return session.execute(
        select(AgentAction).where(AgentAction.user_id == user_id, AgentAction.session_id == session_id,
                                  AgentAction.kind == kind, AgentAction.status == STATUS_BLOCKED)
        .order_by(AgentAction.created_at.desc())
    ).scalars().first()


def set_needs(session: Any, user_id: str, action_id: str, needs: list[dict[str, Any]],
              payload_update: dict[str, Any] | None = None) -> dict[str, Any]:
    """Re-checked: blocked with the new needs, or pending (Approve shows) when nothing is missing."""
    row = _get(session, user_id, action_id)
    if row.status not in (STATUS_BLOCKED, STATUS_PENDING, STATUS_FAILED):
        return view(row)
    if payload_update:
        row.payload = {**dict(row.payload or {}), **payload_update}
    if needs:
        row.status, row.result = STATUS_BLOCKED, {"needs": list(needs)}
    else:
        row.status, row.result, row.error = STATUS_PENDING, None, ""
    session.flush()
    return view(row)


def _get(session: Any, user_id: str, action_id: str) -> AgentAction:
    row = session.get(AgentAction, action_id) if action_id else None
    if row is None or row.user_id != user_id:
        raise GateError("action not found", 404)
    return row


def _claim(session: Any, row: AgentAction, new_status: str) -> bool:
    result = session.execute(
        update(AgentAction)
        .where(AgentAction.id == row.id, AgentAction.status.in_(DECIDABLE))
        .values(status=new_status, decided_at=_now())
        .execution_options(synchronize_session=False)
    )
    session.flush()
    session.refresh(row)
    return bool(result.rowcount)


def _media(row: AgentAction, sections: dict[str, Any], deps: Any, session: Any, kind: str,
           request: str, variation: int = 0) -> dict[str, Any]:
    from app.domains.brand_agent.writers import creative_prompt

    prompt = creative_prompt(sections, request, kind=kind, variation=variation)
    result = deps.generation.generate(session=session, user_id=row.user_id, kind=kind, prompt=prompt,
                                      options=dict(row.payload.get("options") or {}))
    library.add_item(session, user_id=row.user_id, space_id=row.space_id, action_id=row.id, kind=kind,
                     ref=str(result.get("ref", "")), url=str(result.get("url", "")), title=row.title)
    return dict(result)


def _execute(session: Any, deps: Any, row: AgentAction) -> dict[str, Any]:
    sections = memory.current(session, row.space_id)["sections"]
    payload = dict(row.payload or {})
    if row.kind in {KIND_IMAGE, KIND_VIDEO}:
        kind = "image" if row.kind == KIND_IMAGE else "video"
        return _media(row, sections, deps, session, kind, str(payload.get("prompt", "")))
    if row.kind == KIND_ROUTINE_BATCH:
        kind = "video" if payload.get("media") == "video" else "image"
        count = max(1, min(int(payload.get("count") or 1), MAX_ROUTINE_BATCH))
        items, failed = [], 0
        for i in range(count):
            try:
                items.append(_media(row, sections, deps, session, kind, str(payload.get("prompt", "")), i))
            except Exception as exc:  # noqa: BLE001 - counted; the rest of the batch still runs
                logger.warning(f"brand agent batch item failed: {type(exc).__name__}")
                failed += 1
        if not items:
            raise PortUnavailable("None of the variations could be made. Try approving again.")
        # Partial success still counts as executed so a retry never pays twice for the made ones.
        return {"items": items, "count": len(items), "failed": failed}
    if row.kind == KIND_CLONE:
        extra = {"preset": str(payload["preset"])} if payload.get("preset") else {}
        result = deps.ad_clone.clone_from_link(row.user_id, str(payload.get("url", "")), brand=sections,
                                               space_id=row.space_id, **extra)
        library.add_item(session, user_id=row.user_id, space_id=row.space_id, action_id=row.id, kind="clone",
                         ref=str(result.get("job_id", "")), title=row.title)
        return dict(result)
    if row.kind == KIND_PUBLISH:
        return dict(deps.publisher.publish(session=session, user_id=row.user_id, payload=payload))
    raise PortUnavailable(f"unknown action kind: {row.kind}")


def _run(session: Any, deps: Any, row: AgentAction) -> None:
    try:
        result = _execute(session, deps, row)
    except PortUnavailable as exc:
        row.status, row.error, row.result = STATUS_FAILED, clean_text(exc.reason, 500), None
    except Exception as exc:  # noqa: BLE001 - recorded as a plain, secret-free reason
        logger.warning(f"brand agent action {row.id} ({row.kind}) failed: {type(exc).__name__}")
        row.status, row.error, row.result = STATUS_FAILED, "That step failed on our side. Try approving again.", None
    else:
        row.status, row.error, row.result, row.executed_at = STATUS_EXECUTED, "", result, _now()
    session.flush()


def decide(session: Any, deps: Any, user_id: str, action_id: str, decision: str) -> dict[str, Any]:
    if decision not in {APPROVE, REJECT}:
        raise GateError("decision must be approve or reject")
    row = _get(session, user_id, action_id)
    if decision == REJECT:
        if row.status == STATUS_REJECTED:
            return view(row)
        if not _claim(session, row, STATUS_REJECTED):
            raise GateError("This action was already approved.", 409)
        return view(row)
    if row.status in {STATUS_EXECUTED, STATUS_APPROVED}:
        return view(row)
    if row.status == STATUS_REJECTED:
        raise GateError("This action was rejected. Ask me again to make a new one.", 409)
    if row.status == STATUS_BLOCKED:
        return view(row)  # nothing runs until the inline step is done
    from app.domains.brand_agent import preflight

    needs = preflight.check(session, deps, user_id, row.space_id, row.kind, dict(row.payload or {}),
                            memory.current(session, row.space_id)["sections"])
    if needs:  # something changed since the action was shown: block instead of failing
        return set_needs(session, user_id, row.id, needs)
    if not _claim(session, row, STATUS_APPROVED):
        return view(row)  # a concurrent approval won the claim; it executes
    _run(session, deps, row)
    return view(row)


def list_actions(session: Any, user_id: str, *, status: str | None = None,
                 space_id: str | None = None) -> list[dict[str, Any]]:
    stmt = select(AgentAction).where(AgentAction.user_id == user_id)
    if status:
        stmt = stmt.where(AgentAction.status == status)
    if space_id:
        stmt = stmt.where(AgentAction.space_id == space_id)
    rows = session.execute(stmt.order_by(AgentAction.created_at.desc()).limit(MAX_LIST)).scalars().all()
    return [view(r) for r in rows]


def views_by_id(session: Any, user_id: str, ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    wanted = [i for i in ids if i]
    if not wanted:
        return {}
    rows = session.execute(
        select(AgentAction).where(AgentAction.user_id == user_id, AgentAction.id.in_(wanted))
    ).scalars().all()
    return {r.id: view(r) for r in rows}


__all__ = [
    "APPROVE",
    "CREDIT_ESTIMATES",
    "GATED_KINDS",
    "GateError",
    "KIND_CLONE",
    "KIND_IMAGE",
    "KIND_PUBLISH",
    "KIND_ROUTINE_BATCH",
    "KIND_VIDEO",
    "REJECT",
    "STATUS_APPROVED",
    "STATUS_EXECUTED",
    "STATUS_BLOCKED",
    "STATUS_FAILED",
    "STATUS_PENDING",
    "STATUS_REJECTED",
    "decide",
    "estimate",
    "list_actions",
    "propose",
    "view",
    "views_by_id",
]
