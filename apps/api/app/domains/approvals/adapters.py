"""Source adapters for the approvals feed.

Each adapter turns one subsystem's own "waiting for a human" rows into
:class:`Candidate` records, and applies a decision by delegating to that
subsystem's existing service. Adapters never post, send or spend on their own:

* ``social_reply`` - autopilot reply drafts (``EngagementAction`` kind=reply,
  status=pending_approval). Approve sends through
  :func:`app.domains.social_inbox.autopilot.approve` (the normal reply path);
  reject calls :func:`~app.domains.social_inbox.autopilot.reject`, which only
  flips the draft's status and never contacts the platform.
* ``publish_hold`` - posts the pre-publish content gate held
  (``PlatformPost`` status=held). Approve re-queues the post with a one-shot
  gate override; reject cancels it.
* ``ad_budget`` - daily cross-network budget proposals
  (``AdAllocationProposal`` status=proposed). Approve marks the proposal
  ``approved`` for the allocator to apply; reject marks it ``rejected``.

The Wave L producers (``design_publish``, ``capture_publish``,
``catalog_import``) live in :mod:`app.domains.approvals.producers`: approving
schedules the design's image posts, turns a capture into reel jobs, or turns a
catalog product into an Ad Studio project with its default ads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select

from app.domains.approvals.models import (
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    SOURCE_AD_BUDGET,
    SOURCE_PUBLISH_HOLD,
    SOURCE_SOCIAL_REPLY,
)

try:
    from app.models.db.base import get_session
except Exception:  # pragma: no cover - the service reports the import failure
    get_session = None  # type: ignore[assignment]

#: Upper bound on rows one adapter reads per sync; a truncated scan never expires items.
SCAN_LIMIT = 200


class ApprovalExecError(RuntimeError):
    """The source service refused or failed a decision."""

    def __init__(self, message: str, *, status_code: int = 400, gone: bool = False) -> None:
        self.status_code = status_code
        #: True when the source row was already handled elsewhere (item -> expired).
        self.gone = gone
        super().__init__(message)


@dataclass(frozen=True)
class Candidate:
    external_ref: str
    title: str
    summary: str
    risk: str
    payload: dict = field(default_factory=dict)
    expires_at: datetime | None = None


@dataclass(frozen=True)
class Adapter:
    source: str
    scan: Callable[[Any, str], tuple[list[Candidate], bool]]
    approve: Callable[[str, str, dict], dict]
    reject: Callable[[str, str], dict]


def _clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# social_reply
# --------------------------------------------------------------------------- #
def _scan_social(session: Any, user_id: str) -> tuple[list[Candidate], bool]:
    from app.domains.social_inbox.engagement_models import ACT_REPLY, AS_PENDING, EngagementAction

    rows = session.execute(
        select(EngagementAction)
        .where(EngagementAction.user_id == user_id, EngagementAction.status == AS_PENDING,
               EngagementAction.kind == ACT_REPLY)
        .order_by(EngagementAction.created_at.desc())
        .limit(SCAN_LIMIT + 1)
    ).scalars().all()
    complete = len(rows) <= SCAN_LIMIT
    out: list[Candidate] = []
    for row in rows[:SCAN_LIMIT]:
        who = row.author_name or "someone"
        out.append(Candidate(
            external_ref=row.id,
            title=_clip(f"Reply to {who} on {row.platform}", 300),
            summary=_clip(f"They wrote: \"{row.excerpt}\" Draft reply: \"{row.text}\"", 1000),
            risk=RISK_MEDIUM,
            payload={
                "platform": row.platform,
                "thread_id": row.thread_id,
                "author_name": row.author_name or "",
                "excerpt": _clip(row.excerpt, 1000),
                "text": row.text or "",
                "label": row.label or "",
                "open_path": "/inbox",
                "editable_fields": ["text"],
            },
        ))
    return out, complete


def _map_autopilot(exc: Exception) -> ApprovalExecError:
    status = int(getattr(exc, "status_code", 400) or 400)
    return ApprovalExecError(str(exc), status_code=status, gone=status in (404, 409))


def _approve_social(user_id: str, ref: str, edits: dict) -> dict:
    from app.domains.social_inbox import autopilot

    text = str(edits.get("text") or "").strip()[:1000]
    try:
        record = autopilot.approve(user_id, ref, text=text)
    except autopilot.AutopilotError as exc:
        raise _map_autopilot(exc) from exc
    return {"action": "reply_sent", "action_id": record.get("id"), "status": record.get("status")}


def _reject_social(user_id: str, ref: str) -> dict:
    from app.domains.social_inbox import autopilot

    try:
        record = autopilot.reject(user_id, ref)
    except autopilot.AutopilotError as exc:
        raise _map_autopilot(exc) from exc
    return {"action": "draft_rejected", "action_id": record.get("id"), "status": record.get("status")}


# --------------------------------------------------------------------------- #
# publish_hold
# --------------------------------------------------------------------------- #
def _scan_publish(session: Any, user_id: str) -> tuple[list[Candidate], bool]:
    from app.domains.publishing.extended.models import POST_HELD, PlatformPost

    rows = session.execute(
        select(PlatformPost)
        .where(PlatformPost.user_id == user_id, PlatformPost.status == POST_HELD)
        .order_by(PlatformPost.created_at.desc())
        .limit(SCAN_LIMIT + 1)
    ).scalars().all()
    complete = len(rows) <= SCAN_LIMIT
    out: list[Candidate] = []
    for row in rows[:SCAN_LIMIT]:
        label = row.title or row.text or "a post"
        out.append(Candidate(
            external_ref=row.id,
            title=_clip(f"Held post for {row.platform}: {label}", 300),
            summary=_clip(row.error or "The content check held this post for a human review.", 1000),
            risk=RISK_MEDIUM,
            payload={
                "platform": row.platform,
                "job_id": row.job_id,
                "post_title": row.title or "",
                "text": row.text or "",
                "hashtags": list(row.hashtags or []),
                "hold_reason": row.error or "",
                "open_path": "/publish",
            },
        ))
    return out, complete


def _publishing():
    from app.domains.publishing.extended import posts
    from app.domains.publishing.extended import repository as repo
    from app.domains.publishing.extended.models import POST_CANCELED, POST_HELD, POST_SCHEDULED

    return posts, repo, POST_HELD, POST_SCHEDULED, POST_CANCELED


def _approve_publish(user_id: str, ref: str, _edits: dict) -> dict:
    posts, repo, held, scheduled, _canceled = _publishing()
    moment = repo.utcnow()
    with posts.get_session() as session:  # type: ignore[misc]
        row = repo.get_post(session, user_id, ref)
        if row is None:
            raise ApprovalExecError("post not found", status_code=404, gone=True)
        if row.status != held:
            raise ApprovalExecError("this post is no longer held", status_code=409, gone=True)
        from app.domains.publishing.extended.images import keep_media

        row.status = scheduled
        row.attempts = 0
        row.error = ""
        # Keep an image post's pages; everything else about the old attempt is reset.
        row.progress = {**keep_media(row.progress), "gate_override": {"at": moment.isoformat()}}
        row.scheduled_at = moment
        row.next_attempt_at = moment
        session.flush()
        post_id = row.id
    posts._enqueue(post_id)
    return {"action": "post_requeued", "post_id": post_id, "status": scheduled}


def _reject_publish(user_id: str, ref: str) -> dict:
    posts, repo, held, _scheduled, canceled = _publishing()
    with posts.get_session() as session:  # type: ignore[misc]
        row = repo.get_post(session, user_id, ref)
        if row is None:
            raise ApprovalExecError("post not found", status_code=404, gone=True)
        if row.status != held:
            raise ApprovalExecError("this post is no longer held", status_code=409, gone=True)
        row.status = canceled
        row.next_attempt_at = None
        session.flush()
    return {"action": "post_canceled", "post_id": ref, "status": canceled}


# --------------------------------------------------------------------------- #
# ad_budget
# --------------------------------------------------------------------------- #
def _money(micros: int, currency: str) -> str:
    return f"{(micros or 0) / 1_000_000:,.2f} {currency or 'USD'}"


def _split_text(split: dict) -> str:
    parts = [f"{k} {round(float(v) * 100)}%" for k, v in sorted((split or {}).items()) if _is_number(v)]
    return ", ".join(parts) or "none"


def _is_number(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _scan_budget(session: Any, user_id: str) -> tuple[list[Candidate], bool]:
    from app.domains.ads.allocation_models import STATUS_PROPOSED, AdAllocationProposal

    rows = session.execute(
        select(AdAllocationProposal)
        .where(AdAllocationProposal.user_id == user_id, AdAllocationProposal.status == STATUS_PROPOSED)
        .order_by(AdAllocationProposal.run_date.desc())
        .limit(SCAN_LIMIT + 1)
    ).scalars().all()
    complete = len(rows) <= SCAN_LIMIT
    out: list[Candidate] = []
    for row in rows[:SCAN_LIMIT]:
        delta = float(row.max_delta or 0.0)
        out.append(Candidate(
            external_ref=row.id,
            title=_clip(f"Budget split for {row.run_date.isoformat()} "
                        f"({_money(row.total_daily_budget_micros, row.currency)} per day)", 300),
            summary=_clip(f"Now: {_split_text(row.current_split)}. Proposed: {_split_text(row.proposed_split)}. "
                          f"{row.reason or ''}", 1000),
            risk=RISK_HIGH if delta >= 0.2 else RISK_MEDIUM if delta > 0 else RISK_LOW,
            payload={
                "run_date": row.run_date.isoformat(),
                "currency": row.currency,
                "total_daily_budget_micros": int(row.total_daily_budget_micros or 0),
                "current_split": dict(row.current_split or {}),
                "proposed_split": dict(row.proposed_split or {}),
                "max_delta": delta,
                "method": row.method,
                "open_path": "/ads",
            },
        ))
    return out, complete


def _decide_budget(user_id: str, ref: str, new_status: str, action: str) -> dict:
    from app.domains.ads.allocation_models import STATUS_PROPOSED, AdAllocationProposal

    if get_session is None:
        raise ApprovalExecError("persistence is not available", status_code=503)
    with get_session() as session:
        row = session.get(AdAllocationProposal, ref)
        if row is None or row.user_id != user_id:
            raise ApprovalExecError("budget proposal not found", status_code=404, gone=True)
        if row.status != STATUS_PROPOSED:
            raise ApprovalExecError("this budget proposal was already handled", status_code=409, gone=True)
        row.status = new_status
        session.flush()
    return {"action": action, "proposal_id": ref, "status": new_status}


def _approve_budget(user_id: str, ref: str, _edits: dict) -> dict:
    from app.domains.ads.allocation_models import STATUS_APPROVED

    return _decide_budget(user_id, ref, STATUS_APPROVED, "budget_approved")


def _reject_budget(user_id: str, ref: str) -> dict:
    from app.domains.ads.allocation_models import STATUS_REJECTED

    return _decide_budget(user_id, ref, STATUS_REJECTED, "budget_rejected")


ADAPTERS: dict[str, Adapter] = {
    SOURCE_SOCIAL_REPLY: Adapter(SOURCE_SOCIAL_REPLY, _scan_social, _approve_social, _reject_social),
    SOURCE_PUBLISH_HOLD: Adapter(SOURCE_PUBLISH_HOLD, _scan_publish, _approve_publish, _reject_publish),
    SOURCE_AD_BUDGET: Adapter(SOURCE_AD_BUDGET, _scan_budget, _approve_budget, _reject_budget),
}


def _register_producers() -> None:
    from app.domains.approvals.producers import PRODUCER_ADAPTERS
    from app.domains.approvals.models import SOURCE_AD_ACTION
    from app.domains.integrations import actions as ad_actions

    ADAPTERS.update(PRODUCER_ADAPTERS)
    ADAPTERS[SOURCE_AD_ACTION] = Adapter(SOURCE_AD_ACTION, ad_actions.scan, ad_actions.approve, ad_actions.reject)
    _register_wave2()


def _register_wave2() -> None:
    from app.domains.approvals.models import SOURCE_CREATIVE_REVIEW, SOURCE_STUDIO_RENDER
    from app.domains.creative_review import adapter as review
    from app.domains.studio_render import adapter as renders

    ADAPTERS[SOURCE_CREATIVE_REVIEW] = Adapter(SOURCE_CREATIVE_REVIEW, review.scan, review.approve, review.reject)
    ADAPTERS[SOURCE_STUDIO_RENDER] = Adapter(SOURCE_STUDIO_RENDER, renders.scan, renders.approve, renders.reject)


_register_producers()

__all__ = ["ADAPTERS", "Adapter", "ApprovalExecError", "Candidate", "SCAN_LIMIT"]
