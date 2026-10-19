"""ReelForge billing orchestration layer.

This is the single choke point between the payment providers (Stripe / iyzico /
Creem / Polar) and the credit ledger. Responsibilities:

1. :func:`create_checkout` — validate the plan/provider and dispatch to the
   provider-specific client to open a hosted checkout.
2. :func:`fulfill_purchase` — **idempotently** grant credits for a paid event.
   The grant targets the buyer's personal balance, or — when the event carries a
   ``workspace_id`` — the workspace's shared pool
   (:meth:`CreditRepository.workspace_grant`). Idempotency is enforced two ways
   (belt and suspenders) on *both* routes:
     * fast path: Redis ``SETNX billing:evt:<provider>:<event_id>`` (TTL 30d);
       a duplicate webhook finds the key already set and grants nothing.
     * durable fallback: the ledger ``reason`` encodes the provider event
       (``purchase:<provider>:<reason_ref>``) so a second delivery is deduped
       even if Redis is unavailable or the key expired.
3. :func:`handle_stripe_webhook` / :func:`handle_creem_webhook` /
   :func:`handle_polar_webhook` / :func:`handle_iyzico_callback` — verify the
   provider payload, extract provenance, and call :func:`fulfill_purchase`.
4. :func:`grant_signup_credits` — one-time signup grant, idempotent per user.

Design rules honored here:

* **No schema change.** Provenance rides in ``CreditLedger.reason``; idempotency
  rides in Redis + the reason lookup. Nothing new is persisted structurally.
* **Secrets only from config** — read exclusively by the lazily-imported
  provider clients; this module never touches provider secrets directly.
* **Lazy imports** — provider SDKs (``stripe`` / ``iyzipay``) and the DB layer
  are imported inside functions so importing this module never fails at
  ``py_compile`` time even when those packages/clients are absent.
* Webhooks verify signatures (delegated to the client) and are safe to call on
  duplicate deliveries; the API layer returns 200 fast on the value returned.
"""

from __future__ import annotations

import hashlib
from typing import Any

from loguru import logger

from app.config import config

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STRIPE: str = "stripe"
IYZICO: str = "iyzico"
CREEM: str = "creem"
POLAR: str = "polar"
DODO: str = "dodo"
PADDLE: str = "paddle"
_SUPPORTED_PROVIDERS: tuple[str, ...] = (STRIPE, IYZICO, CREEM, POLAR, DODO, PADDLE)
# Merchant-of-record rails selected by MENIVOR_PAYMENTS_PROVIDER. When one of
# them is active only that one is offered for new checkouts (so customer money
# never routes through a store that is not the chosen one).
_MOR_PROVIDERS: tuple[str, ...] = (CREEM, DODO, PADDLE)

# Providers that can fund a workspace's SHARED credit pool (they thread the
# ``workspace_id`` through provider metadata; the webhook routes the grant to the
# pool). iyzico has no metadata channel for this, so it stays personal-only.
_WORKSPACE_CAPABLE_PROVIDERS: tuple[str, ...] = (STRIPE, CREEM, POLAR, DODO, PADDLE)

# Config keys that must be present (non-empty) for a provider to be considered
# "enabled" for the UI's provider list. Secrets are only ever read from config.
_PROVIDER_REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    STRIPE: ("secret_key",),
    IYZICO: ("api_key", "secret_key"),
    CREEM: ("api_key",),
    POLAR: ("access_token",),
    DODO: ("api_key",),
    PADDLE: ("api_key",),
}

# Provider webhook/event idempotency key namespace + TTL (30 days). The key is
# retained well beyond any realistic provider retry window so replays are caught.
_EVENT_KEY_PREFIX: str = "billing:evt"
_SIGNUP_KEY_PREFIX: str = "billing:signup"
_EVENT_TTL_SECONDS: int = 30 * 24 * 60 * 60  # 2_592_000

# CreditLedger.reason is String(80) (schema is locked; must not overflow). Long
# provider ids are hashed deterministically so idempotency-by-reason survives.
_REASON_MAX_LEN: int = 80
_SIGNUP_REASON: str = "signup"


# ---------------------------------------------------------------------------
# Small access helpers
# ---------------------------------------------------------------------------


