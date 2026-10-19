"""Platform events for OTT channels (Wave Q QM1.5, U39): signed webhooks and viewer push.

Three events reach the channel owner's webhook subscriptions:

* ``ott.title.published``: the first time a title becomes watchable on the
  channel, i.e. it is published AND packaged (see "When a title is announced");
* ``ott.purchase.granted``: a buy, rental or subscription grant from the
  creator's own processor (no amount, no buyer identity: a salted viewer hash);
* ``ott.live.started``: a live stream went on air.

Delivery reuses the MN8 path end to end: :func:`webhook_subscriptions.dispatch`
writes one outbox row per subscription (idempotent on the event id), signs
with the subscription secret (Standard Webhooks ``webhook-id`` /
``webhook-timestamp`` / ``webhook-signature``, plus the deprecated body-only
``X-Menivor-Signature``; see :mod:`app.services.webhooks`), and the minute beat
``menivor-webhook-retry`` retries with backoff until delivered or dead.

Events are queued after the caller's transaction commits (``after_commit``),
then sent from the worker (``emit_task``); if the queue is down they are sent
in-process instead, so a commit is never lost.

Push: a newly watchable episode (topic ``episodes``) and a live start (topic
``live``) go to viewers who opted in on that channel, and nothing else.

When a title is announced (QM verify): the publish click alone is not enough.
:func:`maybe_title_published` is the one gate, called from both sides of the
race: ``publish_title`` (the title was already packaged) and the packaging-done
hook ``ott_transcode.service.finish`` (the title was published first). It
announces only when the title is published AND packaged and playable by the
same predicate the player and storefront use (``catalog_public.watchable``; a
future ``available_from`` does not hold the announcement back, an expired
``available_until`` does), and only once per title:

* the event id is stable per title (``ott.title.published:<title id>:<published_at>``,
  and ``published_at`` is set once and never cleared), so the webhook outbox
  dedupes publish + packaging on the same id;
* the announcement is recorded in the caller's transaction as an append-only
  ``audit_log`` row (action ``ott.title.announced``, target the title, the event
  id in its metadata); the push is only queued together with that row, so it
  is deduped on the same event id. The title row is re-read after the caller's
  flush, so a publish and a packaging finish racing in two transactions
  serialize on the title row and the second sees the first one's record;
* a free-to-paid re-encrypt (``_protect_after_tier_change``) records the
  announcement before it makes the title unwatchable (covers titles announced
  before this gate existed), so the re-packaging finish never re-announces.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger
from sqlalchemy import event as sa_event, select
from sqlalchemy.orm import Session

from app.workers.celery_app import celery_app

TITLE_PUBLISHED = "ott.title.published"
#: audit_log action that records "this title was announced" (the dedupe record; no extra column).
ANNOUNCED_ACTION = "ott.title.announced"
ANNOUNCED_TARGET = "ott_title"
PURCHASE_GRANTED = "ott.purchase.granted"
LIVE_STARTED = "ott.live.started"
EVENT_TYPES = (TITLE_PUBLISHED, PURCHASE_GRANTED, LIVE_STARTED)
EMIT_TASK = "app.domains.ott.events.emit_task"
PUSH_TOPIC = {TITLE_PUBLISHED: "episodes", LIVE_STARTED: "live"}


def _stamp(value: Optional[datetime]) -> int:
    moment = value or datetime.now(timezone.utc)
    moment = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp())


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


def title_published(channel: Any, title: Any) -> tuple[str, dict[str, Any]]:
    from .feeds import web_base

    payload = {"event_type": TITLE_PUBLISHED, "channel": channel.handle, "title_id": title.id, "title": title.title,
               "kind": title.kind, "season": title.season, "episode": title.episode,
               "access_tier": title.access_tier, "url": f"{web_base()}/c/{channel.handle}/{title.id}",
               "published_at": _iso(title.published_at)}
    return f"{TITLE_PUBLISHED}:{title.id}:{_stamp(title.published_at)}", payload


def _announceable(session: Session, title: Any) -> bool:
    """Published and playable by the player's own predicate; a future start window does not block it."""
    from . import catalog_public

    moment = datetime.now(timezone.utc)
    start = title.available_from
    if start is not None:
        start = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        moment = max(moment, start)
    return title.published_at is not None and catalog_public.watchable(session, title, now=moment)


