"""Unit tests for the customer webhook SUBSCRIPTIONS layer (Enterprise API, Epic 4).

Runs against an in-memory SQLite DB built from the live ORM metadata. Covered
behaviour (all built ON TOP of the existing HMAC-signed, SSRF-guarded
``app.services.webhooks.deliver_webhook`` primitive — never weakening it):

* **SSRF (reuses the delivery guard).** Creating a subscription to the cloud
  metadata endpoint (``http://169.254.169.254``), ``http://localhost`` or a
  private RFC-1918 host (``http://10.0.0.1``) is REJECTED before any row is
  persisted; a public https target is accepted.
* **Signing secret hygiene.** The secret is returned EXACTLY ONCE on create,
  stored only Fernet-encrypted (never plaintext), and never surfaced by ``list_``.
* **Idempotent dispatch.** ``dispatch`` creates exactly one ``WebhookDelivery``
  per ``(subscription, event_id)`` and signs+delivers via the existing primitive;
  a duplicate ``event_id`` does NOT double-deliver.
* **Retry backoff.** ``retry_pending`` re-attempts pending deliveries with capped
  exponential backoff and caps ``attempts`` at ``MAX_DELIVERY_ATTEMPTS`` before
  marking a permanently-failing delivery ``dead`` (MN8).
* **Tenant isolation.** Workspace *B* can neither see nor deliver workspace *A*'s
  subscriptions.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.base import Base
from app.models.db.models import User, Workspace
from app.services import crypto_tokens, webhook_subscriptions, webhooks


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )


@contextmanager
def _session(factory):
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _make_user(session, email: str) -> str:
    user = User(email=email, credits=0)
    session.add(user)
    session.flush()
    return user.id


def _make_workspace(session, owner_id: str, name: str = "Tenant") -> str:
    ws = Workspace(owner_id=owner_id, name=name)
    session.add(ws)
    session.flush()
    return ws.id


@pytest.fixture(autouse=True)
def _token_key(monkeypatch):
    """Ensure a Fernet key is configured so secrets can be encrypted."""
    monkeypatch.setenv("SOCIAL_TOKEN_KEY", "test-webhook-signing-key")


_PUBLIC_URL = "https://93.184.216.34/hook"  # public IP literal — no DNS needed


def _capture_deliveries(monkeypatch, *, delivered=True, status=200):
    """Monkeypatch the SHARED delivery primitive; capture its calls."""
    calls: list[dict] = []

    def _fake_deliver(url, payload, secret=None, timeout_s=10.0):  # noqa: ANN001
        calls.append({"url": url, "payload": payload, "secret": secret})
        if delivered:
            return {"delivered": True, "status": status}
        return {"delivered": False, "status": status, "error": "boom"}

    monkeypatch.setattr(webhooks, "deliver_webhook", _fake_deliver)
    return calls


# --------------------------------------------------------------------------- #
# SSRF — the subscription URL passes the SAME guard as deliver_webhook
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "bad_url",
    [
        "http://169.254.169.254/latest/meta-data",  # cloud metadata (link-local)
        "http://localhost/hook",  # loopback hostname
        "http://10.0.0.1/hook",  # private RFC-1918
        "http://127.0.0.1:8080/hook",  # loopback literal
        "ftp://example.com/hook",  # unsupported scheme
    ],
)
def test_create_rejects_ssrf_targets(session_factory, bad_url):
    with _session(session_factory) as s:
        owner = _make_user(s, "a@example.com")
        ws = _make_workspace(s, owner)
        with pytest.raises(webhook_subscriptions.WebhookSubscriptionError):
            webhook_subscriptions.create(s, ws, bad_url, ["job.completed"])
        # Nothing was persisted.
        assert webhook_subscriptions.list_(s, ws) == []


def test_create_accepts_public_https(session_factory):
    with _session(session_factory) as s:
        owner = _make_user(s, "a@example.com")
        ws = _make_workspace(s, owner)
        sub, secret = webhook_subscriptions.create(
            s, ws, _PUBLIC_URL, ["job.completed"]
        )
        assert sub.id
        assert sub.url == _PUBLIC_URL
        assert sub.enabled is True
        assert secret  # returned once


def test_create_reuses_webhooks_ssrf_guard(session_factory, monkeypatch):
    """The service must delegate URL validation to the delivery primitive's guard."""
    seen: list[str] = []
    real = webhooks._validate_and_resolve

    def _spy(url):  # noqa: ANN001
        seen.append(url)
        return real(url)

    monkeypatch.setattr(webhooks, "_validate_and_resolve", _spy)
    with _session(session_factory) as s:
        owner = _make_user(s, "a@example.com")
        ws = _make_workspace(s, owner)
        webhook_subscriptions.create(s, ws, _PUBLIC_URL, ["job.completed"])
    assert _PUBLIC_URL in seen


