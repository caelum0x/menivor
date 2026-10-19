"""Money lifecycle mail (MG5): payment failed, Autopilot paused, credits low.

Contract: ``gtm/policy/ACCOUNT-LIFECYCLE.md`` section 4.

* **One per cause.** Each email is keyed by ``(kind, cause)``: a failed renewal
  is ``<subscription>:<period end>``, a pause is ``<channel>:<paused_at>``, a
  low balance is the ledger id of the last top-up. An append-only audit row
  (``lifecycle_mail.sent`` / ``lifecycle_mail.suppressed``) records the
  decision, so a webhook replay or a second sweep never sends again.
* **Budget (L1).** At most :data:`MONTHLY_BUDGET` lifecycle emails per account
  per calendar month (UTC). Priority (payment failed > work paused > credits
  low) is kept by reserving a slot: credits low may only send while fewer than
  two lifecycle emails went out this month (:data:`_SLOT_LIMIT`). Over budget
  the notice stays in-app only.
* **Always in-app.** Every notice also writes one in-app notification, so the
  banner shows even when the email is not sent.
* **Unsubscribe (L3).** Every email carries a visible link plus
  ``List-Unsubscribe`` (https and mailto) and ``List-Unsubscribe-Post``. One
  click records a ``lifecycle_mail`` consent withdrawal; transactional mail
  continues. Without a signing secret no lifecycle email is sent (in-app only).
* **L4.** Nothing is sent to a deleted account, or to one whose plan is
  cancelled and whose balance is 0 or less.

Entry points: :func:`on_plan_status` (one call from
``creator_subscriptions.apply_update``), :func:`on_channel_paused` (subscribed
to MN1's ``channel_paused`` signal by :func:`install`), and :func:`sweep` (beat
task in ``workers/tasks_lifecycle_mail.py``), which catches anything the
signals missed. Nothing here raises into a caller.
"""

from __future__ import annotations

import hashlib
import hmac
import inspect
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from loguru import logger

PAYMENT_FAILED = "payment_failed"
AUTOPILOT_PAUSED = "autopilot_paused"
CREDITS_LOW = "credits_low"
KINDS: tuple[str, ...] = (PAYMENT_FAILED, AUTOPILOT_PAUSED, CREDITS_LOW)

MONTHLY_BUDGET = 3
#: A kind may send only while fewer than this many lifecycle emails went out
#: this month, which keeps the last slots for higher-priority notices.
_SLOT_LIMIT: dict[str, int] = {PAYMENT_FAILED: 3, AUTOPILOT_PAUSED: 3, CREDITS_LOW: 2}
LOW_BALANCE = 1
CONSENT_KIND = "lifecycle_mail"
ACTION_SENT = "lifecycle_mail.sent"
ACTION_SUPPRESSED = "lifecycle_mail.suppressed"
UNSUBSCRIBE_PATH = "/api/v1/mail/unsubscribe"
BILLING_PATH = "/settings/billing"
PRICING_PATH = "/pricing"
_SWEEP_LOOKBACK = timedelta(hours=2)
_SCAN_LIMIT = 2000


# --------------------------------------------------------------------------- #
# Unsubscribe tokens
# --------------------------------------------------------------------------- #
def _secret() -> str:
    raw = (os.getenv("MENIVOR_MAIL_UNSUBSCRIBE_SECRET") or "").strip()
    if raw:
        return raw
    try:
        from app.services import crypto_tokens

        return crypto_tokens._resolve_secret()  # domain-separated below
    except Exception:  # noqa: BLE001 - no secret -> no lifecycle email
        return ""


def unsubscribe_token(user_id: str) -> str:
    secret = _secret()
    if not secret or not user_id:
        return ""
    msg = f"menivor-lifecycle-unsubscribe:v1:{user_id}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()[:40]


def verify_unsubscribe(user_id: str, token: str) -> bool:
    expected = unsubscribe_token(user_id)
    return bool(expected) and hmac.compare_digest(expected, str(token or ""))


def api_base_url() -> str:
    raw = (os.getenv("MENIVOR_API_BASE_URL") or "").strip().rstrip("/")
    return raw or "https://api.menivor.com"


def web_base_url() -> str:
    from app.services import job_emails

    return job_emails.web_base_url()


def unsubscribe_url(user_id: str) -> str:
    token = unsubscribe_token(user_id)
    if not token:
        return ""
    return f"{api_base_url()}{UNSUBSCRIBE_PATH}?u={quote(user_id, safe='')}&t={token}"


def unsubscribe(session: Any, user_id: str) -> None:
    """Record the one-click opt-out (append-only consent row, audited)."""
    from app.services.compliance import consent

    consent.record_consent(session, user_id, CONSENT_KIND, False, version="one-click")


