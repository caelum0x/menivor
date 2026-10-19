"""Approvals-feed adapter for source ``studio_render`` (the only path that spends).

Approve: paid rendering must be switched on (``ADCLONE_PAID_RENDER``, the same
owner switch as Ad Clone), the AI-video credits are debited once, the row moves to
``queued`` and the worker is queued after commit. If the queue is down the credits
come back. Reject never spends.

Module-level imports must not import ``app.domains.approvals.service`` or ``adapters``.
"""

from __future__ import annotations

from typing import Any, Callable

from app.domains.studio_render import service
from app.domains.studio_render.models import (
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_PLANNED,
    STATUS_QUEUED,
    STATUS_REJECTED,
    StudioRender,
)


def _default_enqueue(render_id: str) -> None:
    from app.domains.studio_render.tasks import run_studio_render_task

    run_studio_render_task.apply_async(args=[render_id], queue="generation")


ENQUEUE: Callable[[str], None] = _default_enqueue
PAID_CHECK: Callable[[], bool] | None = None


def _paid_on() -> bool:
    if PAID_CHECK is not None:
        return bool(PAID_CHECK())
    from app.domains.adclone.service import paid_enabled

    return paid_enabled()


def _err(message: str, status_code: int = 400, gone: bool = False) -> Exception:
    from app.domains.approvals.adapters import ApprovalExecError

    return ApprovalExecError(message, status_code=status_code, gone=gone)


def scan(_session: Any, _user_id: str) -> tuple[list, bool]:
    """Renders are pushed by :func:`service.submit`; never expire them on sync."""
    return [], False


def approve(user_id: str, ref: str, _edits: dict) -> dict:
    from app.services.billing import premium_credits as pc

    with service.get_session() as session:  # type: ignore[misc]
        row = session.get(StudioRender, ref)
        if row is None or row.user_id != user_id:
            raise _err("this render no longer exists", 404, gone=True)
        if row.status not in (STATUS_PENDING, STATUS_PLANNED, STATUS_FAILED):
            return {"action": "already_started", "render_id": row.id, "status": row.status}
        if not _paid_on():
            raise _err("Paid rendering is off on this server. Nothing was charged.", 403)
        if row.credits > 0 and not pc.has_reason(session, user_id, f"{service.DEBIT_PREFIX}{row.id}"):
            try:
                pc.debit(session, user_id, pc.KIND_AI_VIDEO, row.credits, f"{service.DEBIT_PREFIX}{row.id}")
            except pc.InsufficientPremiumCredits as exc:
                raise _err(f"This render needs {exc.needed} AI-video credits; you have {exc.available}.", 402) \
                    from exc
        row.status, row.error = STATUS_QUEUED, ""
        credits = row.credits
    try:
        ENQUEUE(ref)
    except Exception as exc:  # noqa: BLE001 - the queue is down: give everything back
        with service.get_session() as session:  # type: ignore[misc]
            row = session.get(StudioRender, ref)
            row.status, row.error = STATUS_FAILED, "Could not start the render; your credits are back."
            service.refund_once(session, row)
        raise _err("Could not start the render; your credits are back.", 502) from exc
    return {"action": "render_queued", "render_id": ref, "credits": credits}


def reject(user_id: str, ref: str) -> dict:
    with service.get_session() as session:  # type: ignore[misc]
        row = session.get(StudioRender, ref)
        if row is not None and row.user_id == user_id and row.status in (STATUS_PENDING, STATUS_PLANNED):
            row.status = STATUS_REJECTED
    return {"action": "rejected", "render_id": ref}


__all__ = ["ENQUEUE", "approve", "reject", "scan"]
