"""Customer webhook SUBSCRIPTIONS layer (Enterprise API Platform, Epic 4).

This is the tenant-scoped subscription layer built ON TOP of the existing,
already-hardened delivery primitive :func:`app.services.webhooks.deliver_webhook`
(HMAC-signed + SSRF/DNS-pinned). It does NOT re-implement or weaken those guards —
it reuses them:

* **SSRF.** A subscription ``url`` is validated at :func:`create` through the
  EXACT SAME guard the delivery primitive uses
  (:func:`app.services.webhooks._validate_and_resolve`) BEFORE the row is ever
  persisted. A loopback / link-local / RFC-1918 / metadata / non-resolving target
  is rejected, so a customer can never register an internal URL to SSRF the
  platform. (The delivery primitive re-validates and DNS-pins again at send time —
  defense in depth.)
* **Signing.** Each subscription owns a randomly-minted HMAC signing secret that
  is returned to the caller EXACTLY ONCE (on create) and otherwise stored only as
  a Fernet blob (:mod:`app.services.crypto_tokens`). Deliveries are always signed
  with it via ``deliver_webhook(secret=...)``: Standard Webhooks ``webhook-id`` /
  ``webhook-timestamp`` / ``webhook-signature`` (``webhook-id`` = the event id,
  re-signed with a fresh timestamp per attempt) plus the deprecated body-only
  ``X-Menivor-Signature``.
* **Idempotency.** :func:`dispatch` records one :class:`WebhookDelivery` per
  ``(subscription, event_id)`` (UNIQUE) so a replayed event never double-delivers.
  The rows are committed (outbox-style) BEFORE the HTTP attempt — never across
  open network I/O — and the ``event_id`` is embedded in the signed body so the
  RECEIVER can dedup on it (delivery is at-least-once, so receivers must).
* **Retry.** :func:`retry_pending` re-attempts ``pending`` deliveries with capped
  exponential backoff and marks them ``dead`` once the attempt budget is spent. The
  Celery beat entry ``menivor-webhook-retry`` (``app.workers.tasks_webhooks``)
  runs it every minute, so a failed first attempt is always followed up.
* **No workspace needed.** :func:`ensure_personal_workspace` gives a user who
  belongs to no workspace a personal one, so any signed-in user can subscribe
  (``POST /me/webhooks``).

Tenant isolation: every read/write is scoped by ``workspace_id`` at the repository
boundary, so workspace *B* can never see or deliver workspace *A*'s subscriptions.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db.models import WebhookDelivery, WebhookSubscription
from app.models.db.repositories import (
    WebhookDeliveryRepository,
    WebhookSubscriptionRepository,
)
from app.services import audit, crypto_tokens, webhooks

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
#: Bytes of entropy in a minted signing secret (URL-safe base64 -> ~43 chars).
_SECRET_BYTES: int = 32
#: Total delivery attempts before a delivery is marked ``dead`` (1 initial +
#: retries). Bounds the retry budget so a permanently-dead endpoint cannot be
#: retried forever.
MAX_DELIVERY_ATTEMPTS: int = 6
#: Base backoff seconds; the delay after attempt ``n`` is ``BASE * 2**(n-1)``.
RETRY_BASE_SECONDS: float = 30.0
#: Hard cap on a single backoff interval (capped exponential backoff).
RETRY_MAX_SECONDS: float = 3600.0

#: Delivery statuses. ``dead`` is terminal: the attempt budget is spent and the
#: retry worker never picks the row up again (it only scans ``pending``).
DELIVERY_PENDING: str = "pending"
DELIVERY_DELIVERED: str = "delivered"
DELIVERY_DEAD: str = "dead"

#: Name of the workspace minted for a user who belongs to none.
PERSONAL_WORKSPACE_NAME: str = "Personal"

#: Audit action verbs (stable dotted strings).
_ACTION_CREATE: str = "webhook_subscription.created"
_ACTION_REVOKE: str = "webhook_subscription.revoked"

#: Event type carried by an owner-triggered test delivery (``POST .../test``). It
#: is intentionally NOT in the public subscribe catalog: a test targets ONE named
#: subscription directly (bypassing the event-match fan-out) so an owner can verify
#: their endpoint + signature handling on demand.
TEST_EVENT_TYPE: str = "webhook.test"


class WebhookSubscriptionError(ValueError):
    """Raised when a subscription cannot be created (e.g. SSRF-blocked URL)."""


# --------------------------------------------------------------------------- #
# SSRF guard reuse
# --------------------------------------------------------------------------- #
def _validate_url_or_raise(url: str) -> None:
    """Validate ``url`` through the SHARED delivery SSRF guard or raise.

    Delegates to :func:`app.services.webhooks._validate_and_resolve` — the exact
    guard :func:`~app.services.webhooks.deliver_webhook` applies at send time — so
    the subscription URL is held to the SAME policy (scheme must be http/https;
    loopback / link-local / private / reserved / metadata / non-resolving hosts
    are refused). Raises :class:`WebhookSubscriptionError` on rejection.
    """
    error, _pinned_ip = webhooks._validate_and_resolve(url)
    if error is not None:
        raise WebhookSubscriptionError(f"refusing to subscribe URL: {error}")


# --------------------------------------------------------------------------- #
# Backoff
# --------------------------------------------------------------------------- #
def _backoff_seconds(attempts: int) -> float:
    """Return the capped exponential backoff after ``attempts`` tries.

    ``RETRY_BASE_SECONDS * 2**(attempts-1)`` clamped to ``RETRY_MAX_SECONDS`` (and
    floored at the base). ``attempts <= 0`` yields the base delay.
    """
    n = max(1, int(attempts))
    delay = RETRY_BASE_SECONDS * (2 ** (n - 1))
    return float(min(delay, RETRY_MAX_SECONDS))


# --------------------------------------------------------------------------- #
# Personal workspace (a user with no workspace can still subscribe)
# --------------------------------------------------------------------------- #
def ensure_personal_workspace(session: Session, user_id: str) -> str:
    """Return a workspace ``user_id`` owns, creating a personal one if needed.

    Reuses the oldest workspace the user OWNS (role ``owner``). A user who owns
    none (no workspace at all, or only invited as a member) gets a new
    ``Personal`` workspace with themselves as owner, so the subscription is
    always managed by its creator. The user row is locked first so two racing
    calls do not mint two personal workspaces.
    """
    from app.models.db.models import User, Workspace, WorkspaceMember
    from app.models.db.repositories import WorkspaceRepository

    uid = (user_id or "").strip()
    if not uid:
        raise WebhookSubscriptionError("user_id must be a non-empty string")

    try:
        session.execute(select(User.id).where(User.id == uid).with_for_update())
    except Exception:  # noqa: BLE001 - SQLite has no row locks; the lookup still runs
        pass

    owned = session.execute(
        select(Workspace.id)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == uid, WorkspaceMember.role == "owner")
        .order_by(Workspace.created_at.asc(), Workspace.id.asc())
        .limit(1)
    ).scalar()
    if owned:
        return str(owned)
    workspace = WorkspaceRepository(session).create_workspace(
        PERSONAL_WORKSPACE_NAME, uid
    )
    logger.info(f"created personal workspace {workspace.id} for webhook user {uid}")
    return str(workspace.id)


def create_for_user(
    session: Session,
    user_id: str,
    url: str,
    event_types: list[str],
) -> tuple[WebhookSubscription, str]:
    """Create a subscription in the user's own workspace (minted if missing).

    The URL and event types are validated BEFORE a personal workspace is ever
    created, so a rejected request leaves no empty workspace behind.
    """
    if not [e for e in (event_types or []) if str(e or "").strip()]:
        raise WebhookSubscriptionError("at least one event_type is required")
    _validate_url_or_raise(url)
    workspace_id = ensure_personal_workspace(session, user_id)
    return create(session, workspace_id, url, event_types, actor_user_id=user_id)


# --------------------------------------------------------------------------- #
# CRUD (tenant-scoped)
# --------------------------------------------------------------------------- #
def create(
    session: Session,
    workspace_id: str,
    url: str,
    event_types: list[str],
    *,
    actor_user_id: str | None = None,
) -> tuple[WebhookSubscription, str]:
    """Create a subscription and return ``(subscription, plaintext_secret)``.

    The signing secret is minted here, returned to the caller EXACTLY ONCE, and
    persisted only Fernet-encrypted — it is never returned again by :func:`list_`
    / :func:`get`. The ``url`` is validated through the shared SSRF guard BEFORE
    anything is persisted, so an internal/private target never even creates a row.
    When ``actor_user_id`` is supplied, an audit row is appended (create).

    Raises :class:`WebhookSubscriptionError` on a blank/invalid/SSRF-blocked URL
    or when no ``event_types`` are given.
    """
    ws = (workspace_id or "").strip()
    if not ws:
        raise WebhookSubscriptionError("workspace_id must be a non-empty string")

    normalized_events = [
        str(e or "").strip() for e in (event_types or []) if str(e or "").strip()
    ]
    if not normalized_events:
        raise WebhookSubscriptionError("at least one event_type is required")

    # SSRF: validate through the SAME guard deliver_webhook uses — before persist.
    _validate_url_or_raise(url)

    # Mint the signing secret, return once, store encrypted.
    plaintext_secret = secrets.token_urlsafe(_SECRET_BYTES)
    secret_enc = crypto_tokens.encrypt(plaintext_secret)

    subscription = WebhookSubscriptionRepository(session).create(
        workspace_id=ws,
        url=url.strip(),
        event_types=normalized_events,
        secret_enc=secret_enc,
        enabled=True,
    )

    if actor_user_id:
        audit.record(
            session,
            actor_user_id=actor_user_id,
            action=_ACTION_CREATE,
            workspace_id=ws,
            target_type="webhook_subscription",
            target_id=subscription.id,
            metadata={"event_types": normalized_events},
        )

    return subscription, plaintext_secret


def list_(
    session: Session, workspace_id: str, limit: int = 100, offset: int = 0
) -> list[WebhookSubscription]:
    """Return a workspace's subscriptions (tenant-scoped, newest first).

    The rows carry ``secret_enc`` (the encrypted blob) — callers/serializers MUST
    NOT expose it; the plaintext signing secret is only ever available at create.
    """
    return WebhookSubscriptionRepository(session).list_for_workspace(
        workspace_id, limit=limit, offset=offset
    )


def get(
    session: Session, workspace_id: str, subscription_id: str
) -> WebhookSubscription | None:
    """Return one tenant-owned subscription, or ``None`` when foreign/missing."""
    return WebhookSubscriptionRepository(session).get_owned(
        subscription_id, workspace_id
    )


def revoke(
    session: Session,
    workspace_id: str,
    subscription_id: str,
    *,
    actor_user_id: str | None = None,
) -> WebhookSubscription | None:
    """Soft-disable a tenant-owned subscription; return it (``None`` if foreign).

    Tenant-scoped: a subscription belonging to another workspace is never touched.
    When ``actor_user_id`` is supplied and a row was revoked, an audit row is
    appended (revoke).
    """
    row = WebhookSubscriptionRepository(session).revoke(
        subscription_id, workspace_id
    )
    if row is not None and actor_user_id:
        audit.record(
            session,
            actor_user_id=actor_user_id,
            action=_ACTION_REVOKE,
            workspace_id=(workspace_id or "").strip(),
            target_type="webhook_subscription",
            target_id=row.id,
        )
    return row


# --------------------------------------------------------------------------- #
# Dispatch + delivery
# --------------------------------------------------------------------------- #
def _attempt_delivery(
    session: Session,
    subscription: WebhookSubscription,
    delivery: WebhookDelivery,
    *,
    now: datetime | None = None,
) -> WebhookDelivery:
    """Make ONE signed delivery attempt and persist the updated retry state.

    Decrypts the subscription's signing secret and hands the body to the EXISTING
    :func:`app.services.webhooks.deliver_webhook` (which re-validates + DNS-pins
    the URL and HMAC-signs the payload). The delivery row is advanced via
    :meth:`WebhookDeliveryRepository.record_attempt`: ``delivered`` on a 2xx,
    ``dead`` once the attempt budget is exhausted, else left ``pending``.
    """
    attempted_at = now or datetime.now(timezone.utc)
    repo = WebhookDeliveryRepository(session)

    try:
        secret = crypto_tokens.decrypt(subscription.secret_enc)
    except crypto_tokens.TokenCryptoError as exc:
        # Cannot sign without the secret — count the attempt and let backoff/retry
        # (or exhaustion) handle it rather than raising into the caller.
        logger.warning(
            f"webhook delivery {delivery.id}: signing secret unavailable ({exc})"
        )
        exhausted = int(delivery.attempts or 0) + 1 >= MAX_DELIVERY_ATTEMPTS
        row = repo.record_attempt(
            delivery,
            delivered=False,
            response_code=None,
            attempted_at=attempted_at,
            exhausted=exhausted,
        )
        return _mark_dead_if_exhausted(session, row, exhausted)

    # The stored payload always carries ``event_id`` (dispatch/send_test embed
    # it), and deliver_webhook uses it as the ``webhook-id``: the same id on every
    # attempt, the retry worker's included; only webhook-timestamp and the
    # signature change per attempt.
    result = webhooks.deliver_webhook(
        subscription.url, dict(delivery.payload or {}), secret=secret
    )
    delivered = bool(result.get("delivered"))
    status = result.get("status")
    response_code = int(status) if isinstance(status, int) else None
    exhausted = (not delivered) and (
        int(delivery.attempts or 0) + 1 >= MAX_DELIVERY_ATTEMPTS
    )
    row = repo.record_attempt(
        delivery,
        delivered=delivered,
        response_code=response_code,
        attempted_at=attempted_at,
        exhausted=exhausted,
    )
    return _mark_dead_if_exhausted(session, row, exhausted)


def _mark_dead_if_exhausted(
    session: Session, delivery: WebhookDelivery, exhausted: bool
) -> WebhookDelivery:
    """Move an exhausted delivery to the terminal ``dead`` status."""
    if exhausted and delivery.status != DELIVERY_DELIVERED:
        delivery.status = DELIVERY_DEAD
        session.flush()
        logger.warning(
            f"webhook delivery {delivery.id} is dead after {delivery.attempts} attempts"
        )
    return delivery


def dispatch(
    session: Session,
    workspace_id: str,
    event_type: str,
    payload: dict[str, Any],
    *,
    event_id: str | None = None,
    now: datetime | None = None,
) -> list[WebhookDelivery]:
    """Fan an event out to every enabled matching subscription (idempotently).

    For each ENABLED subscription in ``workspace_id`` whose ``event_types`` include
    ``event_type``, a :class:`WebhookDelivery` is created idempotently on
    ``event_id`` (UNIQUE per ``(subscription, event_id)``) and, when NEWLY created,
    an immediate first signed delivery attempt is made via the existing
    :func:`~app.services.webhooks.deliver_webhook`. A duplicate ``event_id`` for a
    subscription resolves to the existing delivery and is NOT re-delivered.

    ``event_id`` defaults to ``payload["event_id"]`` when present, else a fresh
    uuid — so callers can pass a stable per-event id to get idempotency. The
    resolved id is also embedded into the delivered body as ``payload["event_id"]``
    (covered by the HMAC signature), giving the RECEIVER a stable, signed key to
    dedup on: because delivery is at-least-once (the retry worker re-POSTs the same
    row on any non-2xx or after a network timeout the receiver may have processed),
    receivers MUST dedup on ``event_id`` to preserve the at-most-once guarantee.

    Delivery uses an OUTBOX discipline: the pending rows are committed FIRST and the
    HTTP attempts are made only afterwards, out of band — the DB transaction is
    never held open across network I/O, and a rollback/crash can never lose a row
    after the receiver already accepted the signed POST (which would let a later
    re-dispatch deliver a SECOND time). Anything not delivered on this pass is the
    retry worker's durable backstop.

    Returns the list of :class:`WebhookDelivery` rows (created or pre-existing)
    touched. Never raises for a single subscription's delivery failure — failures
    are recorded on the delivery row for the retry worker.
    """
    ws = (workspace_id or "").strip()
    etype = (event_type or "").strip()
    if not ws or not etype:
        return []

    eid = (event_id or "").strip() or str(
        (payload or {}).get("event_id") or ""
    ).strip()
    if not eid:
        eid = secrets.token_hex(16)

    sub_repo = WebhookSubscriptionRepository(session)
    del_repo = WebhookDeliveryRepository(session)
    subscriptions = sub_repo.list_enabled_for_event(ws, etype)

    # Embed the resolved event id into the delivered body so the receiver gets a
    # stable, HMAC-signed key to dedup on (the signature already covers the body).
    delivery_payload = dict(payload or {})
    delivery_payload["event_id"] = eid

    # Phase 1 — OUTBOX write: create the idempotent delivery rows ONLY. No network
    # I/O happens here, so the DB transaction is never held open across an HTTP
    # call (nor does a racing dispatch block on the UNIQUE insert behind a send).
    deliveries: list[WebhookDelivery] = []
    pending_new: list[tuple[WebhookSubscription, WebhookDelivery]] = []
    for subscription in subscriptions:
        delivery, created = del_repo.create_idempotent(
            subscription_id=subscription.id,
            event_type=etype,
            event_id=eid,
            payload=delivery_payload,
        )
        deliveries.append(delivery)
        if created:
            pending_new.append((subscription, delivery))

    # Commit the outbox rows BEFORE any delivery attempt: a rollback/crash after
    # the receiver accepted the signed POST can then never lose the row (which
    # would let a re-dispatch deliver the event a SECOND time). The retry worker
    # is the durable backstop for whatever isn't delivered on the pass below.
    if pending_new:
        session.commit()

    # Phase 2 — SEND out of band: one attempt per newly-created row. Failures are
    # recorded on the row for the retry worker; one bad subscription never fails
    # the others. ``_attempt_delivery`` mutates the row in place, so the objects
    # already collected in ``deliveries`` reflect the updated status.
    for subscription, delivery in pending_new:
        try:
            _attempt_delivery(session, subscription, delivery, now=now)
        except Exception as exc:  # noqa: BLE001 - one bad sub never fails others
            logger.warning(
                f"webhook dispatch: delivery {delivery.id} attempt errored "
                f"(non-fatal): {exc}"
            )

    return deliveries


def send_test(
    session: Session,
    workspace_id: str,
    subscription_id: str,
    *,
    now: datetime | None = None,
) -> WebhookDelivery | None:
    """Send a signed TEST event to ONE tenant-owned subscription; return its delivery.

    Tenant-scoped: the subscription is resolved via
    :meth:`WebhookSubscriptionRepository.get_owned`, so a caller can never test
    another tenant's subscription (a foreign/missing id returns ``None`` — the
    controller maps that to ``404``). A :class:`WebhookDelivery` is recorded
    (so the test shows up in the deliveries view) and an immediate signed attempt is
    made via the EXISTING :func:`app.services.webhooks.deliver_webhook` primitive
    (which re-validates + DNS-pins the URL and HMAC-signs the body). Unlike
    :func:`dispatch`, this targets the named subscription directly and does not
    require it to be subscribed to :data:`TEST_EVENT_TYPE`.
    """
    ws = (workspace_id or "").strip()
    subscription = WebhookSubscriptionRepository(session).get_owned(
        subscription_id, ws
    )
    if subscription is None:
        return None

    at = now or datetime.now(timezone.utc)
    event_id = f"{TEST_EVENT_TYPE}:{secrets.token_hex(16)}"
    payload = {
        "event_type": TEST_EVENT_TYPE,
        "event_id": event_id,
        "workspace_id": ws,
        "subscription_id": subscription.id,
        "message": "This is a test event from ReelForge.",
        "created_at": at.isoformat(),
    }
    delivery, created = WebhookDeliveryRepository(session).create_idempotent(
        subscription_id=subscription.id,
        event_type=TEST_EVENT_TYPE,
        event_id=event_id,
        payload=payload,
    )
    if created:
        try:
            delivery = _attempt_delivery(session, subscription, delivery, now=at)
        except Exception as exc:  # noqa: BLE001 - record the attempt, never raise
            logger.warning(
                f"webhook test: delivery {delivery.id} attempt errored "
                f"(non-fatal): {exc}"
            )
    return delivery


def list_deliveries(
    session: Session,
    workspace_id: str,
    subscription_id: str,
    *,
    limit: int = 50,
) -> list[WebhookDelivery] | None:
    """Return a tenant-owned subscription's recent deliveries (newest first).

    Tenant-scoped: ownership is verified via
    :meth:`WebhookSubscriptionRepository.get_owned` FIRST, so a caller can never
    read another tenant's deliveries (a foreign/missing subscription id returns
    ``None`` — the controller maps that to ``404``). Returns at most ``limit``
    deliveries ordered by ``created_at`` descending.
    """
    ws = (workspace_id or "").strip()
    subscription = WebhookSubscriptionRepository(session).get_owned(
        subscription_id, ws
    )
    if subscription is None:
        return None

    stmt = (
        select(WebhookDelivery)
        .where(WebhookDelivery.subscription_id == subscription.id)
        .order_by(
            WebhookDelivery.created_at.desc(),
            WebhookDelivery.id.desc(),
        )
        .limit(max(1, int(limit)))
    )
    return list(session.execute(stmt).scalars().all())


def retry_pending(
    session: Session,
    *,
    limit: int = 100,
    now: datetime | None = None,
) -> list[WebhookDelivery]:
    """Retry DUE ``pending`` deliveries with capped exponential backoff.

    Celery-beat style: call periodically. A pending delivery is DUE when
    ``now >= last_attempt_at + backoff(attempts)`` (a never-attempted delivery is
    always due). Each due delivery gets ONE more signed attempt via the existing
    delivery primitive; on a 2xx it becomes ``delivered``, once ``attempts``
    reaches :data:`MAX_DELIVERY_ATTEMPTS` it becomes ``dead``, otherwise it stays
    ``pending`` for a later, longer-backed-off retry. Returns the deliveries
    attempted this pass.
    """
    at = now or datetime.now(timezone.utc)
    del_repo = WebhookDeliveryRepository(session)
    sub_repo = WebhookSubscriptionRepository(session)

    attempted: list[WebhookDelivery] = []
    for delivery in del_repo.list_pending(limit=limit):
        if not _is_due(delivery, at):
            continue
        subscription = sub_repo.get_by_id(delivery.subscription_id)
        if subscription is None:
            continue
        try:
            attempted.append(
                _attempt_delivery(session, subscription, delivery, now=at)
            )
        except Exception as exc:  # noqa: BLE001 - one bad delivery never blocks others
            logger.warning(
                f"webhook retry: delivery {delivery.id} attempt errored "
                f"(non-fatal): {exc}"
            )
    return attempted


def _is_due(delivery: WebhookDelivery, now: datetime) -> bool:
    """Return whether a pending ``delivery`` is due for another attempt at ``now``."""
    last = delivery.last_attempt_at
    if last is None:
        return True
    # Normalize naive timestamps (SQLite) to UTC for a safe comparison.
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    ref = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    return ref >= last + timedelta(seconds=_backoff_seconds(delivery.attempts))


__all__ = [
    "DELIVERY_DEAD",
    "DELIVERY_DELIVERED",
    "DELIVERY_PENDING",
    "MAX_DELIVERY_ATTEMPTS",
    "PERSONAL_WORKSPACE_NAME",
    "RETRY_BASE_SECONDS",
    "RETRY_MAX_SECONDS",
    "TEST_EVENT_TYPE",
    "WebhookSubscriptionError",
    "create",
    "create_for_user",
    "dispatch",
    "ensure_personal_workspace",
    "get",
    "list_",
    "list_deliveries",
    "retry_pending",
    "revoke",
    "send_test",
]