def opted_out(session: Any, user_id: str) -> bool:
    from app.models.db.repositories import ConsentRepository

    record = ConsentRepository(session).get_latest(user_id, CONSENT_KIND)
    return record is not None and not bool(record.granted)


# --------------------------------------------------------------------------- #
# Content
# --------------------------------------------------------------------------- #
def _content(kind: str, context: dict[str, Any], unsub: str):
    from app.services.email_templates import EmailAction, EmailContent

    web = web_base_url()
    reason = "You received this because of your Menivor account's billing."
    if kind == PAYMENT_FAILED:
        return EmailContent(
            subject="Your Menivor payment did not go through",
            preheader="Your plan stays on while we retry. Update your card to keep it.",
            title="Your payment did not go through",
            paragraphs=(
                "Your last plan payment failed. Your plan and your credits stay on while the "
                "payment provider retries.",
                "Update your card to keep your plan. If the retries fail, the plan ends and your "
                "paid credit stays in your account.",
            ),
            action=EmailAction(label="Update card", url=str(context.get("portal_url") or web + BILLING_PATH)),
            reason=reason,
            unsubscribe_url=unsub,
        )
    if kind == AUTOPILOT_PAUSED:
        name = str(context.get("channel_name") or "Your Autopilot channel")[:80]
        return EmailContent(
            subject="Autopilot paused: out of credits",
            preheader=f"{name} stopped making reels. Top up and it starts again by itself.",
            title="Autopilot paused",
            paragraphs=(
                f"{name} ran out of credits, so it stopped making new reels. Nothing was charged.",
                "Add credits or pick a plan. Autopilot starts again on its next run, with no "
                "other step.",
            ),
            action=EmailAction(label="Top up", url=web + PRICING_PATH),
            reason=reason,
            unsubscribe_url=unsub,
        )
    left = max(0, int(context.get("balance") or 0))
    unit = "credit" if left == 1 else "credits"
    return EmailContent(
        subject="Your Menivor credits are running low",
        preheader=f"{left} {unit} left.",
        title=f"{left} {unit} left",
        paragraphs=("Each reel uses one credit. Top up or pick a plan to keep making reels.",),
        action=EmailAction(label="Add credits", url=web + PRICING_PATH),
        reason=reason,
        unsubscribe_url=unsub,
    )


_IN_APP = {
    PAYMENT_FAILED: ("Your payment did not go through", "Update your card in Billing to keep your plan."),
    AUTOPILOT_PAUSED: ("Autopilot paused", "Out of credits. Top up and it starts again on its next run."),
    CREDITS_LOW: ("Credits running low", "Top up or pick a plan to keep making reels."),
}


def _send(to: str, rendered: Any) -> bool:
    from email.utils import parseaddr

    from app.services import mailer

    headers = dict(rendered.headers)
    _, sender = parseaddr(os.getenv("MENIVOR_SMTP_FROM") or os.getenv("SMTP_FROM") or os.getenv("EMAIL_FROM") or "")
    if "List-Unsubscribe" in headers and "@" in sender:
        headers["List-Unsubscribe"] += f", <mailto:{sender}?subject=unsubscribe>"
    kwargs: dict[str, Any] = {"to": to, "subject": rendered.subject, "text": rendered.text, "html": rendered.html}
    if "headers" in inspect.signature(mailer.send_email).parameters:
        kwargs["headers"] = headers
    return bool(mailer.send_email(**kwargs))


# --------------------------------------------------------------------------- #
# Decision
# --------------------------------------------------------------------------- #
def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _decided(session: Any, user_id: str, kind: str, cause: str) -> bool:
    from sqlalchemy import select

    from app.models.db.models import AuditLog

    return session.execute(
        select(AuditLog.id).where(
            AuditLog.actor_user_id == user_id,
            AuditLog.action.in_((ACTION_SENT, ACTION_SUPPRESSED)),
            AuditLog.target_type == f"lifecycle:{kind}",
            AuditLog.target_id == cause[:64],
        ).limit(1)
    ).first() is not None


def sent_this_month(session: Any, user_id: str, now: datetime | None = None) -> int:
    from sqlalchemy import func, select

    from app.models.db.models import AuditLog

    start = _month_start(now or datetime.now(timezone.utc))
    return int(session.execute(
        select(func.count(AuditLog.id)).where(
            AuditLog.actor_user_id == user_id,
            AuditLog.action == ACTION_SENT,
            AuditLog.created_at >= start,
        )
    ).scalar() or 0)


def _plan_row(session: Any, user_id: str):
    from sqlalchemy import select

    from app.models.db.creator_subscription import CreatorSubscription

    return session.execute(
        select(CreatorSubscription).where(CreatorSubscription.user_id == user_id)
    ).scalars().first()