def _read(obj: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from an object (attribute) or a mapping (key)."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _normalize_provider(provider: str) -> str:
    """Lower/strip a provider id and validate it is supported."""
    normalized = (provider or "").strip().lower()
    if normalized not in _SUPPORTED_PROVIDERS:
        raise ValueError(
            f"unsupported billing provider {provider!r}; "
            f"expected one of {list(_SUPPORTED_PROVIDERS)}"
        )
    return normalized


def _fit_reason(reason: str, provider: str, reason_ref: str) -> str:
    """Return a ``reason`` guaranteed to fit ``String(80)`` deterministically.

    Short reasons pass through unchanged so provenance stays human-readable
    (``purchase:stripe:cs_test_123``). Only when a very long provider id would
    overflow the column do we substitute a stable hash of ``reason_ref`` — still
    deterministic, so the reason-based idempotency check keeps working.
    """
    if len(reason) <= _REASON_MAX_LEN:
        return reason
    digest = hashlib.sha256((reason_ref or "").encode("utf-8")).hexdigest()[:32]
    hashed = f"purchase:{provider}:{digest}"
    return hashed[:_REASON_MAX_LEN]


# ---------------------------------------------------------------------------
# Redis (idempotency lock)
# ---------------------------------------------------------------------------

_redis_client: Any = None
_redis_initialized: bool = False


def _get_redis() -> Any:
    """Return a lazily-built plain Redis client, or ``None`` if unavailable.

    Built from the existing ``[app]`` redis keys (same source the state machine
    and Celery use). Short socket timeouts keep webhook handling fast — if Redis
    is unreachable we fall back to the durable ledger-reason dedupe rather than
    blocking the request. Never raises.
    """
    global _redis_client, _redis_initialized
    if _redis_initialized:
        return _redis_client
    _redis_initialized = True
    try:
        import redis  # lazy: optional at import/compile time

        _redis_client = redis.Redis(
            host=config.app.get("redis_host", "localhost"),
            port=int(config.app.get("redis_port", 6379)),
            db=int(config.app.get("redis_db", 0)),
            password=config.app.get("redis_password") or None,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    except Exception as exc:  # noqa: BLE001 - redis is best-effort here
        logger.warning(f"billing: Redis client unavailable, using ledger-only "
                       f"idempotency: {exc}")
        _redis_client = None
    return _redis_client


def _reserve_event(key: str, ttl_seconds: int | None) -> tuple[bool, bool]:
    """Attempt to claim an idempotency key via ``SETNX``.

    Returns ``(reserved, redis_ok)``:
        * ``reserved`` — True if we newly claimed the key (first delivery) or if
          Redis is unavailable (defer the decision to the ledger dedupe).
        * ``redis_ok`` — whether the reservation was actually recorded in Redis
          (so a failed grant can release it).
    """
    client = _get_redis()
    if client is None:
        return True, False
    try:
        created = client.set(name=key, value="1", nx=True, ex=ttl_seconds)
        return bool(created), True
    except Exception as exc:  # noqa: BLE001 - degrade to ledger dedupe
        logger.warning(f"billing: Redis SETNX failed for {key!r}, falling back "
                       f"to ledger dedupe: {exc}")
        return True, False


def _release_event(key: str) -> None:
    """Best-effort delete of an idempotency key so a failed grant can retry."""
    client = _get_redis()
    if client is None:
        return
    try:
        client.delete(key)
    except Exception as exc:  # noqa: BLE001 - best effort only
        logger.warning(f"billing: Redis DEL failed for {key!r}: {exc}")


# ---------------------------------------------------------------------------
# Ledger access (lazy DB imports)
# ---------------------------------------------------------------------------


def _ledger_has_reason(session: Any, user_id: str, reason: str) -> bool:
    """True if a ledger row with this exact ``(user_id, reason)`` already exists.

    This is the durable idempotency guarantee: ``reason`` uniquely encodes the
    provider event (or the signup grant), so a duplicate is caught even without
    Redis.
    """
    from sqlalchemy import select

    from app.models.db.models import CreditLedger

    stmt = (
        select(CreditLedger.id)
        .where(
            CreditLedger.user_id == user_id,
            CreditLedger.reason == reason,
        )
        .limit(1)
    )
    return session.execute(stmt).first() is not None


def _lock_user_row(session: Any, user_id: str) -> None:
    """Acquire the ``User`` row lock (``SELECT ... FOR UPDATE``) in ``session``.

    Taking the same lock ``CreditRepository._locked_balance`` uses — but *before*
    the ledger-reason dedupe check — makes the dedupe re-check and the subsequent
    grant run under a single lock held for the whole transaction. This closes the
    TOCTOU double-grant race on the durable fallback path (Redis unavailable):
    a concurrent duplicate delivery of the same event blocks here until the first
    grant commits, then observes the now-committed ledger row and skips the second
    grant instead of reading the inflated balance and inserting a duplicate.

    Mirrors ``_locked_balance``: only SQLite's lack of ``FOR UPDATE`` (raised as
    ``NotSupportedError``) is tolerated; any other backend error propagates.
    """
    from sqlalchemy import select
    from sqlalchemy.exc import NotSupportedError

    from app.models.db.models import User

    try:
        stmt = select(User).where(User.id == user_id).with_for_update()
        session.execute(stmt).first()
    except NotSupportedError:
        if session.get_bind().dialect.name != "sqlite":
            raise
        # SQLite (tests): no row locks — proceed without serialization.


def _current_balance(user_id: str) -> int:
    """Return the user's current credit balance in its own short session."""
    from app.models.db.base import get_session
    from app.models.db.repositories import CreditRepository

    with get_session() as session:
        return CreditRepository(session).balance(user_id)


def _idempotent_grant(
    *,
    idempotency_key: str,
    user_id: str,
    credits: int,
    reason: str,
    ttl_seconds: int | None,
) -> int:
    """Grant ``credits`` at most once for ``idempotency_key`` / ``reason``.

    Flow:
        1. ``SETNX`` the Redis key. If it was already set, this is a duplicate —
           return the current balance without granting.
        2. Otherwise open a DB session, re-check the ledger by ``reason`` (durable
           dedupe), and grant only if not already present.
        3. On any grant failure, release the Redis key so the provider's retry
           can reprocess the event.

    Returns the resulting (or already-current) balance.
    """
    if not user_id:
        raise ValueError("grant requires a non-empty user_id")
    if credits <= 0:
        raise ValueError(f"grant credits must be positive, got {credits}")

    reserved, redis_ok = _reserve_event(idempotency_key, ttl_seconds)
    if redis_ok and not reserved:
        # A concurrent/previous delivery already owns this event.
        logger.info(f"billing: duplicate event {idempotency_key!r} ignored")
        return _current_balance(user_id)

    from app.models.db.base import get_session
    from app.models.db.repositories import CreditRepository

    try:
        with get_session() as session:
            # Lock the User row FIRST so the dedupe re-check below and the grant
            # execute under one lock held to commit. Without this, two concurrent
            # duplicate deliveries (Redis down) both pass the dedupe check before
            # either commits, then both grant — a TOCTOU double-grant. With the
            # lock, the second delivery blocks until the first commits and then
            # sees its ledger row.
            _lock_user_row(session, user_id)
            if _ledger_has_reason(session, user_id, reason):
                logger.info(
                    f"billing: reason {reason!r} already credited for "
                    f"user={user_id}; skipping duplicate grant"
                )
                return CreditRepository(session).balance(user_id)

            entry = CreditRepository(session).grant(user_id, credits, reason=reason)
            logger.info(
                f"billing: granted {credits} credits to user={user_id} "
                f"reason={reason!r} balance_after={entry.balance_after}"
            )
            return int(entry.balance_after)
    except Exception as exc:
        # Release the lock so the provider's next retry can fulfill the purchase.
        if redis_ok:
            _release_event(idempotency_key)
        logger.error(
            f"billing: grant failed for user={user_id} reason={reason!r}: {exc}"
        )
        raise


# ---------------------------------------------------------------------------
# Workspace shared-pool grant (idempotent) — WF25
# ---------------------------------------------------------------------------


def _ledger_has_workspace_reason(
    session: Any, workspace_id: str, reason: str
) -> bool:
    """True if a workspace-pool row with this ``(workspace_id, reason)`` exists.

    The workspace analogue of :func:`_ledger_has_reason`: ``reason`` uniquely
    encodes the provider event, so a duplicate webhook is caught durably even
    without Redis. Keyed on ``workspace_id`` (not ``user_id``) so it matches the
    exact pool row :meth:`CreditRepository.workspace_grant` writes.
    """
    from sqlalchemy import select

    from app.models.db.models import CreditLedger

    stmt = (
        select(CreditLedger.id)
        .where(
            CreditLedger.workspace_id == workspace_id,
            CreditLedger.reason == reason,
        )
        .limit(1)
    )
    return session.execute(stmt).first() is not None


def _lock_workspace_row(session: Any, workspace_id: str) -> None:
    """Acquire the ``Workspace`` row lock (``SELECT ... FOR UPDATE``).

    The workspace analogue of :func:`_lock_user_row`: taking the same lock
    :meth:`CreditRepository._locked_workspace_balance` uses — but *before* the
    ledger-reason dedupe check — makes the dedupe re-check and the subsequent
    ``workspace_grant`` run under one lock held for the whole transaction. This
    closes the TOCTOU double-fund race on the durable fallback path (Redis
    unavailable): a concurrent duplicate delivery of the same event blocks here
    until the first grant commits, then observes the now-committed pool row and
    skips the second grant. Only SQLite's lack of ``FOR UPDATE``
    (``NotSupportedError``) is tolerated; any other backend error propagates.
    """
    from sqlalchemy import select
    from sqlalchemy.exc import NotSupportedError

    from app.models.db.models import Workspace

    try:
        stmt = select(Workspace).where(Workspace.id == workspace_id).with_for_update()
        session.execute(stmt).first()
    except NotSupportedError:
        if session.get_bind().dialect.name != "sqlite":
            raise
        # SQLite (tests): no row locks — proceed without serialization.


def _current_workspace_balance(workspace_id: str) -> int:
    """Return a workspace pool's current balance in its own short session."""
    from app.models.db.base import get_session
    from app.models.db.repositories import CreditRepository

    with get_session() as session:
        return CreditRepository(session).workspace_balance(workspace_id)


def _idempotent_workspace_grant(
    *,
    idempotency_key: str,
    workspace_id: str,
    actor_user_id: str | None,
    credits: int,
    reason: str,
    ttl_seconds: int | None,
) -> int:
    """Grant ``credits`` to a workspace pool at most once per event / reason.

    The workspace analogue of :func:`_idempotent_grant`, using the *same* two
    idempotency guards (Redis ``SETNX`` on the event id + the durable
    ledger-reason dedupe) so a replayed webhook never double-funds the shared
    pool. ``actor_user_id`` (the funding admin) is recorded on the pool ledger
    row for audit only and never touches any personal balance.

    Returns the resulting (or already-current) pool balance.
    """
    if not workspace_id:
        raise ValueError("workspace grant requires a non-empty workspace_id")
    if credits <= 0:
        raise ValueError(f"grant credits must be positive, got {credits}")

    reserved, redis_ok = _reserve_event(idempotency_key, ttl_seconds)
    if redis_ok and not reserved:
        # A concurrent/previous delivery already owns this event.
        logger.info(f"billing: duplicate event {idempotency_key!r} ignored")
        return _current_workspace_balance(workspace_id)

    from app.models.db.base import get_session
    from app.models.db.repositories import CreditRepository

    try:
        with get_session() as session:
            # Lock the Workspace row FIRST so the dedupe re-check below and the
            # grant execute under one lock held to commit (see _lock_workspace_row
            # for the TOCTOU rationale).
            _lock_workspace_row(session, workspace_id)
            if _ledger_has_workspace_reason(session, workspace_id, reason):
                logger.info(
                    f"billing: reason {reason!r} already credited to "
                    f"workspace={workspace_id}; skipping duplicate grant"
                )
                return CreditRepository(session).workspace_balance(workspace_id)

            entry = CreditRepository(session).workspace_grant(
                workspace_id,
                credits,
                reason=reason,
                actor_user_id=actor_user_id or None,
            )
            logger.info(
                f"billing: granted {credits} credits to workspace={workspace_id} "
                f"actor={actor_user_id or '-'} reason={reason!r} "
                f"balance_after={entry.balance_after}"
            )
            return int(entry.balance_after)
    except Exception as exc:
        # Release the lock so the provider's next retry can fulfill the purchase.
        if redis_ok:
            _release_event(idempotency_key)
        logger.error(
            f"billing: workspace grant failed for workspace={workspace_id} "
            f"reason={reason!r}: {exc}"
        )
        raise


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_plans() -> list[dict[str, Any]]:
    """Return the public credit-plan catalogue as JSON-safe dicts.

    The catalogue itself is owned by :mod:`app.services.billing.plans`; this
    thin wrapper exposes it through the service module (the single import the
    API controller depends on) and flattens each :class:`Plan` into a plain
    dict so it serializes cleanly through the API envelope without leaking the
    dataclass type.
    """
    from app.services.billing.plans import list_plans as _catalog_list_plans

    return [
        {
            "key": plan.key,
            "display_name": plan.display_name,
            "credits": plan.credits,
            "price_usd": plan.price_usd,
            "is_purchasable": plan.is_purchasable,
        }
        for plan in _catalog_list_plans()
    ]


def _config_section(name: str) -> dict[str, Any]:
    """Return a provider config section as a plain dict, defensively (never raises)."""
    section = getattr(config, name, None)
    if section is None:
        return {}
    try:
        return dict(section)
    except Exception:  # noqa: BLE001 - non-mapping guard
        return {}


def _provider_configured(provider: str) -> bool:
    """True if every required secret key for ``provider`` is present and non-empty.

    Secrets are read ONLY from config (never hardcoded); a provider with a missing
    key is simply not offered to the UI rather than erroring at checkout time.
    """
    section = _config_section(provider)
    required = _PROVIDER_REQUIRED_KEYS.get(provider, ())
    if not required:
        return False
    return all(str(section.get(key, "") or "").strip() for key in required)


def list_enabled_providers() -> list[str]:
    """Return the payment providers that are configured (enabled) for checkout.

    A provider is "enabled" when its required secret(s) are present in config, so
    the UI can render only the rails that will actually work. Order follows the
    canonical provider tuple so the response is stable.
    """
    from app.services.billing import payments_mode

    active = payments_mode.active_provider()
    if active == payments_mode.NONE:
        return []
    return [p for p in (active,) if _provider_configured(p)]


class PaymentsPaused(RuntimeError):
    """New checkouts are paused, or the provider is not the active one."""


def _require_active_provider(provider: str) -> None:
    from app.services.billing import payments_mode

    active = payments_mode.active_provider()
    if active == payments_mode.NONE:
        raise PaymentsPaused("Paid plans are paused while we move to a new payment partner.")
    if provider in _MOR_PROVIDERS and provider != active:
        raise PaymentsPaused(f"{provider} is not the active payment provider.")


def create_checkout(
    user_id: str,
    user_email: str = "",
    plan_key: str = "",
    provider: str = "",
    workspace_id: str | None = None,
    subscription: bool = False,
) -> dict[str, Any]:
    """Open a hosted checkout for ``plan_key`` via ``provider``.

    ``subscription=True`` opens a recurring-plan checkout (Stripe
    ``mode="subscription"``) so the provider emits the ``customer.subscription.*``
    / ``invoice.payment_succeeded`` events the subscription webhook is built
    around; the default (``False``) opens a one-time credit-pack purchase.

    Validates the plan is a real, purchasable pack and the provider is
    supported, then dispatches to the provider client (lazily imported so a
    missing SDK does not break import). Returns a normalized envelope:

        ``{"provider", "plan_key", "credits", "checkout_url", "reference",
        "workspace_id", ...}``

    When ``workspace_id`` is set (an admin buying credits for a workspace's
    shared pool), it is threaded into the Stripe session ``metadata`` so the
    webhook fulfils the purchase against the workspace pool rather than the
    actor's personal balance. Authorization (the actor must be a workspace
    admin) is enforced by the caller via
    :func:`app.services.workspaces.require_role` before this runs; the ``None``
    default keeps every personal-purchase call site unchanged.

    Args:
        user_id: The purchasing user's id (encoded into provider metadata so the
            webhook can credit the right account / pool actor).
        user_email: The purchasing user's email (optional; used by the iyzico
            buyer block and Stripe receipts).
        plan_key: ``"starter"`` | ``"pro"`` (``"free"`` is a signup grant, not
            purchasable).
        provider: ``"stripe"`` | ``"iyzico"`` | ``"creem"`` | ``"polar"``.
        workspace_id: Optional target workspace whose shared pool to fund;
            ``None``/empty means a personal purchase. Workspace-targeted
            purchases are supported on the Stripe, Creem and Polar paths.

    Raises:
        ValueError: On unknown/non-purchasable plan, bad provider, or missing
            user id.
        RuntimeError: If the provider client/SDK is unavailable.
    """
    from app.services.billing.plans import get_plan

    normalized_provider = _normalize_provider(provider)
    _require_active_provider(normalized_provider)

    plan = get_plan(plan_key)
    if plan is None:
        raise ValueError(f"unknown plan {plan_key!r}")
    if not plan.is_purchasable:
        raise ValueError(f"plan {plan.key!r} is not purchasable")

    user_id = str(user_id or "").strip()
    if not user_id:
        raise ValueError("create_checkout: user is missing an 'id'")

    normalized_workspace_id = str(workspace_id or "").strip() or None
    if normalized_workspace_id and normalized_provider not in _WORKSPACE_CAPABLE_PROVIDERS:
        # Workspace-pool funding is only wired for the metadata-carrying providers;
        # fail fast rather than silently dropping the target and crediting the
        # wrong pool.
        raise ValueError(
            "workspace credit purchases are only supported via the "
            f"{list(_WORKSPACE_CAPABLE_PROVIDERS)} providers, "
            f"not {normalized_provider!r}"
        )

    # Only primitive, JSON-safe values cross into the provider clients (the DB
    # session is already released by the caller); a plain mapping satisfies the
    # attribute/key access both clients use.
    user: dict[str, Any] = {"id": user_id, "email": user_email or ""}

    if normalized_provider == STRIPE:
        from app.services.billing import stripe_client

        # Only pass the ``subscription`` kwarg when opening a recurring checkout so
        # the one-time credit-pack call signature (and its test doubles) is
        # unchanged.
        stripe_kwargs: dict[str, Any] = {"workspace_id": normalized_workspace_id}
        if subscription:
            stripe_kwargs["subscription"] = True
        result = stripe_client.create_checkout_session(user, plan, **stripe_kwargs)
        reference = result.get("session_id", "")
        checkout_url = result.get("checkout_url", "")
    elif normalized_provider == CREEM:
        from app.services.billing import creem_client

        result = creem_client.create_checkout_session(
            user, plan, workspace_id=normalized_workspace_id
        )
        reference = result.get("session_id", "")
        checkout_url = result.get("checkout_url", "")
    elif normalized_provider == DODO:
        from app.services.billing import dodo_billing

        result = dodo_billing.open_pack_checkout(
            user, plan, workspace_id=normalized_workspace_id
        )
        reference = result.get("session_id", "")
        checkout_url = result.get("checkout_url", "")
    elif normalized_provider == PADDLE:
        from app.services.billing import paddle_client

        result = paddle_client.create_pack_checkout(
            user, plan, workspace_id=normalized_workspace_id
        )
        reference = result.get("session_id", "")
        checkout_url = result.get("checkout_url", "")
    elif normalized_provider == POLAR:
        from app.services.billing import polar_client

        result = polar_client.create_checkout_session(
            user, plan, workspace_id=normalized_workspace_id
        )
        reference = result.get("session_id", "")
        checkout_url = result.get("checkout_url", "")
    else:  # IYZICO
        iyzico_client = _import_iyzico_client()
        result = iyzico_client.create_checkout_form(user, plan)
        # Support either the stripe-style or an iyzico-native key name.
        reference = result.get("token") or result.get("conversation_id", "")
        checkout_url = (
            result.get("payment_page_url")
            or result.get("checkout_url", "")
        )

    logger.info(
        f"billing: created {normalized_provider} checkout for user={user_id} "
        f"plan={plan.key} reference={reference} "
        f"workspace={normalized_workspace_id or '-'}"
    )
    return {
        "provider": normalized_provider,
        "plan_key": plan.key,
        "credits": plan.credits,
        "checkout_url": checkout_url,
        "reference": reference,
        "workspace_id": normalized_workspace_id,
    }


def fulfill_purchase(
    provider: str,
    external_event_id: str,
    user_id: str,
    credits: int,
    reason_ref: str,
    workspace_id: str | None = None,
) -> int:
    """Idempotently grant ``credits`` for a paid provider event.

    Idempotency key: ``billing:evt:<provider>:<external_event_id>`` (Redis
    SETNX, TTL 30d). Ledger provenance: ``purchase:<provider>:<reason_ref>``.

    When ``workspace_id`` is set the grant is routed to that workspace's shared
    pool (:meth:`CreditRepository.workspace_grant`) with ``user_id`` recorded as
    the funding actor; otherwise the credits go to the user's personal balance
    (path unchanged). Both routes share the identical dual idempotency guard so a
    replayed webhook never double-funds either target.

    Args:
        provider: ``"stripe"`` | ``"iyzico"``.
        external_event_id: The provider's unique event/payment id (dedupe key).
        user_id: The user to credit (personal), or the funding admin (workspace).
        credits: Positive number of credits to grant.
        reason_ref: Provenance reference encoded into the ledger reason (e.g.
            the Stripe checkout ``session_id`` or the iyzico ``payment_id``).
        workspace_id: Optional target workspace pool; ``None``/empty grants to
            the user's personal balance.

    Returns:
        The resulting balance after fulfillment — the workspace pool balance when
        ``workspace_id`` is set, else the user's personal balance (or the current
        balance if this event was already processed).
    """
    normalized_provider = _normalize_provider(provider)
    event_id = (external_event_id or "").strip()
    if not event_id:
        raise ValueError("fulfill_purchase requires a non-empty external_event_id")

    key = f"{_EVENT_KEY_PREFIX}:{normalized_provider}:{event_id}"
    reason = _fit_reason(
        f"purchase:{normalized_provider}:{reason_ref}",
        normalized_provider,
        reason_ref or "",
    )

    normalized_workspace_id = str(workspace_id or "").strip()
    if normalized_workspace_id:
        # Fund the workspace shared pool instead of the actor's personal balance.
        balance = _idempotent_workspace_grant(
            idempotency_key=key,
            workspace_id=normalized_workspace_id,
            actor_user_id=str(user_id or "").strip() or None,
            credits=int(credits),
            reason=reason,
            ttl_seconds=_EVENT_TTL_SECONDS,
        )
    else:
        balance = _idempotent_grant(
            idempotency_key=key,
            user_id=str(user_id or "").strip(),
            credits=int(credits),
            reason=reason,
            ttl_seconds=_EVENT_TTL_SECONDS,
        )
    _rally_credits_purchased(
        user_id, normalized_provider, event_id, int(credits), normalized_workspace_id or None
    )
    return balance


def _rally_credits_purchased(
    user_id: str, provider: str, reference: str, credits: int, workspace_id: str | None
) -> None:
    """Rally ``credits_purchased`` (no-op unless RALLY_EVENTS_KEY; never raises).

    Keyed on the provider event id, so a replayed webhook is recorded once.
    """
    if not str(user_id or "").strip():
        return
    try:
        from app.integrations.rally import track_credits_purchased

        track_credits_purchased(
            str(user_id).strip(),
            provider=provider,
            reference=reference,
            credits=credits,
            workspace_id=workspace_id,
        )
    except Exception as exc:  # noqa: BLE001 - lifecycle events never fail fulfilment
        logger.debug(f"rally credits_purchased skipped: {exc}")


def _route_subscription_event(provider: str, event: Any) -> bool:
    """Apply ``event`` as a workspace SUBSCRIPTION event when it is one.

    Owners typically register ONE webhook endpoint per provider, so recurring
    workspace-plan events (and the checkout that opened them) can arrive on the
    pack endpoint. They are handed to the idempotent subscription applier and
    never treated as a one-time pack (which would double-grant). Returns True
    when the event was a subscription event (handled here).
    """
    if provider == CREEM:
        # Personal monthly plans (Creator / Pro / Agency) first: their events
        # carry ``kind=creator_plan`` or a personal-plan product id and must
        # never be treated as a workspace subscription or a one-time pack.
        from app.services.billing import creator_subscriptions

        personal = creator_subscriptions.parse_creem_event(event)
        if personal is not None:
            creator_subscriptions.apply_update(personal)
            return True

    from app.services.billing import subscription_providers

    if subscription_providers.parse_event(provider, event) is None:
        return False
    from app.services import subscriptions

    subscriptions.process_provider_event(provider, event)
    return True


def handle_stripe_webhook(payload: bytes, signature: str) -> int | None:
    """Verify a Stripe webhook and fulfill the purchase if it is a completed sale.

    Delegates signature verification + event extraction to ``stripe_client``
    (which reads ``config.stripe.webhook_secret``). Returns the new balance for
    a fulfilled ``checkout.session.completed`` event, or ``None`` for any other
    (ignored) event. Signature-verification failures propagate so the API layer
    can respond 400.

    Args:
        payload: Raw request body bytes (byte-exact — do not re-serialize).
        signature: The ``Stripe-Signature`` header value.
    """
    from app.services.billing import stripe_client

    event = stripe_client.verify_and_parse_webhook(payload, signature)
    if _route_subscription_event(STRIPE, event):
        return None

    purchase = stripe_client.extract_completed_purchase(event)
    if not purchase:
        # Verified but not a fulfillment event: ack 200, grant nothing.
        return None

    event_id = str(_read(event, "id", "") or "").strip() or purchase["session_id"]
    return fulfill_purchase(
        provider=STRIPE,
        external_event_id=event_id,
        user_id=purchase["user_id"],
        credits=int(purchase["credits"]),
        reason_ref=purchase["session_id"],
        # None for a personal purchase; a real id routes to the workspace pool.
        workspace_id=purchase.get("workspace_id"),
    )


def handle_creem_webhook(payload: bytes, signature: str) -> int | None:
    """Verify a Creem webhook and fulfill the purchase if it is a completed sale.

    Delegates HMAC-SHA256 signature verification + event extraction to
    ``creem_client`` (which reads ``config.creem.webhook_secret``). Returns the new
    balance for a fulfilled completed-checkout event, or ``None`` for any other
    (ignored) event. Signature-verification failures propagate so the API layer
    can respond 400. Fulfillment is the shared idempotent
    :func:`fulfill_purchase`, so a replayed webhook grants at most once and a
    ``workspace_id`` in the checkout metadata routes the grant to the shared pool.

    Args:
        payload: Raw request body bytes (byte-exact — do not re-serialize).
        signature: The ``creem-signature`` header value.
    """
    from app.services.billing import creem_client

    event = creem_client.verify_and_parse_webhook(payload, signature)
    if _route_subscription_event(CREEM, event):
        return None

    purchase = creem_client.extract_completed_purchase(event)
    if not purchase:
        # Verified but not a fulfillment event: ack 200, grant nothing.
        return None

    event_id = str(_read(event, "id", "") or "").strip() or purchase["session_id"]
    from app.services.billing import card_check

    if purchase.get("plan_key") == card_check.CARD_CHECK_KEY:
        # $1 card check: credit it and unlock the free signup reels.
        return card_check.fulfill(
            user_id=purchase["user_id"],
            checkout_id=purchase["session_id"],
            external_event_id=event_id,
        )
    return fulfill_purchase(
        provider=CREEM,
        external_event_id=event_id,
        user_id=purchase["user_id"],
        credits=int(purchase["credits"]),
        reason_ref=purchase["session_id"],
        # None for a personal purchase; a real id routes to the workspace pool.
        workspace_id=purchase.get("workspace_id"),
    )


class RedirectVerificationError(ValueError):
    """A Creem success redirect failed signature verification or is incomplete."""


def confirm_creem_redirect(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    """Credit a credit pack from Creem's SIGNED success redirect (no webhook).

    Creem appends ``checkout_id``/``order_id``/``product_id``/``request_id`` and a
    ``signature`` (SHA-256 salted with our Creem API key) to ``success_url``. A
    valid signature proves the checkout was paid. The buyer comes from the signed
    ``request_id`` and the credits from the signed ``product_id`` mapped onto the
    locked plan catalog (never from anything the browser could choose).

    Idempotent with the webhook path: both write the same ledger reason
    ``purchase:creem:<checkout_id>`` under the user-row lock, so a redirect
    replay, a page refresh, or a later webhook for the same checkout grants once.

    Args:
        pairs: The success-URL query as ordered ``(key, value)`` pairs.

    Returns:
        ``{"plan_key", "credits", "balance", "checkout_id", "workspace_id"}``.

    Raises:
        RedirectVerificationError: Bad/missing signature, missing fields, or a
            product that is not a one-time credit pack.
    """
    from app.services.billing import creem_client
    from app.services.billing.plans import list_plans as _catalog_plans

    if not creem_client.verify_redirect_signature(list(pairs)):
        raise RedirectVerificationError("Creem redirect signature is invalid.")
    try:
        purchase = creem_client.extract_redirect_purchase(list(pairs))
    except ValueError as exc:
        raise RedirectVerificationError(str(exc)) from exc

    from app.services.billing import card_check

    checkout_id = purchase["checkout_id"]
    if card_check.product_id() and purchase["product_id"] == card_check.product_id():
        balance = card_check.fulfill(
            user_id=purchase["user_id"],
            checkout_id=checkout_id,
            external_event_id=f"redirect:{checkout_id}",
        )
        return {
            "plan_key": card_check.CARD_CHECK_KEY,
            "credits": card_check.CARD_CHECK_CREDITS,
            "balance": int(balance),
            "checkout_id": checkout_id,
            "workspace_id": None,
            "unlocked": True,
        }

    from app.services.billing import creator_plans

    personal = creator_plans.plan_for_product(purchase["product_id"], "creem")
    if personal is not None:
        # A personal monthly plan: activate it and grant the first period's
        # included reels (idempotent with the subscription webhooks).
        from app.services.billing import creator_plan_actions

        return creator_plan_actions.confirm_redirect(
            {**purchase, "customer_id": dict(pairs).get("customer_id", "")},
            personal[0],
            personal[1],
        )

    plan = next(
        (
            p
            for p in _catalog_plans(purchasable_only=True)
            if p.creem_product_id and p.creem_product_id == purchase["product_id"]
        ),
        None,
    )
    if plan is None:
        raise RedirectVerificationError(
            "This checkout is not a Menivor credit pack on this server."
        )

    balance = fulfill_purchase(
        provider=CREEM,
        # Distinct Redis key from the webhook's event id; the durable ledger
        # reason (shared with the webhook) is what prevents a double grant.
        external_event_id=f"redirect:{checkout_id}",
        user_id=purchase["user_id"],
        credits=int(plan.credits),
        reason_ref=checkout_id,
        workspace_id=purchase["workspace_id"],
    )
    return {
        "plan_key": plan.key,
        "credits": int(plan.credits),
        "balance": int(balance),
        "checkout_id": checkout_id,
        "workspace_id": purchase["workspace_id"],
        "unlocked": not purchase["workspace_id"],
    }


def handle_polar_webhook(payload: bytes, headers: dict[str, Any]) -> int | None:
    """Verify a Polar webhook and fulfill the purchase if it is a completed sale.

    Delegates Standard-Webhooks signature verification (``webhook-id`` /
    ``webhook-timestamp`` / ``webhook-signature`` headers) + event extraction to
    ``polar_client`` (which reads ``config.polar.webhook_secret``). Returns the new
    balance for a fulfilled ``order.created`` / succeeded ``checkout.updated``
    event, or ``None`` for any other (ignored) event. Signature-verification
    failures propagate so the API layer can respond 400. Fulfillment is the shared
    idempotent :func:`fulfill_purchase`, keyed on the Polar ``checkout_id`` so both
    the ``order.created`` and ``checkout.updated`` deliveries for one purchase
    dedupe to a single grant; a ``workspace_id`` in the checkout metadata routes
    the grant to the shared pool.

    Args:
        payload: Raw request body bytes (byte-exact — do not re-serialize).
        headers: The inbound request headers (mapping; case-insensitive).
    """
    from app.services.billing import polar_client

    event = polar_client.verify_and_parse_webhook(payload, headers)
    if _route_subscription_event(POLAR, event):
        return None

    purchase = polar_client.extract_completed_purchase(event)
    if not purchase:
        # Verified but not a fulfillment event: ack 200, grant nothing.
        return None

    checkout_id = purchase["checkout_id"]
    event_id = str(_read(event, "id", "") or "").strip() or checkout_id
    return fulfill_purchase(
        provider=POLAR,
        external_event_id=event_id,
        user_id=purchase["user_id"],
        credits=int(purchase["credits"]),
        reason_ref=checkout_id,
        # None for a personal purchase; a real id routes to the workspace pool.
        workspace_id=purchase.get("workspace_id"),
    )


def handle_iyzico_callback(token: str) -> int | None:
    """Retrieve an iyzico checkout result by ``token`` and fulfill if paid.

    The iyzico client re-fetches the authoritative payment result from iyzico's
    API (never trusting the raw callback), returning a normalized dict:

        ``{"user_id", "credits", "payment_id", "paid": bool, ...}``

    Returns the new balance when the payment is confirmed paid, else ``None``.

    Args:
        token: The iyzico Checkout-Form token echoed to the callback URL.
    """
    if not (token or "").strip():
        raise ValueError("handle_iyzico_callback requires a non-empty token")

    iyzico_client = _import_iyzico_client()
    result = iyzico_client.retrieve_and_verify(token)
    if not result:
        return None

    if not result.get("paid"):
        logger.info(
            f"billing: iyzico payment not completed for token={token!r}; "
            "no credits granted"
        )
        return None

    # Prefer the provider's payment id when present; otherwise the checkout-form
    # token is itself a unique, provider-issued handle for this purchase and is a
    # safe dedupe key (SETNX) + ledger provenance reference.
    payment_id = str(result.get("payment_id", "") or "").strip() or token.strip()
    if not payment_id:
        raise ValueError("iyzico result is missing a payment_id")

    return fulfill_purchase(
        provider=IYZICO,
        external_event_id=payment_id,
        user_id=str(result.get("user_id", "") or ""),
        credits=int(result.get("credits", 0) or 0),
        reason_ref=payment_id,
    )


def grant_signup_credits(user_id: str) -> int:
    """Grant the one-time signup credits to a new user, idempotently.

    Per-user idempotency uses both Redis (``billing:signup:<user_id>``) and the
    durable ledger-reason lookup (reason ``"signup"``), so a user is never
    double-granted even if Redis is flushed or unavailable.

    Returns the user's balance after the grant (or current balance if already
    granted).
    """
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("grant_signup_credits requires a non-empty user_id")

    from app.services.billing.plans import SIGNUP_GRANT

    return _idempotent_grant(
        idempotency_key=f"{_SIGNUP_KEY_PREFIX}:{uid}",
        user_id=uid,
        credits=int(SIGNUP_GRANT),
        reason=_SIGNUP_REASON,
        ttl_seconds=None,  # signup lock never expires; ledger reason is durable
    )


# ---------------------------------------------------------------------------
# Lazy provider-client import
# ---------------------------------------------------------------------------


def _import_iyzico_client() -> Any:
    """Lazily import the iyzico client, with a clear error if it is absent.

    Contract expected of ``app.services.billing.iyzico_client``:
        * ``create_checkout_form(user, plan) -> dict`` with a hosted payment
          URL (``payment_page_url``/``checkout_url``) and a ``token``.
        * ``retrieve_and_verify(token) -> dict | None`` with
          ``{"user_id", "credits", "paid": bool}`` (``payment_id`` optional;
          the token is used as the dedupe handle when it is absent).
    """
    try:
        from app.services.billing import iyzico_client

        return iyzico_client
    except Exception as exc:
        raise RuntimeError(
            "iyzico billing is unavailable: could not import "
            f"app.services.billing.iyzico_client ({exc})."
        ) from exc


__all__ = [
    "RedirectVerificationError",
    "confirm_creem_redirect",
    "create_checkout",
    "fulfill_purchase",
    "grant_signup_credits",
    "handle_creem_webhook",
    "handle_iyzico_callback",
    "handle_polar_webhook",
    "handle_stripe_webhook",
    "list_enabled_providers",
    "list_plans",
]
