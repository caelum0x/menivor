"""Engagement autopilot: rules over new inbox comments and DMs.

For every connected platform the creator turned on, each new inbound message
is labelled (:mod:`.engagement_classify`) and the creator's rules decide:

* **spam**          -> hide it where the platform allows (else flag it).
* **abuse**         -> flag it; hide it too when the creator chose that.
* **buying intent** -> route the conversation to Leads.
* **positive**      -> like it where the platform allows; draft a reply that
                       waits for approval (default) or is sent right away
                       when the creator switched replies to automatic.

Guarantees:

* Off by default. Replies need approval by default.
* Each action happens at most once per inbound message (unique key), even if
  two runs overlap: the row is inserted *before* the platform call.
* Actions that call the platform (like, hide, reply) count toward the
  per-account daily cap; over the cap they are recorded as ``skipped``.
* Everything - including rule changes - lands in the audit log.
* Automatic replies go through the same send path as a manual reply, so the
  launch gate, granted scopes and Instagram's 24-hour DM window still apply;
  when a reply cannot be sent it becomes a draft waiting for approval.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

from . import bluesky_client, facebook_client, instagram_client, threads_client, youtube_client
from . import engagement_store as store
from . import repository as repo
from .capabilities import PLATFORM_LABELS, PLATFORMS, YES, PlatformCapabilities
from .engagement_classify import (
    ABUSE,
    BUYING_INTENT,
    POSITIVE,
    QUESTION,
    SPAM,
    Classification,
    classify,
    lead_score,
)
from .engagement_models import (
    ACT_FLAG,
    ACT_HIDE,
    ACT_LEAD,
    ACT_LIKE,
    ACT_REPLY,
    ACT_SETTINGS,
    ACTOR_AUTOPILOT,
    ACTOR_CREATOR,
    AS_DONE,
    AS_FAILED,
    AS_PENDING,
    AS_QUEUED,
    AS_REJECTED,
    AS_SKIPPED,
    CAPPED_KINDS,
    DEFAULT_DAILY_CAP,
    LEAD_STATUSES,
    MAX_DAILY_CAP,
    REPLY_APPROVE,
    REPLY_AUTO,
    REPLY_MODES,
    REPLY_OFF,
    EngagementAction,
    EngagementLead,
    EngagementSettings,
)
from .models import KIND_DM, STATUS_DONE, InboxThread
from .platform_types import InboxPlatformError, Transport, default_transport
from .replies import ReplyError, publishing_open, reply_mode, send_reply
from .suggestions import suggest
from .sync import AccountAccess, require_ready, resolve_account

try:
    from app.models.db.base import get_session
except Exception:  # pragma: no cover - require_ready() reports the import failure
    get_session = None  # type: ignore[assignment]

LIKE_SUPPORTED = frozenset({"facebook", "bluesky"})
HIDE_SUPPORTED = frozenset({"youtube", "instagram", "facebook", "threads"})
_LIKE_NOTES = {
    "youtube": "YouTube's API does not let apps like comments.",
    "instagram": "Instagram's API does not let apps like comments.",
    "threads": "The Threads API does not let apps like replies.",
}
_HIDE_NOTES = {
    "bluesky": "Bluesky replies can't be hidden from Menivor; they are flagged for you instead.",
}
FIRST_RUN_LOOKBACK = timedelta(days=2)
MAX_LOOKBACK = timedelta(days=7)
RUN_OVERLAP = timedelta(minutes=15)
PER_PLATFORM_LIMIT = 40
MAX_BLOCKED_WORDS = 50
TICK_USERS = 50
TICK_BUDGET_S = 200.0

_DEFAULTS = {
    "enabled": False, "auto_like": True, "reply_mode": REPLY_APPROVE, "reply_to_questions": False,
    "hide_spam": True, "hide_abuse": False, "route_leads": True, "daily_cap": DEFAULT_DAILY_CAP,
    "blocked_words": [],
}
_EDITABLE = tuple(_DEFAULTS)


class AutopilotError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400, open_url: str = "") -> None:
        self.status_code = status_code
        self.open_url = open_url
        super().__init__(message)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


# --------------------------------------------------------------------------- #
# What each platform lets the autopilot do
# --------------------------------------------------------------------------- #
def support_for(platform: str, caps: PlatformCapabilities | None) -> dict:
    comments = caps.comments if caps is not None else None
    reply = comments.reply if comments is not None else "not_offered"
    can_act = caps is not None and caps.connected and comments is not None and comments.read == YES
    return {
        "read": comments.read if comments is not None else "not_offered",
        "like": bool(can_act and platform in LIKE_SUPPORTED),
        "like_note": "" if platform in LIKE_SUPPORTED else _LIKE_NOTES.get(platform, "Liking is not available here."),
        "hide": bool(can_act and platform in HIDE_SUPPORTED and comments.reply == YES),
        "hide_note": "" if platform in HIDE_SUPPORTED else _HIDE_NOTES.get(platform, "Hiding is not available here."),
        "reply": reply,
        "reply_note": comments.note if comments is not None else "",
    }


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
def _values(row: EngagementSettings | None) -> dict:
    if row is None:
        return dict(_DEFAULTS)
    return {key: getattr(row, key) if getattr(row, key) is not None else _DEFAULTS[key] for key in _EDITABLE}


def settings_record(platform: str, row: EngagementSettings | None, caps: PlatformCapabilities | None,
                    used: int) -> dict:
    values = _values(row)
    return {
        "platform": platform,
        "label": PLATFORM_LABELS.get(platform, platform),
        "connected": bool(caps and caps.connected),
        "support": support_for(platform, caps),
        **values,
        "blocked_words": list(values["blocked_words"] or []),
        "used_today": used,
        "last_run_at": _iso(row.last_run_at) if row is not None else None,
    }


def overview(session: Any, user_id: str) -> dict:
    from .views import capability_map

    caps = capability_map(session, user_id)
    rows = store.settings_rows(session, user_id)
    used = store.used_today(session, user_id, _utcnow())
    return {
        "platforms": [settings_record(p, rows.get(p), caps.get(p), used.get(p, 0)) for p in PLATFORMS],
        "pending_approvals": store.pending_count(session, user_id),
        "new_leads": store.new_lead_count(session, user_id),
        "sending_enabled": publishing_open(),
        "max_daily_cap": MAX_DAILY_CAP,
    }


def _clean_changes(changes: dict) -> dict:
    out: dict = {}
    for key, value in changes.items():
        if key not in _EDITABLE or value is None:
            continue
        if key == "reply_mode":
            mode = str(value).strip().lower()
            if mode not in REPLY_MODES:
                raise AutopilotError(f"reply_mode must be one of {sorted(REPLY_MODES)}")
            out[key] = mode
        elif key == "daily_cap":
            try:
                cap = int(value)
            except (TypeError, ValueError) as exc:
                raise AutopilotError("daily_cap must be a whole number") from exc
            if not 0 <= cap <= MAX_DAILY_CAP:
                raise AutopilotError(f"daily_cap must be between 0 and {MAX_DAILY_CAP}")
            out[key] = cap
        elif key == "blocked_words":
            if not isinstance(value, (list, tuple)):
                raise AutopilotError("blocked_words must be a list")
            words = sorted({str(w).strip().lower()[:40] for w in value if str(w).strip()})
            if len(words) > MAX_BLOCKED_WORDS:
                raise AutopilotError(f"at most {MAX_BLOCKED_WORDS} blocked words")
            out[key] = words
        else:
            out[key] = bool(value)
    return out


def update_settings(user_id: str, platform: str, changes: dict, *, now: datetime | None = None) -> dict:
    require_ready()
    plat = str(platform or "").strip().lower()
    if plat not in PLATFORMS:
        raise AutopilotError("unknown platform", status_code=404)
    clean = _clean_changes(changes or {})
    moment = now or _utcnow()
    from .views import capability_map

    with get_session() as session:  # type: ignore[misc]
        row = store.get_or_create_settings(session, user_id, plat)
        before = _values(row)
        diff = {k: {"from": before[k], "to": v} for k, v in clean.items() if before.get(k) != v}
        for key, value in clean.items():
            setattr(row, key, value)
        if diff:
            store.try_add_action(
                session, user_id=user_id, thread_id=None, platform=plat, kind=ACT_SETTINGS, status=AS_DONE,
                actor=ACTOR_CREATOR, message_key=f"settings:{uuid.uuid4().hex}",
                reason=_describe_changes(diff), executed_at=moment,
            )
        session.flush()
        caps = capability_map(session, user_id).get(plat)
        used = store.used_today(session, user_id, moment).get(plat, 0)
        return settings_record(plat, row, caps, used)


def _describe_changes(diff: dict) -> str:
    names = {
        "enabled": "Autopilot", "auto_like": "Like positive comments", "reply_mode": "Replies",
        "reply_to_questions": "Also draft replies to questions", "hide_spam": "Hide spam",
        "hide_abuse": "Hide abuse", "route_leads": "Send buying intent to Leads", "daily_cap": "Daily limit",
        "blocked_words": "Blocked words",
    }

    def fmt(value: Any) -> str:
        if isinstance(value, bool):
            return "on" if value else "off"
        if isinstance(value, list):
            return f"{len(value)} word{'s' if len(value) != 1 else ''}"
        return str(value)

    return "; ".join(f"{names.get(k, k)}: {fmt(v['from'])} -> {fmt(v['to'])}" for k, v in diff.items())[:1000]


# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _Candidate:
    thread_id: str
    platform: str
    kind: str
    external_thread_id: str
    post_external_id: str
    post_title: str
    author_name: str
    message_key: str
    text: str
    reply_api: bool
    reply_reason: str


@dataclass
class _Planned:
    candidate: _Candidate
    label: Classification
    actions: list[dict] = field(default_factory=list)


def _latest_inbound(thread: InboxThread) -> tuple[str, str]:
    inbound = [m for m in (thread.messages or []) if isinstance(m, dict) and not m.get("from_me")]
    if not inbound:
        return "", thread.text or ""
    last = max(inbound, key=lambda m: str(m.get("at") or ""))
    return str(last.get("id") or ""), str(last.get("text") or "")


def _gather(user_id: str, moment: datetime) -> tuple[dict, dict[str, AccountAccess], list[_Candidate], dict]:
    """Enabled settings, fresh platform access and unprocessed candidates (one DB session)."""
    with get_session() as session:  # type: ignore[misc]
        rows = store.settings_rows(session, user_id)
        enabled = {p: _values(r) for p, r in rows.items() if r.enabled and p in PLATFORMS}
        if not enabled:
            return {}, {}, [], {}
        used = store.used_today(session, user_id, moment)
        access: dict[str, AccountAccess] = {}
        candidates: list[_Candidate] = []
        publishing = publishing_open()
        for plat, row in ((p, rows[p]) for p in enabled):
            acc = resolve_account(session, user_id, plat)
            access[plat] = acc
            last = row.last_run_at
            if last is not None and last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            since = max(moment - MAX_LOOKBACK, (last - RUN_OVERLAP) if last else moment - FIRST_RUN_LOOKBACK)
            row.last_run_at = moment
            if not acc.connected:
                continue
            threads = store.candidate_threads(session, user_id, plat, since, limit=PER_PLATFORM_LIMIT)
            done = store.processed_keys(session, user_id, [t.id for t in threads])
            for thread in threads:
                message_id, text = _latest_inbound(thread)
                key = (message_id or f"text:{hashlib.sha1(text.encode('utf-8')).hexdigest()[:16]}")[:200]
                if (thread.id, key) in done or not text.strip():
                    continue
                post = repo.get_post(session, user_id, thread.post_id) if thread.post_id else None
                mode = reply_mode(thread, post, acc.caps, publishing=publishing, now=moment)
                candidates.append(_Candidate(
                    thread_id=thread.id, platform=plat, kind=thread.kind,
                    external_thread_id=thread.external_thread_id,
                    post_external_id=post.external_id if post is not None else "",
                    post_title=post.title if post is not None else "",
                    author_name=thread.author_name or "", message_key=key, text=text,
                    reply_api=mode.mode == "api", reply_reason=mode.reason,
                ))
        return enabled, access, candidates, used


def _plan(c: _Candidate, rules: dict, caps: PlatformCapabilities | None) -> _Planned:
    label = classify(c.text, kind=c.kind, blocked_words=rules.get("blocked_words") or [])
    plan = _Planned(candidate=c, label=label)
    support = support_for(c.platform, caps)
    is_comment = c.kind != KIND_DM
    why = f"Looks like {label.label.replace('_', ' ')}" + (f" ({', '.join(label.signals)})" if label.signals else "")

    if label.label == SPAM:
        if rules["hide_spam"] and is_comment and support["hide"]:
            plan.actions.append({"kind": ACT_HIDE, "reason": why})
        else:
            plan.actions.append({"kind": ACT_FLAG, "reason": why + (
                "" if not rules["hide_spam"] or not is_comment else f". {support['hide_note']}")})
    elif label.label == ABUSE:
        plan.actions.append({"kind": ACT_FLAG, "reason": why})
        if rules["hide_abuse"] and is_comment and support["hide"]:
            plan.actions.append({"kind": ACT_HIDE, "reason": why})
    elif label.label == BUYING_INTENT:
        if rules["route_leads"]:
            plan.actions.append({"kind": ACT_LEAD, "reason": why})
    elif label.label == POSITIVE or (label.label == QUESTION and rules["reply_to_questions"]):
        if label.label == POSITIVE and rules["auto_like"] and is_comment and support["like"]:
            plan.actions.append({"kind": ACT_LIKE, "reason": why})
        if rules["reply_mode"] != REPLY_OFF:
            plan.actions.append({"kind": ACT_REPLY, "reason": why})
    return plan


def _draft_reply(c: _Candidate) -> tuple[str, str]:
    result = suggest(platform=c.platform, post_title=c.post_title, author=c.author_name, comment=c.text, kind=c.kind)
    text = result.replies[0] if result.replies else ""
    return text, result.source


def run_for_user(user_id: str, *, transport: Transport | None = None, now: datetime | None = None) -> dict:
    """One autopilot pass for a creator. Returns counts per outcome."""
    require_ready()
    moment = now or _utcnow()
    enabled, access, candidates, used = _gather(user_id, moment)
    summary = {"checked": len(candidates), "liked": 0, "hidden": 0, "flagged": 0, "leads": 0,
               "replies_sent": 0, "drafts": 0, "skipped": 0, "failed": 0}
    if not candidates:
        return summary

    plans = [_plan(c, enabled[c.platform], access[c.platform].caps) for c in candidates]
    for plan in plans:
        for action in plan.actions:
            if action["kind"] == ACT_REPLY:
                action["text"], action["text_source"] = _draft_reply(plan.candidate)

    queued = _record_plans(user_id, plans, enabled, used, moment, summary)
    tx = transport or default_transport()
    results = [_execute(user_id, item, access[item["platform"]], tx) for item in queued]
    _finish(user_id, results, moment, summary)
    return summary


def _record_plans(user_id: str, plans: list[_Planned], enabled: dict, used: dict, moment: datetime,
                  summary: dict) -> list[dict]:
    """Insert every planned action once; return those that must call the platform now."""
    budget = {p: max(0, int(enabled[p]["daily_cap"]) - used.get(p, 0)) for p in enabled}
    queued: list[dict] = []
    with get_session() as session:  # type: ignore[misc]
        for plan in plans:
            c = plan.candidate
            thread = repo.get_thread(session, user_id, c.thread_id)
            if thread is None:
                continue
            for action in plan.actions:
                kind = action["kind"]
                status, reason = AS_DONE, action["reason"]
                if kind == ACT_REPLY:
                    auto = enabled[c.platform]["reply_mode"] == REPLY_AUTO and c.reply_api
                    status = AS_QUEUED if auto else AS_PENDING
                    if enabled[c.platform]["reply_mode"] == REPLY_AUTO and not c.reply_api:
                        reason = f"{reason}. Waiting for approval: {c.reply_reason}"
                    if not action.get("text"):
                        continue
                elif kind in CAPPED_KINDS:
                    status = AS_QUEUED
                if status == AS_QUEUED:
                    if budget.get(c.platform, 0) <= 0:
                        status, reason = AS_SKIPPED, (
                            f"Daily limit of {enabled[c.platform]['daily_cap']} actions reached for "
                            f"{PLATFORM_LABELS.get(c.platform, c.platform)}.")
                    else:
                        budget[c.platform] -= 1
                row = store.try_add_action(
                    session, user_id=user_id, thread_id=c.thread_id, platform=c.platform, kind=kind, status=status,
                    actor=ACTOR_AUTOPILOT, message_key=c.message_key, label=plan.label.label,
                    confidence=plan.label.confidence, reason=reason[:1000], text=action.get("text", ""),
                    text_source=action.get("text_source", ""), excerpt=c.text[:500], author_name=c.author_name[:200],
                    detail={"signals": list(plan.label.signals)},
                    executed_at=moment if status == AS_DONE else None,
                )
                if row is None:
                    continue  # another run already handled this message
                if kind == ACT_LEAD:
                    store.upsert_lead(session, user_id=user_id, thread=thread,
                                      source="dm" if c.kind == KIND_DM else "comment", excerpt=c.text,
                                      signals=list(plan.label.signals),
                                      score=lead_score(plan.label, kind=c.kind))
                    summary["leads"] += 1
                elif kind == ACT_FLAG:
                    summary["flagged"] += 1
                elif status == AS_PENDING:
                    summary["drafts"] += 1
                elif status == AS_SKIPPED:
                    summary["skipped"] += 1
                if status == AS_QUEUED:
                    queued.append({"action_id": row.id, "kind": kind, "platform": c.platform,
                                   "candidate": c, "text": action.get("text", "")})
    return queued


def _execute(user_id: str, item: dict, access: AccountAccess, transport: Transport) -> dict:
    """Call the platform for one queued action (no DB session held)."""
    c: _Candidate = item["candidate"]
    kind = item["kind"]
    try:
        if kind == ACT_REPLY:
            row = send_reply(user_id, c.thread_id, item["text"], transport=transport)
            return {**item, "status": AS_DONE, "external_id": row.reply_external_id or ""}
        if kind == ACT_LIKE:
            return {**item, "status": AS_DONE, "external_id": _like(c, access, transport)}
        if kind == ACT_HIDE:
            return {**item, "status": AS_DONE, "external_id": _hide(c, access, transport)}
        return {**item, "status": AS_FAILED, "error": "unsupported action"}
    except ReplyError as exc:
        # The reply could not go out automatically: keep it as a draft for the creator.
        return {**item, "status": AS_PENDING, "error": str(exc)}
    except InboxPlatformError as exc:
        return {**item, "status": AS_FAILED, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - network failure
        logger.warning(f"autopilot {kind} failed for thread {c.thread_id}: {exc}")
        return {**item, "status": AS_FAILED, "error": "The platform could not be reached."}


def _like(c: _Candidate, access: AccountAccess, transport: Transport) -> str:
    if c.platform == "facebook":
        return facebook_client.like_comment(access.token, c.external_thread_id, transport=transport)
    if c.platform == "bluesky":
        session = bluesky_client.session_for(access.external_account_id, access.token,
                                             str(access.meta.get("pds") or "https://bsky.social"), transport=transport)
        return bluesky_client.like_comment(session, c.external_thread_id, transport=transport)
    raise InboxPlatformError(c.platform, _LIKE_NOTES.get(c.platform, "Liking is not available here."))


def _hide(c: _Candidate, access: AccountAccess, transport: Transport) -> str:
    if c.platform == "youtube":
        return youtube_client.hide_comment(access.token, c.external_thread_id, transport=transport)
    if c.platform == "instagram":
        return instagram_client.hide_comment(access.token, c.external_thread_id, transport=transport)
    if c.platform == "facebook":
        return facebook_client.hide_comment(access.token, c.external_thread_id, transport=transport)
    if c.platform == "threads":
        return threads_client.hide_comment(access.token, c.external_thread_id, transport=transport)
    raise InboxPlatformError(c.platform, _HIDE_NOTES.get(c.platform, "Hiding is not available here."))


def _finish(user_id: str, results: list[dict], moment: datetime, summary: dict) -> None:
    if not results:
        return
    with get_session() as session:  # type: ignore[misc]
        for res in results:
            row = store.get_action(session, user_id, res["action_id"])
            if row is None:
                continue
            row.status = res["status"]
            row.error = str(res.get("error") or "")[:1000]
            row.external_id = str(res.get("external_id") or "")[:300]
            if res["status"] == AS_DONE:
                row.executed_at = moment
                key = {ACT_LIKE: "liked", ACT_HIDE: "hidden", ACT_REPLY: "replies_sent"}[res["kind"]]
                summary[key] += 1
                if res["kind"] == ACT_HIDE:
                    thread = repo.get_thread(session, user_id, res["candidate"].thread_id)
                    if thread is not None:
                        thread.status = STATUS_DONE
                        thread.done_at = moment
            elif res["status"] == AS_PENDING:
                row.reason = f"{row.reason}. Not sent automatically: {row.error}"[:1000]
                summary["drafts"] += 1
            else:
                summary["failed"] += 1


def tick(now: datetime | None = None, *, transport: Transport | None = None) -> dict[str, int]:
    """One beat pass over every creator with the autopilot on (bounded)."""
    require_ready()
    moment = now or _utcnow()
    with get_session() as session:  # type: ignore[misc]
        users = store.users_with_autopilot(session, limit=TICK_USERS)
    started = time.monotonic()
    totals = {"users": 0, "failed_users": 0}
    tx = transport or default_transport()
    for user_id in users:
        if time.monotonic() - started > TICK_BUDGET_S:
            break
        try:
            summary = run_for_user(user_id, transport=tx, now=moment)
            totals["users"] += 1
            for key, value in summary.items():
                totals[key] = totals.get(key, 0) + int(value)
        except Exception as exc:  # noqa: BLE001 - one creator must not stop the tick
            totals["failed_users"] += 1
            logger.error(f"engagement autopilot failed for user {user_id}: {exc}")
    return totals


# --------------------------------------------------------------------------- #
# Approvals, leads, audit log
# --------------------------------------------------------------------------- #
def action_record(row: EngagementAction) -> dict:
    return {
        "id": row.id,
        "thread_id": row.thread_id,
        "platform": row.platform,
        "platform_label": PLATFORM_LABELS.get(row.platform, row.platform),
        "kind": row.kind,
        "status": row.status,
        "actor": row.actor,
        "label": row.label or "",
        "confidence": row.confidence,
        "signals": list((row.detail or {}).get("signals") or []),
        "reason": row.reason or "",
        "text": row.text or "",
        "text_source": row.text_source or "",
        "excerpt": row.excerpt or "",
        "author_name": row.author_name or "",
        "error": row.error or "",
        "created_at": _iso(row.created_at),
        "executed_at": _iso(row.executed_at),
        "decided_at": _iso(row.decided_at),
    }


def lead_record(row: EngagementLead) -> dict:
    return {
        "id": row.id,
        "thread_id": row.thread_id,
        "platform": row.platform,
        "platform_label": PLATFORM_LABELS.get(row.platform, row.platform),
        "source": row.source,
        "author_name": row.author_name or "",
        "excerpt": row.excerpt or "",
        "signals": list(row.signals or []),
        "score": int(row.score or 0),
        "status": row.status,
        "note": row.note or "",
        "permalink": row.permalink or "",
        "last_message_at": _iso(row.last_message_at),
        "created_at": _iso(row.created_at),
    }


def list_actions(user_id: str, *, statuses: tuple[str, ...] = (), kinds: tuple[str, ...] = (), platform: str = "",
                 limit: int = 50, offset: int = 0) -> dict:
    require_ready()
    with get_session() as session:  # type: ignore[misc]
        rows, total = store.list_actions(session, user_id, statuses=statuses, kinds=kinds, platform=platform,
                                         limit=limit, offset=offset)
        return {"actions": [action_record(r) for r in rows], "total": total, "limit": limit, "offset": offset}


def approve(user_id: str, action_id: str, *, text: str = "", now: datetime | None = None) -> dict:
    """Send an approved (optionally edited) reply draft through the normal reply path."""
    require_ready()
    moment = now or _utcnow()
    with get_session() as session:  # type: ignore[misc]
        row = store.get_action(session, user_id, action_id)
        if row is None:
            raise AutopilotError("draft not found", status_code=404)
        if row.status != AS_PENDING or row.kind != ACT_REPLY or not row.thread_id:
            raise AutopilotError("this draft was already handled", status_code=409)
        thread_id = row.thread_id
        body = (text or row.text or "").strip()
    try:
        thread = send_reply(user_id, thread_id, body)
    except ReplyError as exc:
        with get_session() as session:  # type: ignore[misc]
            row = store.get_action(session, user_id, action_id)
            if row is not None:
                row.error = str(exc)[:1000]
        raise AutopilotError(str(exc), status_code=exc.status_code, open_url=exc.open_url) from exc
    with get_session() as session:  # type: ignore[misc]
        row = store.get_action(session, user_id, action_id)
        if row is None:
            raise AutopilotError("draft not found", status_code=404)
        row.status = AS_DONE
        row.actor = ACTOR_CREATOR
        row.text = body
        row.error = ""
        row.external_id = (thread.reply_external_id or "")[:300]
        row.decided_at = moment
        row.executed_at = moment
        session.flush()
        return action_record(row)


def reject(user_id: str, action_id: str, *, now: datetime | None = None) -> dict:
    require_ready()
    with get_session() as session:  # type: ignore[misc]
        row = store.get_action(session, user_id, action_id)
        if row is None:
            raise AutopilotError("draft not found", status_code=404)
        if row.status != AS_PENDING:
            raise AutopilotError("this draft was already handled", status_code=409)
        row.status = AS_REJECTED
        row.actor = ACTOR_CREATOR
        row.decided_at = now or _utcnow()
        session.flush()
        return action_record(row)


def list_leads(user_id: str, *, status: str = "", limit: int = 50, offset: int = 0) -> dict:
    require_ready()
    if status and status not in LEAD_STATUSES:
        raise AutopilotError(f"status must be one of {sorted(LEAD_STATUSES)}")
    with get_session() as session:  # type: ignore[misc]
        rows, total = store.list_leads(session, user_id, status=status, limit=limit, offset=offset)
        return {"leads": [lead_record(r) for r in rows], "total": total, "limit": limit, "offset": offset}


def update_lead(user_id: str, lead_id: str, *, status: str | None = None, note: str | None = None) -> dict:
    require_ready()
    if status is not None and status not in LEAD_STATUSES:
        raise AutopilotError(f"status must be one of {sorted(LEAD_STATUSES)}")
    with get_session() as session:  # type: ignore[misc]
        row = store.get_lead(session, user_id, lead_id)
        if row is None:
            raise AutopilotError("lead not found", status_code=404)
        if status is not None:
            row.status = status
        if note is not None:
            row.note = str(note).strip()[:1000]
        session.flush()
        return lead_record(row)