def _block_reason(session: Any, user: Any, kind: str, now: datetime) -> str:
    """Why the email must not go out ('' = send). The in-app notice still shows."""
    from app.models.db.repositories import CreditRepository

    email = str(getattr(user, "email", "") or "")
    if "@" not in email or email.startswith("deleted+"):
        return "no_address"
    plan = _plan_row(session, user.id)
    balance = CreditRepository(session).balance(user.id)
    if plan is not None and str(plan.status) == "canceled" and balance <= 0 and kind != PAYMENT_FAILED:
        return "cancelled_no_balance"
    if opted_out(session, user.id):
        return "unsubscribed"
    if sent_this_month(session, user.id, now) >= _SLOT_LIMIT[kind]:
        return "budget"
    if not unsubscribe_token(user.id):
        return "no_unsubscribe_secret"
    from app.services import mailer

    if not mailer.configured():
        return "mailer_not_configured"
    return ""


def _in_app(session: Any, user_id: str, kind: str, cause: str) -> None:
    from app.models.db.repositories import NotificationRepository

    title, body = _IN_APP[kind]
    NotificationRepository(session).create(
        user_id=user_id, kind=f"billing_{kind}", title=title, body=body,
        data={"lifecycle": kind, "cause": cause[:64]},
    )


def notify(kind: str, user_id: str, cause: str, context: dict[str, Any] | None = None,
           *, now: datetime | None = None) -> str:
    """Handle one lifecycle event once. Returns sent | suppressed:<why> | duplicate | error."""
    if kind not in KINDS or not user_id or not cause:
        return "error"
    moment = now or datetime.now(timezone.utc)
    context = dict(context or {})
    try:
        from app.models.db.base import get_session
        from app.models.db.models import User
        from app.services import audit
        from app.services.email_templates import render_email

        with get_session() as session:
            if _decided(session, user_id, kind, cause):
                return "duplicate"
            user = session.get(User, user_id)
            if user is None:
                return "error"
            _in_app(session, user_id, kind, cause)
            why = _block_reason(session, user, kind, moment)
            sent = False
            if not why:
                if kind == PAYMENT_FAILED and not context.get("portal_url"):
                    context["portal_url"] = _portal_url(user_id)
                rendered = render_email(_content(kind, context, unsubscribe_url(user_id)))
                sent = _send(str(user.email), rendered)
                why = "" if sent else "mailer"
            audit.record(
                session, actor_user_id=user_id,
                action=ACTION_SENT if sent else ACTION_SUPPRESSED,
                target_type=f"lifecycle:{kind}", target_id=cause[:64],
                metadata={"kind": kind, "reason": why},
            )
        return "sent" if sent else f"suppressed:{why}"
    except Exception as exc:  # noqa: BLE001 - lifecycle mail never breaks billing
        logger.error(f"lifecycle mail {kind} for {user_id} failed: {exc}")
        return "error"


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #
def _portal_url(user_id: str) -> str:
    try:
        from app.services.billing import creator_plan_actions

        return str(creator_plan_actions.portal(user_id) or "")
    except Exception as exc:  # noqa: BLE001 - fall back to the billing page
        logger.debug(f"lifecycle mail: portal link unavailable for {user_id}: {exc}")
        return ""


def _period_cause(ref: str, period_end: Any) -> str:
    stamp = ""
    if isinstance(period_end, datetime):
        aware = period_end if period_end.tzinfo else period_end.replace(tzinfo=timezone.utc)
        stamp = str(int(aware.timestamp()))
    return f"{ref or 'plan'}:{stamp or 'open'}"


def on_plan_status(user_id: str, status: str, provider_ref: str = "", period_end: Any = None) -> str:
    """Called after every personal-plan update; mails once per failed renewal."""
    if str(status or "") != "past_due" or not user_id:
        return "ignored"
    return notify(PAYMENT_FAILED, user_id, _period_cause(provider_ref, period_end))


def _pause_cause(channel_id: str, params: dict[str, Any], fallback: str) -> str:
    """Same key from the signal and the sweep: the channel plus its ``paused_at``."""
    return f"{channel_id}:{params.get('paused_at') or fallback}"


def _definition_params(channel_id: str) -> dict[str, Any]:
    try:
        from app.models.db.base import get_session
        from app.domains.series import channels

        with get_session() as session:
            row = channels.get_definition(session, channel_id)
            return dict(row.params or {}) if row is not None else {}
    except Exception:  # noqa: BLE001 - an ad-hoc channel has no definition
        return {}