def already_announced(session: Session, channel: Any, title: Any) -> bool:
    from app.models.db.models import AuditLog, WebhookDelivery

    marked = session.execute(select(AuditLog.id).where(
        AuditLog.actor_user_id == str(channel.user_id), AuditLog.action == ANNOUNCED_ACTION,
        AuditLog.target_type == ANNOUNCED_TARGET, AuditLog.target_id == str(title.id)).limit(1)).first()
    if marked is not None:
        return True
    # Announced before the audit record existed: the outbox already holds this event id.
    event_id, _payload = title_published(channel, title)
    return session.execute(select(WebhookDelivery.id).where(
        WebhookDelivery.event_id == event_id).limit(1)).first() is not None


def _record_announced(session: Session, channel: Any, title: Any, event_id: str) -> None:
    from app.services import audit

    audit.record(session, actor_user_id=str(channel.user_id), action=ANNOUNCED_ACTION,
                 target_type=ANNOUNCED_TARGET, target_id=str(title.id), metadata={"event_id": event_id})


def _fresh(session: Session, title: Any) -> Optional[Any]:
    """The title as committed by now: flush ours, then re-read (a racing publish/finish may have landed)."""
    from .models import OttChannel

    session.flush()
    try:
        session.refresh(title)
    except Exception as exc:  # noqa: BLE001 - a detached/deleted title is simply not announced
        logger.warning(f"ott title {getattr(title, 'id', '?')} not re-read for the announcement: {exc}")
        return None
    return session.get(OttChannel, title.channel_id)


def maybe_title_published(session: Session, title: Any) -> bool:
    """Queue ``ott.title.published`` (and the new-episode push) if the title just became watchable.

    Emits only when the title is published, packaged and playable, and has not
    been announced before; returns whether it queued the event. Never raises.
    """
    try:
        channel = _fresh(session, title)
        if channel is None or not _announceable(session, title) or already_announced(session, channel, title):
            return False
        event_id, payload = title_published(channel, title)
        with session.begin_nested():  # a failed insert never poisons the caller's transaction
            _record_announced(session, channel, title, event_id)
        queue(session, channel.id, TITLE_PUBLISHED, event_id, payload)
        return True
    except Exception as exc:  # noqa: BLE001 - an announcement never fails a publish or a packaging finish
        logger.warning(f"ott title {getattr(title, 'id', '?')} announcement skipped: {exc}")
        return False


def mark_announced_if_live(session: Session, title: Any) -> bool:
    """Record the announcement for a title that is watchable now, without sending anything.

    Called before a re-packaging makes the title unwatchable (free to paid), so
    its finish does not announce the title a second time.
    """
    try:
        channel = _fresh(session, title)
        if channel is None or not _announceable(session, title) or already_announced(session, channel, title):
            return False
        event_id, _payload = title_published(channel, title)
        with session.begin_nested():
            _record_announced(session, channel, title, event_id)
        return True
    except Exception as exc:  # noqa: BLE001 - never block the tier change
        logger.warning(f"ott title {getattr(title, 'id', '?')} announcement record skipped: {exc}")
        return False


def purchase_granted(channel: Any, offer: Any, entitlement: Any, mint_event_id: str) -> tuple[str, dict[str, Any]]:
    from app.domains.ott_analytics.service import viewer_hash

    payload = {"event_type": PURCHASE_GRANTED, "channel": channel.handle, "offer_kind": offer.kind,
               "sku": offer.sku, "title_id": offer.title_id, "entitlement_id": entitlement.id,
               "viewer": viewer_hash(f"viewer:{entitlement.viewer_id}")[:16],
               "granted_at": _iso(entitlement.granted_at), "expires_at": _iso(entitlement.expires_at)}
    return f"{PURCHASE_GRANTED}:{mint_event_id}", payload


def live_started(channel: Any, stream: Any) -> tuple[str, dict[str, Any]]:
    from .feeds import web_base

    payload = {"event_type": LIVE_STARTED, "channel": channel.handle, "stream_id": stream.id,
               "title": getattr(stream, "title", "") or "", "url": f"{web_base()}/c/{channel.handle}/live/{stream.id}",
               "started_at": _iso(stream.started_at)}
    return f"{LIVE_STARTED}:{stream.id}:{_stamp(stream.started_at)}", payload


def queue(session: Session, channel_id: str, event_type: str, event_id: str, payload: dict[str, Any]) -> None:
    """Send the event once the caller's transaction has committed (never inside it)."""

    def _send(_session) -> None:
        try:
            emit_task.delay(channel_id, event_type, event_id, payload)
        except Exception as exc:  # noqa: BLE001 - the broker is down: send in-process, never lose the event
            logger.warning(f"ott event {event_type} not queued ({exc}); sending in-process")
            emit_now(channel_id, event_type, event_id, payload)

    sa_event.listen(session, "after_commit", _send, once=True)


