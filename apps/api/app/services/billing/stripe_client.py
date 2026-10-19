"""Stripe Checkout + webhook adapter for ReelForge billing.

This module is a *pure transport/parsing adapter* around the official ``stripe``
SDK. It performs exactly three jobs and nothing else:

1. :func:`create_checkout_session` — open a Checkout Session for a credit pack
   (``mode="payment"``) or a recurring plan (``mode="subscription"``, threading
   provenance onto ``subscription_data.metadata``) and return its hosted URL + id.
2. :func:`verify_and_parse_webhook` — cryptographically verify an inbound
   webhook using the signing secret and return the parsed event.
3. :func:`extract_completed_purchase` — pull the ``{user_id, credits,
   session_id, plan_key, workspace_id}`` provenance out of a
   ``checkout.session.completed`` event (``workspace_id`` is ``None`` for a
   personal purchase; returns ``None`` for any other event type).

It writes NO credits: the service layer is solely responsible for the ledger
and for webhook idempotency (Redis ``SETNX`` on the Stripe event id). Keeping
this file side-effect-free makes it trivially testable and keeps the trust
boundary explicit.

Secrets are read ONLY from ``config.stripe`` (``secret_key``,
``webhook_secret``, ``success_url``, ``cancel_url``) — never hardcoded. The
``import stripe`` is guarded so the module still parses/imports when the SDK is
absent (e.g. during ``py_compile`` in CI); the clear error is raised only when a
function that actually needs the SDK is called.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.config import config

try:  # The official Stripe SDK is optional at import/compile time.
    import stripe

    _STRIPE_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only without stripe
    stripe = None  # type: ignore[assignment]
    _STRIPE_IMPORT_ERROR = exc


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHECKOUT_MODE: str = "payment"  # one-time purchase (credit pack)
SUBSCRIPTION_MODE: str = "subscription"  # recurring plan (workspace subscription)
COMPLETED_EVENT_TYPE: str = "checkout.session.completed"

_REQUIRED_SECRET_KEY: str = "secret_key"
_REQUIRED_WEBHOOK_SECRET: str = "webhook_secret"


# ---------------------------------------------------------------------------
# Config / object access helpers
# ---------------------------------------------------------------------------


def _stripe_config() -> dict[str, Any]:
    """Return the ``[stripe]`` config section as a plain dict, defensively.

    The section is wired by the config layer; read it via ``getattr`` so this
    module imports cleanly even if that wiring lands later, mirroring the
    pattern used by the R2 and HeyGen adapters.
    """
    section = getattr(config, "stripe", None)
    if section is None:
        return {}
    try:
        return dict(section)
    except Exception:  # noqa: BLE001 - non-mapping guard
        return {}


def _read(obj: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from either an attribute-style object or a mapping.

    ``user`` and ``plan`` may be SQLAlchemy models, dataclasses, or plain
    dicts depending on the caller, so support both access styles without
    assuming a concrete type.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _require_sdk() -> None:
    """Raise a clear error if the Stripe SDK is unavailable."""
    if stripe is None:
        raise RuntimeError(
            "The 'stripe' SDK is required for Stripe billing but is not "
            "installed. Add 'stripe' to the environment "
            f"(original import error: {_STRIPE_IMPORT_ERROR})."
        )


def _require_secret_key() -> str:
    """Return the configured Stripe secret key or raise a clear error."""
    secret = str(_stripe_config().get(_REQUIRED_SECRET_KEY, "") or "").strip()
    if not secret:
        raise RuntimeError(
            "Stripe is not configured: missing config.stripe.secret_key."
        )
    return secret


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------


def create_checkout_session(
    user: Any,
    plan: Any,
    workspace_id: str | None = None,
    *,
    subscription: bool = False,
) -> dict[str, str]:
    """Create a Stripe Checkout Session for a credit pack or a recurring plan.

    Builds a session whose single line item is the plan's Stripe price
    (``plan.stripe_price_id``). Provenance needed to fulfil the purchase on webhook
    — ``user_id``, ``plan_key`` and ``credits`` — is stored in the session
    ``metadata`` (Stripe requires all metadata values to be strings).
    ``client_reference_id`` is also set to the user id as a secondary correlation
    handle.

    When ``subscription`` is ``False`` (the default) this is a one-time
    ``mode="payment"`` credit-pack purchase (fulfilled via the
    ``checkout.session.completed`` webhook). When ``subscription`` is ``True`` the
    session is opened in ``mode="subscription"`` so Stripe creates a real recurring
    Subscription + Invoice — the objects that drive the ``customer.subscription.*``
    / ``invoice.payment_succeeded`` webhook. Those objects do NOT inherit the
    Checkout Session metadata, so the same provenance is ALSO threaded onto the
    subscription via ``subscription_data.metadata``; without it the subscription
    webhook could never recover the ``workspace_id`` needed to fund the right pool.
    A recurring (subscription) price MUST use ``mode="subscription"`` — Stripe
    rejects it under ``mode="payment"``.

    When ``workspace_id`` is supplied (an admin funding a workspace's shared
    credit pool), it is carried in the session ``metadata`` *alongside* the
    existing ``user_id``/``plan_key``/``credits`` so the webhook can route the
    grant to the workspace pool instead of the actor's personal balance. The
    ``user_id`` still identifies the acting admin (recorded on the pool ledger
    row for audit); ``client_reference_id`` remains the user id.

    Args:
        user: The purchasing user (object with ``id`` or a mapping).
        plan: The plan/pack being bought (needs ``stripe_price_id``,
            ``plan_key`` and ``credits``).
        workspace_id: Optional target workspace whose shared pool should be
            funded. ``None``/empty means a personal purchase (unchanged).

    Returns:
        ``{"checkout_url": <hosted url>, "session_id": <session id>}``.

    Raises:
        RuntimeError: If the SDK is missing or config is incomplete.
        ValueError: If required ``user``/``plan`` fields are missing.
    """
    _require_sdk()
    stripe.api_key = _require_secret_key()

    user_id = str(_read(user, "id", "") or "").strip()
    if not user_id:
        raise ValueError("create_checkout_session: user is missing an 'id'.")

    price_id = str(_read(plan, "stripe_price_id", "") or "").strip()
    if not price_id:
        raise ValueError(
            "create_checkout_session: plan is missing 'stripe_price_id'."
        )

    # Plan exposes ``.key`` (dict payloads may use ``plan_key``); accept either so
    # the webhook provenance metadata is never silently blank.
    plan_key = str(
        _read(plan, "key", "") or _read(plan, "plan_key", "") or ""
    ).strip()
    credits = int(_read(plan, "credits", 0) or 0)

    cfg = _stripe_config()
    success_url = str(cfg.get("success_url", "") or "").strip()
    cancel_url = str(cfg.get("cancel_url", "") or "").strip()
    if not success_url or not cancel_url:
        raise RuntimeError(
            "Stripe is not configured: missing config.stripe.success_url "
            "and/or config.stripe.cancel_url."
        )

    metadata = {
        "user_id": user_id,
        "plan_key": plan_key,
        "credits": str(credits),
    }

    # Workspace-targeted purchase: carry the pool id so the webhook grants to the
    # shared pool instead of the actor's personal balance. Stripe requires string
    # metadata values; only add the key when a real workspace id is present so a
    # personal checkout's metadata stays byte-for-byte unchanged.
    workspace_id = str(workspace_id or "").strip()
    if workspace_id:
        metadata["workspace_id"] = workspace_id

    session_kwargs: dict[str, Any] = {
        "mode": SUBSCRIPTION_MODE if subscription else CHECKOUT_MODE,
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": user_id,
        "metadata": metadata,
    }
    if subscription:
        # The recurring Subscription/Invoice objects do not inherit the session
        # metadata; carry the same provenance so the subscription webhook can
        # recover the workspace_id / plan_key / user_id it routes the grant by.
        session_kwargs["subscription_data"] = {"metadata": dict(metadata)}

    try:
        session = stripe.checkout.Session.create(**session_kwargs)
    except Exception as exc:  # noqa: BLE001 - surface a clean error to the service layer
        logger.error(
            f"Stripe checkout.Session.create failed for user={user_id!r} "
            f"plan={plan_key!r}: {exc}"
        )
        raise

    session_id = str(_read(session, "id", "") or "")
    checkout_url = str(_read(session, "url", "") or "")
    if not session_id or not checkout_url:
        raise RuntimeError(
            "Stripe returned a checkout session without an id/url "
            f"(session_id={session_id!r})."
        )

    logger.info(
        f"Stripe checkout session created: session_id={session_id} "
        f"user={user_id} plan={plan_key} credits={credits} "
        f"workspace={workspace_id or '-'}"
    )
    return {"checkout_url": checkout_url, "session_id": session_id}


# ---------------------------------------------------------------------------
# Webhook verification + parsing
# ---------------------------------------------------------------------------


def create_wallet_checkout_session(intent: Any) -> dict[str, str]:
    """Create a one-time Stripe Checkout Session for a wallet top-up.

    The card charge is derived from the durable intent, never from browser
    input. Signed webhook metadata binds the later confirmation to the exact
    intent, credit amount, settlement rail, and optional Mint account.
    """
    _require_sdk()
    stripe.api_key = _require_secret_key()

    intent_id = str(_read(intent, "id", "") or "").strip()
    user_id = str(_read(intent, "user_id", "") or "").strip()
    if not intent_id:
        raise ValueError("create_wallet_checkout_session: intent is missing an 'id'.")

    total_micros = int(_read(intent, "total_charge_micros", 0) or 0)
    credit_micros = int(_read(intent, "credit_micros", 0) or 0)
    if total_micros <= 0 or total_micros % 10_000 != 0:
        raise ValueError(
            "create_wallet_checkout_session: total charge must be a positive "
            "whole number of USD cents."
        )
    intent_meta = _read(intent, "meta", {}) or {}
    if not isinstance(intent_meta, dict):
        intent_meta = {}
    settlement_rail = str(intent_meta.get("settlement_rail", "local") or "local")
    mint_account_id = str(intent_meta.get("mint_account_id", "") or "").strip()

    metadata: dict[str, str] = {
        "payment_intent_id": intent_id,
        "user_id": user_id,
        "credit_micros": str(credit_micros),
        "total_charge_micros": str(total_micros),
        "currency": "USD",
        "kind": "wallet_topup",
        "settlement_rail": settlement_rail,
    }
    if settlement_rail == "mint":
        if not mint_account_id:
            raise ValueError(
                "create_wallet_checkout_session: Mint checkout is missing "
                "meta.mint_account_id."
            )
        metadata["account_id"] = mint_account_id
        metadata["mint_account_id"] = mint_account_id

    cfg = _stripe_config()
    success_url = str(cfg.get("success_url", "") or "").strip()
    cancel_url = str(cfg.get("cancel_url", "") or "").strip()
    if not success_url or not cancel_url:
        raise RuntimeError(
            "Stripe is not configured: missing config.stripe.success_url "
            "and/or config.stripe.cancel_url."
        )

    session = stripe.checkout.Session.create(
        mode=CHECKOUT_MODE,
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": "Menivor AI token wallet top-up"},
                    "unit_amount": total_micros // 10_000,
                },
                "quantity": 1,
            }
        ],
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=user_id or intent_id,
        metadata=metadata,
        payment_intent_data={"metadata": dict(metadata)},
    )
    session_id = str(_read(session, "id", "") or "").strip()
    checkout_url = str(_read(session, "url", "") or "").strip()
    if not session_id or not checkout_url:
        raise RuntimeError("Stripe returned a wallet checkout without an id/url.")
    return {"checkout_url": checkout_url, "session_id": session_id}


def verify_and_parse_webhook(payload: bytes, sig_header: str) -> Any:
    """Verify a Stripe webhook signature and return the parsed event.

    Uses ``stripe.Webhook.construct_event`` with the configured
    ``config.stripe.webhook_secret``. Verification protects the credit-granting
    endpoint from forged requests, so a failure MUST propagate (the caller
    responds 400 and grants nothing).

    Args:
        payload: The raw, unparsed request body bytes (do NOT re-serialize —
            signature verification is byte-exact).
        sig_header: The value of the ``Stripe-Signature`` request header.

    Returns:
        The verified ``stripe`` event object.

    Raises:
        RuntimeError: If the SDK is missing or ``webhook_secret`` is unset.
        ValueError: On malformed payload or signature mismatch.
    """
    _require_sdk()

    webhook_secret = str(
        _stripe_config().get(_REQUIRED_WEBHOOK_SECRET, "") or ""
    ).strip()
    if not webhook_secret:
        raise RuntimeError(
            "Stripe is not configured: missing config.stripe.webhook_secret."
        )

    if not sig_header:
        raise ValueError("Stripe webhook is missing the Stripe-Signature header.")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=webhook_secret,
        )
    except ValueError as exc:
        # Malformed JSON payload.
        logger.warning(f"Stripe webhook payload is malformed: {exc}")
        raise
    except Exception as exc:  # noqa: BLE001 - includes SignatureVerificationError
        # Signature verification failed (or any other SDK-level rejection):
        # normalize to ValueError so the caller can uniformly return 400.
        logger.warning(f"Stripe webhook signature verification failed: {exc}")
        raise ValueError(f"Stripe webhook signature verification failed: {exc}") from exc

    return event


# ---------------------------------------------------------------------------
# Event extraction
# ---------------------------------------------------------------------------


def _event_get(event: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a Stripe event/object (mapping- or attribute-style).

    ``stripe`` objects behave like dicts (``.get``) but we fall back to
    ``getattr`` so plain dict fixtures work in tests too.
    """
    if event is None:
        return default
    if isinstance(event, dict):
        return event.get(key, default)
    getter = getattr(event, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except TypeError:  # pragma: no cover - non-standard get signature
            pass
    return getattr(event, key, default)


def extract_completed_purchase(event: Any) -> dict[str, Any] | None:
    """Extract purchase provenance from a ``checkout.session.completed`` event.

    Returns ``None`` for any other event type (the caller acks with 200 and
    does nothing), so this is safe to call on every verified webhook.

    The returned ``session_id`` is the Stripe Checkout Session id — the value
    the service layer uses both for Redis ``SETNX`` idempotency and to encode
    ledger provenance as ``"purchase:stripe:<session_id>"``.

    Args:
        event: A verified Stripe event (from :func:`verify_and_parse_webhook`)
            or an equivalent mapping.

    Returns:
        ``{"user_id", "credits", "session_id", "plan_key", "workspace_id"}`` on
        a completed checkout with usable metadata, else ``None``.
        ``workspace_id`` is the target shared pool for an admin's workspace
        purchase, or ``None`` for an ordinary personal purchase.
    """
    if _event_get(event, "type") != COMPLETED_EVENT_TYPE:
        return None

    data = _event_get(event, "data", {}) or {}
    session = _event_get(data, "object", {}) or {}

    session_id = str(_event_get(session, "id", "") or "").strip()
    if not session_id:
        logger.warning(
            "Stripe checkout.session.completed event has no session id; ignoring."
        )
        return None

    metadata = _event_get(session, "metadata", {}) or {}
    if (
        str(_event_get(session, "mode", "") or "") == SUBSCRIPTION_MODE
        or str(_event_get(metadata, "kind", "") or "") == "subscription"
    ):
        # A recurring workspace plan: its credits are granted per billing period
        # by the subscription webhook, never as a one-time pack here.
        return None
    user_id = str(_event_get(metadata, "user_id", "") or "").strip()
    if not user_id:
        # Fall back to the correlation handle set at session creation.
        user_id = str(_event_get(session, "client_reference_id", "") or "").strip()

    plan_key = str(_event_get(metadata, "plan_key", "") or "").strip()

    credits = _parse_credits(_event_get(metadata, "credits", 0))

    # ``None`` for a personal purchase; a real id when an admin funded a
    # workspace's shared pool (the service routes the grant accordingly).
    workspace_id = str(_event_get(metadata, "workspace_id", "") or "").strip() or None

    if not user_id or credits <= 0:
        logger.warning(
            "Stripe checkout.session.completed missing user_id/credits in "
            f"metadata (session_id={session_id}, user_id={user_id!r}, "
            f"credits={credits}); ignoring."
        )
        return None

    return {
        "user_id": user_id,
        "credits": credits,
        "session_id": session_id,
        "plan_key": plan_key,
        "workspace_id": workspace_id,
    }


def _parse_credits(raw: Any) -> int:
    """Coerce a metadata ``credits`` value (always a string on Stripe) to int.

    Returns ``0`` on anything non-numeric so the caller treats it as an
    invalid/ignorable purchase rather than granting an unexpected amount.
    """
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return 0