# --------------------------------------------------------------------------- #
# Signing secret — shown once, stored encrypted, never listed
# --------------------------------------------------------------------------- #
def test_secret_stored_encrypted_not_plaintext(session_factory):
    with _session(session_factory) as s:
        owner = _make_user(s, "a@example.com")
        ws = _make_workspace(s, owner)
        sub, secret = webhook_subscriptions.create(
            s, ws, _PUBLIC_URL, ["job.completed"]
        )
        # The stored blob is NOT the plaintext secret ...
        assert sub.secret_enc != secret
        assert secret not in sub.secret_enc
        # ... but decrypts back to it (so deliveries can be signed).
        assert crypto_tokens.decrypt(sub.secret_enc) == secret


def test_list_never_returns_plaintext_secret(session_factory):
    with _session(session_factory) as s:
        owner = _make_user(s, "a@example.com")
        ws = _make_workspace(s, owner)
        _sub, secret = webhook_subscriptions.create(
            s, ws, _PUBLIC_URL, ["job.completed"]
        )
        rows = webhook_subscriptions.list_(s, ws)
        assert len(rows) == 1
        # No listed row exposes the plaintext secret anywhere.
        assert secret not in (rows[0].secret_enc or "")


# --------------------------------------------------------------------------- #
# Dispatch — one delivery per (sub, event); idempotent on event_id
# --------------------------------------------------------------------------- #
def test_dispatch_delivers_signed_once_per_event(session_factory, monkeypatch):
    calls = _capture_deliveries(monkeypatch)
    with _session(session_factory) as s:
        owner = _make_user(s, "a@example.com")
        ws = _make_workspace(s, owner)
        _sub, secret = webhook_subscriptions.create(
            s, ws, _PUBLIC_URL, ["job.completed"]
        )

        deliveries = webhook_subscriptions.dispatch(
            s, ws, "job.completed", {"job_id": "j1"}, event_id="evt-1"
        )
        assert len(deliveries) == 1
        assert deliveries[0].status == "delivered"
        assert deliveries[0].attempts == 1
        # Delivered via the SHARED primitive, signed with the subscription secret.
        assert len(calls) == 1
        assert calls[0]["url"] == _PUBLIC_URL
        assert calls[0]["secret"] == secret


def test_dispatch_is_idempotent_on_event_id(session_factory, monkeypatch):
    calls = _capture_deliveries(monkeypatch)
    with _session(session_factory) as s:
        owner = _make_user(s, "a@example.com")
        ws = _make_workspace(s, owner)
        webhook_subscriptions.create(s, ws, _PUBLIC_URL, ["job.completed"])

        first = webhook_subscriptions.dispatch(
            s, ws, "job.completed", {"n": 1}, event_id="evt-dup"
        )
        second = webhook_subscriptions.dispatch(
            s, ws, "job.completed", {"n": 2}, event_id="evt-dup"
        )
        # Same delivery row resolved; NOT re-delivered.
        assert first[0].id == second[0].id
        assert len(calls) == 1


def test_dispatch_skips_disabled_and_non_matching(session_factory, monkeypatch):
    calls = _capture_deliveries(monkeypatch)
    with _session(session_factory) as s:
        owner = _make_user(s, "a@example.com")
        ws = _make_workspace(s, owner)
        # Subscribed to a different event -> no match.
        webhook_subscriptions.create(s, ws, _PUBLIC_URL, ["publish.succeeded"])
        # Enabled+matching but then revoked -> skipped.
        sub2, _ = webhook_subscriptions.create(
            s, ws, _PUBLIC_URL, ["job.completed"]
        )
        webhook_subscriptions.revoke(s, ws, sub2.id)

        deliveries = webhook_subscriptions.dispatch(
            s, ws, "job.completed", {"job_id": "j"}, event_id="e"
        )
        assert deliveries == []
        assert calls == []


# --------------------------------------------------------------------------- #
# Retry — capped exponential backoff, attempts bounded, then dead
# --------------------------------------------------------------------------- #
def test_backoff_is_capped_and_monotonic():
    b1 = webhook_subscriptions._backoff_seconds(1)
    b2 = webhook_subscriptions._backoff_seconds(2)
    assert b1 == webhook_subscriptions.RETRY_BASE_SECONDS
    assert b2 > b1
    # Grows exponentially but is hard-capped.
    big = webhook_subscriptions._backoff_seconds(100)
    assert big == webhook_subscriptions.RETRY_MAX_SECONDS