def _owner_workspaces(session: Session, user_id: str) -> list[str]:
    from app.models.db.models import WorkspaceMember

    from app.models.db.repositories import WORKSPACE_ROLE_OWNER

    # QM verify: only workspaces the channel owner owns. A membership in someone else's team
    # must not route this channel's title and purchase events to that team's webhooks.
    return sorted({str(ws) for ws in session.execute(select(WorkspaceMember.workspace_id).where(
        WorkspaceMember.user_id == user_id, WorkspaceMember.role == WORKSPACE_ROLE_OWNER)).scalars()})


def emit_now(channel_id: str, event_type: str, event_id: str, payload: dict[str, Any], *,
             session: Optional[Session] = None) -> dict[str, int]:
    """Dispatch to the owner's subscriptions and push to opted-in viewers. Never raises."""
    if event_type not in EVENT_TYPES:
        return {"deliveries": 0, "pushed": 0}
    if session is None:
        from app.models.db.base import get_session

        with get_session() as own:
            return emit_now(channel_id, event_type, event_id, payload, session=own)
    from app.services import webhook_subscriptions

    from .models import OttChannel

    counts = {"deliveries": 0, "pushed": 0}
    channel = session.get(OttChannel, channel_id)
    if channel is None:
        return counts
    for workspace in _owner_workspaces(session, str(channel.user_id)):
        try:
            counts["deliveries"] += len(webhook_subscriptions.dispatch(session, workspace, event_type, payload,
                                                                       event_id=event_id))
        except Exception as exc:  # noqa: BLE001 - one workspace never blocks the others
            logger.warning(f"ott event {event_type} dispatch to {workspace} failed: {exc}")
    topic = PUSH_TOPIC.get(event_type)
    if topic:
        try:
            counts["pushed"] = push_viewers(session, channel, topic, payload)
        except Exception as exc:  # noqa: BLE001 - never raise: a retry would re-send the webhooks' push twin
            logger.warning(f"ott event {event_type} push failed: {exc}")
    return counts


def push_message(channel: Any, topic: str, payload: dict[str, Any]) -> tuple[str, str, dict[str, str]]:
    name = channel.title or channel.handle
    if topic == "live":
        return f"{name} is live", str(payload.get("title") or "Watch now"), {
            "handle": channel.handle, "kind": "live", "stream_id": str(payload.get("stream_id") or "")}
    return f"New on {name}", str(payload.get("title") or ""), {
        "handle": channel.handle, "kind": "episode", "title_id": str(payload.get("title_id") or "")}


def push_viewers(session: Session, channel: Any, topic: str, payload: dict[str, Any]) -> int:
    """Expo push to the channel's opted-in viewers for ``topic``; returns messages sent (best effort)."""
    from app.domains.ott_viewers import retention
    from app.domains.ott_viewers.models import OttViewerPush
    from app.services import push

    tokens = [t for t in retention.push_tokens(session, channel.id, topic) if push._is_valid_expo_token(t)]
    if not tokens:
        return 0
    title, body, data = push_message(channel, topic, payload)
    sent = 0
    for batch in push._chunk(tokens, push._MAX_BATCH):
        messages = [{"to": t, "title": title, "body": body, "data": data, "sound": "default"} for t in batch]
        tickets = push._post_batch(messages)
        sent += len(batch) if tickets else 0
        for token, ticket in zip(batch, tickets):
            details = ticket.get("details") if isinstance(ticket, dict) else None
            if isinstance(details, dict) and details.get("error") == "DeviceNotRegistered":
                session.query(OttViewerPush).filter(OttViewerPush.token == token).delete()
    return sent


@celery_app.task(name=EMIT_TASK, bind=True, max_retries=5, default_retry_delay=30)
def emit_task(self, channel_id: str, event_type: str, event_id: str, payload: dict[str, Any]) -> dict[str, int]:
    try:
        return emit_now(channel_id, event_type, event_id, payload)
    except Exception as exc:  # noqa: BLE001 - retried; dispatch itself is idempotent on the event id
        logger.error(f"ott event {event_type} failed: {exc}")
        raise self.retry(exc=exc)


__all__ = ["ANNOUNCED_ACTION", "EMIT_TASK", "EVENT_TYPES", "LIVE_STARTED", "PURCHASE_GRANTED", "TITLE_PUBLISHED",
           "already_announced", "emit_now", "emit_task", "live_started", "mark_announced_if_live",
           "maybe_title_published", "purchase_granted", "push_message", "push_viewers", "queue", "title_published"]