def on_channel_paused(event: Any) -> None:
    """``channel_paused`` handler (MN1 signal): one "top up" email per pause."""
    payload = dict(getattr(event, "payload", None) or {})
    user_id = str(payload.get("user_id") or "")
    channel_id = str(getattr(event, "key", "") or "")
    params = _definition_params(channel_id)
    cause = _pause_cause(channel_id, params, f"run-{payload.get('run_id') or 'run'}")
    notify(AUTOPILOT_PAUSED, user_id, cause, {"channel_name": params.get("name", "")})


_installed: set[int] = set()


def install(bus: Any = None) -> bool:
    """Subscribe :func:`on_channel_paused` to the runner's signal bus once."""
    try:
        if bus is None:
            from app.domains.series.runner import channel_signals as bus
        from app.domains.series.runner import CHANNEL_PAUSED

        if id(bus) in _installed:
            return False
        bus.subscribe(CHANNEL_PAUSED, on_channel_paused)
        _installed.add(id(bus))
        return True
    except Exception as exc:  # noqa: BLE001 - the sweep still catches pauses
        logger.warning(f"lifecycle mail: channel_paused subscribe failed: {exc}")
        return False


def _low_balance_cause(session: Any, user_id: str) -> str:
    from sqlalchemy import select

    from app.models.db.models import CreditLedger

    last_grant = session.execute(
        select(CreditLedger.id).where(
            CreditLedger.user_id == user_id,
            CreditLedger.workspace_id.is_(None),
            CreditLedger.delta > 0,
        ).order_by(CreditLedger.id.desc()).limit(1)
    ).scalar()
    return f"grant:{last_grant}" if last_grant else ""


def on_balance(user_id: str, balance: int) -> str:
    """Credits at :data:`LOW_BALANCE` or fewer: one email per top-up cycle."""
    if not user_id or int(balance) > LOW_BALANCE:
        return "ignored"
    try:
        from app.models.db.base import get_session

        with get_session() as session:
            cause = _low_balance_cause(session, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"lifecycle mail: balance lookup failed for {user_id}: {exc}")
        return "error"
    if not cause:
        return "ignored"
    return notify(CREDITS_LOW, user_id, cause, {"balance": int(balance)})


def sweep(now: datetime | None = None) -> dict[str, int]:
    """Beat catch-up: failed renewals, credit pauses and recent low balances."""
    from sqlalchemy import select

    from app.models.db.base import get_session
    from app.models.db.creator_subscription import CreatorSubscription
    from app.models.db.models import CreditLedger
    from app.models.db.repositories import CreditRepository
    from app.models.db.series_runs import ChannelRun

    moment = now or datetime.now(timezone.utc)
    counts = {k: 0 for k in KINDS}
    try:
        with get_session() as session:
            failed = list(session.execute(
                select(CreatorSubscription.user_id, CreatorSubscription.provider_ref,
                       CreatorSubscription.current_period_end)
                .where(CreatorSubscription.status == "past_due").limit(_SCAN_LIMIT)
            ).all())
            channels = [
                (r.user_id, r.channel_id, dict(r.params or {}))
                for r in session.execute(select(ChannelRun).limit(_SCAN_LIMIT * 5)).scalars()
                if (r.params or {}).get("paused_reason") == "credits"
            ]
            active = {uid for (uid,) in session.execute(
                select(CreditLedger.user_id).where(
                    CreditLedger.workspace_id.is_(None),
                    CreditLedger.delta < 0,
                    CreditLedger.created_at >= moment - _SWEEP_LOOKBACK,
                ).distinct().limit(_SCAN_LIMIT)
            ).all()}
            balances = {uid: CreditRepository(session).balance(uid) for uid in active}
    except Exception as exc:  # noqa: BLE001 - next tick retries
        logger.error(f"lifecycle mail sweep failed to scan: {exc}")
        return counts
    for user_id, ref, period_end in failed:
        if notify(PAYMENT_FAILED, user_id, _period_cause(ref, period_end), now=moment) == "sent":
            counts[PAYMENT_FAILED] += 1
    for user_id, channel_id, params in channels:
        cause = _pause_cause(channel_id, params, "paused")
        if notify(AUTOPILOT_PAUSED, user_id, cause,
                  {"channel_name": params.get("name", "")}, now=moment) == "sent":
            counts[AUTOPILOT_PAUSED] += 1
    for user_id, balance in balances.items():
        if balance <= LOW_BALANCE and on_balance(user_id, balance) == "sent":
            counts[CREDITS_LOW] += 1
    return counts


__all__ = [
    "AUTOPILOT_PAUSED", "CONSENT_KIND", "CREDITS_LOW", "KINDS", "MONTHLY_BUDGET", "PAYMENT_FAILED",
    "install", "notify", "on_balance", "on_channel_paused", "on_plan_status", "opted_out",
    "sent_this_month", "sweep", "unsubscribe", "unsubscribe_token", "unsubscribe_url",
    "verify_unsubscribe",
]
