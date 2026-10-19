"""Studio renders: price first, approve in the approvals feed, then (and only then) spend.

* :func:`create` stores a ``planned`` render with its USD quote and the AI-video
  credits it will hold (``ceil(3 x cents)``, the same rule as Ad Clone). $0.
* :func:`submit` puts it in the approvals feed (source ``studio_render``).
* Approving (see :mod:`.adapter`) checks the paid-render switch, debits the
  credits once and queues the worker. :func:`run` executes the kind's pipeline;
  a failure refunds the credits exactly once.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from loguru import logger
from sqlalchemy import update

from app.domains.studio_render.models import (
    KINDS,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_PLANNED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    StudioRender,
)

try:
    from app.models.db.base import get_session
except Exception:  # pragma: no cover
    get_session = None  # type: ignore[assignment]

DEBIT_PREFIX = "studio_render:"
REFUND_PREFIX = "studio_render_refund:"
OPEN_PATH = {"actor_shot": "/actors", "lipsync_translation": "/translate"}
#: kind -> callable(plan) -> result dict. Filled by the feature modules (tests swap in fakes).
RUNNERS: dict[str, Callable[[Mapping[str, Any]], dict]] = {}


class RenderError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def view(row: StudioRender) -> dict[str, Any]:
    return {
        "id": row.id, "kind": row.kind, "status": row.status, "title": row.title, "plan": dict(row.plan or {}),
        "quote_usd": round(float(row.quote_usd or 0), 4), "credits": int(row.credits or 0),
        "approval_item_id": row.approval_item_id, "result": dict(row.result or {}), "error": row.error or "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def credits_for(usd: float) -> int:
    from app.services.billing.premium_credits import ai_video_credits_for_usd

    return ai_video_credits_for_usd(usd)


def create(session: Any, user_id: str, *, kind: str, title: str, plan: Mapping[str, Any], quote_usd: float) -> dict:
    if kind not in KINDS:
        raise RenderError(f"unknown render kind: {kind}")
    row = StudioRender(user_id=user_id, kind=kind, status=STATUS_PLANNED, title=str(title or kind)[:300],
                       plan=dict(plan), quote_usd=round(float(quote_usd), 4), credits=credits_for(quote_usd),
                       result={})
    session.add(row)
    session.flush()
    return view(row)


def get(session: Any, user_id: str, render_id: str) -> StudioRender:
    row = session.get(StudioRender, render_id) if render_id else None
    if row is None or row.user_id != user_id:
        raise RenderError("render not found", 404)
    return row


def list_renders(session: Any, user_id: str, kind: str | None = None, limit: int = 50) -> list[dict]:
    from sqlalchemy import select

    stmt = select(StudioRender).where(StudioRender.user_id == user_id)
    if kind:
        stmt = stmt.where(StudioRender.kind == kind)
    rows = session.execute(stmt.order_by(StudioRender.created_at.desc()).limit(max(1, min(limit, 100)))).scalars()
    return [view(r) for r in rows]


def submit(session: Any, user_id: str, render_id: str) -> dict:
    """Send a planned render to the approvals feed. Nothing is spent."""
    from app.domains.approvals import service as approvals
    from app.domains.approvals.models import RISK_HIGH, SOURCE_STUDIO_RENDER

    row = get(session, user_id, render_id)
    if row.status not in (STATUS_PLANNED, STATUS_PENDING):
        return view(row)
    usd = f"${row.quote_usd:.2f}"
    item = approvals.enqueue(
        user_id, SOURCE_STUDIO_RENDER, row.id, title=row.title,
        summary=f"Spends {row.credits} AI-video credits (engine cost about {usd}). Nothing runs before you approve.",
        risk=RISK_HIGH, payload={"render_id": row.id, "kind": row.kind, "credits": row.credits,
                                 "quote_usd": row.quote_usd, "spends_credits": True,
                                 "open_path": OPEN_PATH.get(row.kind, "/approvals")},
        session=session)
    row.status = STATUS_PENDING
    row.approval_item_id = item["id"]
    session.flush()
    return view(row)


def refund_once(session: Any, row: StudioRender) -> int:
    from app.services.billing import premium_credits as pc

    reason = f"{REFUND_PREFIX}{row.id}"
    if row.credits <= 0 or not pc.has_reason(session, row.user_id, f"{DEBIT_PREFIX}{row.id}"):
        return 0
    if pc.has_reason(session, row.user_id, reason):
        return 0
    pc.grant(session, row.user_id, pc.KIND_AI_VIDEO, row.credits, reason)
    return row.credits


def run(render_id: str, *, runners: Mapping[str, Callable[[Mapping[str, Any]], dict]] | None = None) -> dict:
    """Worker body: queued -> running -> done | failed (refund once). Safe to call twice."""
    table = RUNNERS if runners is None else runners
    with get_session() as session:  # type: ignore[misc]
        row = session.get(StudioRender, render_id)
        if row is None:
            return {}
        # Guarded claim: a re-enqueued or duplicated task never runs the same render twice.
        claimed = session.execute(
            update(StudioRender).where(StudioRender.id == render_id, StudioRender.status == STATUS_QUEUED)
            .values(status=STATUS_RUNNING).execution_options(synchronize_session=False)).rowcount
        if not claimed:
            session.refresh(row)
            return view(row)
        plan, kind = dict(row.plan or {}), row.kind
    runner = table.get(kind)
    try:
        if runner is None:
            raise RenderError(f"no worker for {kind}")
        result = dict(runner(plan))
    except Exception as exc:  # noqa: BLE001 - a plain reason is stored, credits come back
        message = getattr(exc, "message", "") or "The render failed on the engine side."
        logger.warning(f"studio render {render_id} failed: {type(exc).__name__}")
        return _finish(render_id, STATUS_FAILED, error=str(message)[:500])
    return _finish(render_id, STATUS_DONE, result=result)


def _finish(render_id: str, status: str, *, result: dict | None = None, error: str = "") -> dict:
    with get_session() as session:  # type: ignore[misc]
        row = session.get(StudioRender, render_id)
        if row is None:
            logger.warning(f"studio render {render_id} vanished before it finished")
            return {}
        row.status, row.error = status, error
        if result is not None:
            row.result = result
        if status == STATUS_FAILED:
            refund_once(session, row)
        session.flush()
        return view(row)


STALE_QUEUED_S = 15 * 60
STALE_RUNNING_S = 3 * 3600


def reconcile(*, now: Any = None, enqueue: Callable[[str], None] | None = None, limit: int = 200) -> dict[str, int]:
    """Beat: re-queue approved renders whose task was lost (crash between commit and enqueue) and fail +
    refund renders stuck running past any engine timeout. The guarded claim in :func:`run` makes a
    re-queue of a render that is in fact still queued harmless."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    moment = now or datetime.now(timezone.utc)
    requeued = failed = 0
    with get_session() as session:  # type: ignore[misc]
        queued = session.execute(select(StudioRender.id).where(
            StudioRender.status == STATUS_QUEUED,
            StudioRender.updated_at < moment - timedelta(seconds=STALE_QUEUED_S)).limit(limit)).scalars().all()
        stuck = session.execute(select(StudioRender).where(
            StudioRender.status == STATUS_RUNNING,
            StudioRender.updated_at < moment - timedelta(seconds=STALE_RUNNING_S)).limit(limit)).scalars().all()
        for row in stuck:
            row.status, row.error = STATUS_FAILED, "The render took too long and was stopped; your credits are back."
            refund_once(session, row)
            failed += 1
        for rid in queued:  # touch so the next tick waits again
            session.execute(update(StudioRender).where(StudioRender.id == rid).values(updated_at=moment)
                            .execution_options(synchronize_session=False))
    if enqueue is None:
        from app.domains.studio_render.adapter import ENQUEUE as enqueue  # noqa: N811
    for rid in queued:
        try:
            enqueue(rid)
            requeued += 1
        except Exception as exc:  # noqa: BLE001 - the next tick tries again
            logger.warning(f"studio render {rid} re-queue failed: {type(exc).__name__}")
    return {"requeued": requeued, "failed": failed}


__all__ = ["RUNNERS", "RenderError", "create", "credits_for", "get", "list_renders", "reconcile", "refund_once",
           "run", "submit", "view"]
