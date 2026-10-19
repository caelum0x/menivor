"""Onboarding lifecycle sequence (MR3): Day 0, 1, 3 and 7 after sign-up.

A beat tick (``workers/tasks_lifecycle.py``) calls :func:`run`. For each
recent account it finds the step that is due and sends it once:

* **Due.** A step is due from ``signup + offset`` for :data:`GRACE`; a tick
  that finds two steps due sends only the later one and records the earlier
  as ``superseded`` (never two tips on one day).
* **Once.** Every decision is an append-only audit row
  (``onboarding_mail.sent`` / ``onboarding_mail.suppressed``, target
  ``onboarding:<step>``), so a replayed tick never sends again. Through Rally
  Send the idempotency key is ``menivor:onboarding:<user>:<step>``.
* **Stops after payment.** A pack purchase, a live or past monthly plan, or a
  ``paid`` funnel event ends the sequence (every later step is recorded
  ``paid``).
* **Unsubscribe and suppression.** The same one-click opt-out as MG5
  (``lifecycle_mail`` consent): an opted-out account gets nothing, and a
  Rally 422 (suppressed address) is recorded and never retried.
* **No duplicate with existing mail** (MG5 ``lifecycle_mail`` and the
  ``411e7744`` Rally events): a step waits while an MG5 email went out in the
  last :data:`QUIET_AFTER_LIFECYCLE`; Day 7 (plans and packs) is dropped when
  MG5 already sent "credits low" since sign-up; paid accounts (the only ones
  MG5 "payment failed" reaches) never get onboarding mail. The Rally events
  are events, not email; the Menivor onboarding journey in Rally stays off
  (owner step) so Rally does not mail the same sign-up.

Send path: Rally Send (contract 5.2) when ``RALLY_TX_URL`` and
``RALLY_TX_KEY`` are set, otherwise the current SMTP mailer (X11 fallback).
Nothing here raises into the caller.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

from app.services.lifecycle import rally_tx_client as rally
from app.services.lifecycle import templates

ACTION_SENT = "onboarding_mail.sent"
ACTION_SUPPRESSED = "onboarding_mail.suppressed"
TARGET_PREFIX = "onboarding:"
GRACE = timedelta(days=2)
QUIET_AFTER_LIFECYCLE = timedelta(hours=20)
WINDOW = timedelta(days=max(templates.OFFSET_DAYS.values())) + GRACE
_SCAN_LIMIT = 5000
_PURCHASE_PREFIX = "purchase:"
_CARD_CHECK_CREDITS = 1


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def due_steps(signed_up: datetime, now: datetime) -> list[str]:
    """Steps whose window ``[signup + offset, + GRACE)`` contains ``now``."""
    start = _utc(signed_up)
    moment = _utc(now)
    out = []
    for step in templates.STEPS:
        at = start + timedelta(days=templates.OFFSET_DAYS[step])
        if at <= moment < at + GRACE:
            out.append(step)
    return out


def has_paid(session: Any, user_id: str) -> bool:
    """A pack purchase (not the $1 card check), any monthly plan, or a funnel ``paid`` row."""
    from sqlalchemy import select

    from app.models.db.creator_subscription import CreatorSubscription
    from app.models.db.funnel import FunnelEvent
    from app.models.db.models import CreditLedger

    if session.get(FunnelEvent, (str(user_id), "paid")) is not None:
        return True
    if session.execute(
        select(CreatorSubscription.id).where(CreatorSubscription.user_id == str(user_id)).limit(1)
    ).first():
        return True
    return session.execute(
        select(CreditLedger.id).where(
            CreditLedger.user_id == str(user_id),
            CreditLedger.reason.like(f"{_PURCHASE_PREFIX}%"),
            CreditLedger.delta > _CARD_CHECK_CREDITS,
        ).limit(1)
    ).first() is not None


def _decided_steps(session: Any, user_id: str) -> set[str]:
    from sqlalchemy import select

    from app.models.db.models import AuditLog

    rows = session.execute(
        select(AuditLog.target_type).where(
            AuditLog.actor_user_id == str(user_id),
            AuditLog.action.in_((ACTION_SENT, ACTION_SUPPRESSED)),
            AuditLog.target_type.like(f"{TARGET_PREFIX}%"),
        )
    ).scalars()
    return {str(t)[len(TARGET_PREFIX):] for t in rows}


def _lifecycle_mail_since(
    session: Any, user_id: str, since: datetime, until: datetime, kind: str | None = None
) -> bool:
    """Whether MG5 sent a lifecycle email (optionally of ``kind``) in ``[since, until]``."""
    from sqlalchemy import select

    from app.models.db.models import AuditLog
    from app.services.billing import lifecycle_mail

    q = select(AuditLog.id).where(
        AuditLog.actor_user_id == str(user_id),
        AuditLog.action == lifecycle_mail.ACTION_SENT,
        AuditLog.created_at >= since.replace(tzinfo=None),
        AuditLog.created_at <= until.replace(tzinfo=None),
    )
    if kind:
        q = q.where(AuditLog.target_type == f"lifecycle:{kind}")
    return session.execute(q.limit(1)).first() is not None


def _record(session: Any, user_id: str, step: str, sent: bool, reason: str = "", message_id: str = "") -> None:
    from app.services import audit

    audit.record(
        session,
        actor_user_id=str(user_id),
        action=ACTION_SENT if sent else ACTION_SUPPRESSED,
        target_type=f"{TARGET_PREFIX}{step}",
        target_id=str(user_id),
        metadata={"step": step, "reason": reason, "message_id": message_id},
    )


def _block_reason(session: Any, user: Any) -> str:
    from app.services.billing import lifecycle_mail

    email = str(getattr(user, "email", "") or "")
    if "@" not in email or email.startswith("deleted+"):
        return "no_address"
    if lifecycle_mail.opted_out(session, user.id):
        return "unsubscribed"
    if not lifecycle_mail.unsubscribe_token(user.id):
        return "no_unsubscribe_secret"
    return ""


def _deliver(user: Any, step: str, transport: Any = None) -> tuple[str, str]:
    """Render and send one step. Returns ``(outcome, message_id)``; outcome is
    ``sent``, ``retry`` (try a later tick) or ``suppressed``."""
    from app.services.billing import lifecycle_mail
    from app.services.email_templates import render_email

    unsub = lifecycle_mail.unsubscribe_url(user.id)
    rendered = render_email(
        templates.content(
            step,
            web_url=lifecycle_mail.web_base_url(),
            unsubscribe_url=unsub,
            comparison=templates.DAY7_COMPARISON,
        )
    )
    if rally.configured():
        body = rally.build_body(
            to=str(user.email),
            subject=rendered.subject,
            html=rendered.html,
            text=rendered.text,
            key=rally.idempotency_key(user.id, step),
            unsubscribe_url=unsub,
            tags=("onboarding", step),
        )
        result = rally.send(body, transport)
        if result.outcome == rally.SENT:
            return "sent", result.message_id
        if result.outcome == rally.SUPPRESSED:
            return "suppressed", ""
        return "retry", ""
    from app.services import mailer

    if not mailer.configured():
        return "retry", ""
    return ("sent", "") if lifecycle_mail._send(str(user.email), rendered) else ("retry", "")


def run(now: datetime | None = None, transport: Any = None) -> dict[str, int]:
    """One tick over accounts that signed up in the last :data:`WINDOW`."""
    from sqlalchemy import select

    from app.models.db.base import get_session
    from app.models.db.models import User

    moment = _utc(now) or datetime.now(timezone.utc)
    counts = {"sent": 0, "suppressed": 0, "deferred": 0}
    try:
        with get_session() as session:
            users = session.execute(
                select(User).where(User.created_at >= (moment - WINDOW).replace(tzinfo=None))
                .order_by(User.created_at).limit(_SCAN_LIMIT)
            ).scalars().all()
            ids = [(u.id, u.created_at) for u in users]
    except Exception as exc:  # noqa: BLE001 - a tick must never crash the worker
        logger.error(f"onboarding mail: scan failed: {exc}")
        return counts
    for user_id, created in ids:
        try:
            outcome = _tick_user(user_id, created, moment, transport)
        except Exception as exc:  # noqa: BLE001 - one account never stops the rest
            logger.error(f"onboarding mail for {user_id} failed: {exc}")
            outcome = "deferred"
        if outcome in counts:
            counts[outcome] += 1
    return counts


def _tick_user(user_id: str, created: datetime, moment: datetime, transport: Any) -> str:
    from app.models.db.base import get_session
    from app.models.db.models import User
    from app.services.billing import lifecycle_mail

    due = due_steps(created, moment)
    if not due:
        return "none"
    with get_session() as session:
        decided = _decided_steps(session, user_id)
        pending = [s for s in due if s not in decided]
        if not pending:
            return "none"
        step = pending[-1]
        for older in pending[:-1]:
            _record(session, user_id, older, False, "superseded")
        user = session.get(User, user_id)
        if user is None:
            return "none"
        if has_paid(session, user_id):
            _record(session, user_id, step, False, "paid")
            return "suppressed"
        why = _block_reason(session, user)
        if not why and step == templates.DAY7 and _lifecycle_mail_since(
            session, user_id, _utc(created), moment, lifecycle_mail.CREDITS_LOW
        ):
            why = "covered_by_credits_low"
        if why:
            _record(session, user_id, step, False, why)
            return "suppressed"
        if _lifecycle_mail_since(session, user_id, moment - QUIET_AFTER_LIFECYCLE, moment):
            return "deferred"
        outcome, message_id = _deliver(user, step, transport)
        if outcome == "sent":
            _record(session, user_id, step, True, message_id=message_id)
            return "sent"
        if outcome == "suppressed":
            _record(session, user_id, step, False, "rally_suppressed")
            return "suppressed"
        return "deferred"