def test_retry_caps_attempts_then_marks_dead(session_factory, monkeypatch):
    # Every delivery attempt fails -> stays pending until the budget is spent.
    _capture_deliveries(monkeypatch, delivered=False, status=500)
    with _session(session_factory) as s:
        owner = _make_user(s, "a@example.com")
        ws = _make_workspace(s, owner)
        webhook_subscriptions.create(s, ws, _PUBLIC_URL, ["job.completed"])

        # First attempt (via dispatch) fails -> pending, attempts == 1.
        deliveries = webhook_subscriptions.dispatch(
            s, ws, "job.completed", {"n": 1}, event_id="retry-me"
        )
        delivery = deliveries[0]
        assert delivery.status == "pending"
        assert delivery.attempts == 1

        # Drive retries far into the future so every pending delivery is DUE.
        now = datetime.now(timezone.utc)
        for i in range(1, webhook_subscriptions.MAX_DELIVERY_ATTEMPTS + 5):
            future = now + timedelta(seconds=webhook_subscriptions.RETRY_MAX_SECONDS * i)
            webhook_subscriptions.retry_pending(s, now=future)

        s.refresh(delivery)
        # Attempts never exceed the budget, and the delivery is finally dead.
        assert delivery.attempts == webhook_subscriptions.MAX_DELIVERY_ATTEMPTS
        assert delivery.status == webhook_subscriptions.DELIVERY_DEAD


def test_retry_respects_backoff_not_yet_due(session_factory, monkeypatch):
    _capture_deliveries(monkeypatch, delivered=False, status=500)
    with _session(session_factory) as s:
        owner = _make_user(s, "a@example.com")
        ws = _make_workspace(s, owner)
        webhook_subscriptions.create(s, ws, _PUBLIC_URL, ["job.completed"])
        d = webhook_subscriptions.dispatch(
            s, ws, "job.completed", {"n": 1}, event_id="soon"
        )[0]
        assert d.attempts == 1
        # A retry an instant later is NOT due (backoff not elapsed).
        attempted = webhook_subscriptions.retry_pending(
            s, now=d.last_attempt_at + timedelta(seconds=1)
        )
        assert attempted == []
        s.refresh(d)
        assert d.attempts == 1


# --------------------------------------------------------------------------- #
# Tenant isolation — B cannot see or deliver A's subscriptions
# --------------------------------------------------------------------------- #
def test_tenant_isolation_list_and_get(session_factory):
    with _session(session_factory) as s:
        owner = _make_user(s, "a@example.com")
        ws_a = _make_workspace(s, owner, "A")
        ws_b = _make_workspace(s, owner, "B")
        sub_a, _ = webhook_subscriptions.create(
            s, ws_a, _PUBLIC_URL, ["job.completed"]
        )

        # B sees nothing of A's, and cannot get/revoke A's subscription.
        assert webhook_subscriptions.list_(s, ws_b) == []
        assert webhook_subscriptions.get(s, ws_b, sub_a.id) is None
        assert webhook_subscriptions.revoke(s, ws_b, sub_a.id) is None
        # A still sees its own, un-revoked.
        assert [r.id for r in webhook_subscriptions.list_(s, ws_a)] == [sub_a.id]
        assert webhook_subscriptions.get(s, ws_a, sub_a.id).enabled is True


def test_tenant_isolation_dispatch(session_factory, monkeypatch):
    calls = _capture_deliveries(monkeypatch)
    with _session(session_factory) as s:
        owner = _make_user(s, "a@example.com")
        ws_a = _make_workspace(s, owner, "A")
        ws_b = _make_workspace(s, owner, "B")
        webhook_subscriptions.create(s, ws_a, _PUBLIC_URL, ["job.completed"])

        # Dispatching for B never delivers to A's subscription.
        assert (
            webhook_subscriptions.dispatch(
                s, ws_b, "job.completed", {"x": 1}, event_id="e"
            )
            == []
        )
        assert calls == []


# --------------------------------------------------------------------------- #
# Audit — create/revoke append audit rows when an actor is supplied
# --------------------------------------------------------------------------- #
def test_create_and_revoke_record_audit(session_factory):
    from app.models.db.repositories import AuditLogRepository

    with _session(session_factory) as s:
        actor = _make_user(s, "actor@example.com")
        ws = _make_workspace(s, actor)
        sub, _ = webhook_subscriptions.create(
            s, ws, _PUBLIC_URL, ["job.completed"], actor_user_id=actor
        )
        webhook_subscriptions.revoke(s, ws, sub.id, actor_user_id=actor)

        rows = AuditLogRepository(s).list_for_workspace(ws)
        actions = {r.action for r in rows}
        assert "webhook_subscription.created" in actions
        assert "webhook_subscription.revoked" in actions
