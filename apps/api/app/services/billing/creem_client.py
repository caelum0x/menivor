"""Creem (creem.io) checkout + webhook adapter for ReelForge billing.

Creem is a merchant-of-record checkout platform (like Stripe/Polar). This module
is a *pure transport/parsing adapter* around Creem's REST API and mirrors the
:mod:`app.services.billing.stripe_client` interface exactly. It performs three
jobs and nothing else:

1. :func:`create_checkout_session` — open a hosted checkout for a credit pack via
   ``POST https://api.creem.io/v1/checkouts`` and return its hosted URL + id.
2. :func:`verify_and_parse_webhook` — cryptographically verify an inbound webhook
   (HMAC-SHA256 of the raw body with the signing secret, constant-time compare)
   and return the parsed JSON event.
3. :func:`extract_completed_purchase` — pull the ``{user_id, credits, session_id,
   plan_key, workspace_id}`` provenance out of a completed checkout event
   (``workspace_id`` is ``None`` for a personal purchase; returns ``None`` for any
   other event type).

It writes NO credits: the service layer is solely responsible for the ledger and
for webhook idempotency (Redis ``SETNX`` on the Creem event id). Keeping this file
side-effect-free makes it trivially testable and keeps the trust boundary explicit.

Secrets are read ONLY from ``config.creem`` (``api_key``, ``webhook_secret``,
``success_url``) — never hardcoded — with ``config.stripe.success_url`` as a
``success_url`` fallback. The ``import requests`` is guarded so this module still
parses/imports when the package is absent (e.g. during ``py_compile`` in CI); the
clear error is raised only when a function that actually needs it is called.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from loguru import logger

from app.config import config

try:  # ``requests`` is optional at import/compile time.
    import requests

    _REQUESTS_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only without requests
    requests = None  # type: ignore[assignment]
    _REQUESTS_IMPORT_ERROR = exc


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CREEM_API_BASE: str = "https://api.creem.io"
CHECKOUT_PATH: str = "/v1/checkouts"

# Creem emits ``checkout.completed`` once a hosted checkout is paid. Accept the
# dotted form and a couple of documented aliases so a minor naming change on the
# provider side does not silently drop fulfillment.
COMPLETED_EVENT_TYPES: frozenset[str] = frozenset(
    {"checkout.completed", "checkout.paid"}
)

# Header Creem sends its HMAC signature in.
SIGNATURE_HEADER: str = "creem-signature"

# Network timeout (connect, read) for the checkout call — fail fast rather than
# hang a request thread on a provider outage.
_REQUEST_TIMEOUT: tuple[int, int] = (5, 15)


# ---------------------------------------------------------------------------
# Config / object access helpers
# ---------------------------------------------------------------------------


def _creem_config() -> dict[str, Any]:
    """Return the ``[creem]`` config section as a plain dict, defensively.

    Read via ``getattr`` so this module imports cleanly even if the config
    wiring lands later, mirroring the stripe/iyzico adapters.
    """
    section = getattr(config, "creem", None)
    if section is None:
        return {}
    try:
        return dict(section)
    except Exception:  # noqa: BLE001 - non-mapping guard
        return {}


def _stripe_config() -> dict[str, Any]:
    """Return the ``[stripe]`` config section (used only for the URL fallback)."""
    section = getattr(config, "stripe", None)
    if section is None:
        return {}
    try:
        return dict(section)
    except Exception:  # noqa: BLE001 - non-mapping guard
        return {}


def _read(obj: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from either an attribute-style object or a mapping.

    ``user`` and ``plan`` may be SQLAlchemy models, dataclasses, or plain dicts
    depending on the caller, so support both access styles.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _api_base() -> str:
    """Creem API origin: ``config.creem.base_url`` (e.g. the test-mode host) or prod."""
    configured = str(_creem_config().get("base_url", "") or "").strip().rstrip("/")
    return configured or CREEM_API_BASE


def _require_requests() -> None:
    """Raise a clear error if the ``requests`` package is unavailable."""
    if requests is None:
        raise RuntimeError(
            "The 'requests' package is required for Creem billing but is not "
            "installed. Add 'requests' to the environment "
            f"(original import error: {_REQUESTS_IMPORT_ERROR})."
        )


def _require_api_key() -> str:
    """Return the configured Creem API key or raise a clear error."""
    api_key = str(_creem_config().get("api_key", "") or "").strip()
    if not api_key:
        raise RuntimeError("Creem is not configured: missing config.creem.api_key.")
    return api_key


def _require_webhook_secret() -> str:
    """Return the configured Creem webhook signing secret or raise."""
    secret = str(_creem_config().get("webhook_secret", "") or "").strip()
    if not secret:
        raise RuntimeError(
            "Creem is not configured: missing config.creem.webhook_secret."
        )
    return secret


def _success_url() -> str:
    """Resolve the post-payment success URL.

    Prefers ``config.creem.success_url`` and falls back to
    ``config.stripe.success_url`` so a single hosted return page can be shared.
    """
    url = str(_creem_config().get("success_url", "") or "").strip()
    if url:
        return url
    fallback = str(_stripe_config().get("success_url", "") or "").strip()
    if fallback:
        return fallback
    raise RuntimeError(
        "Creem is not configured: missing config.creem.success_url (and no "
        "config.stripe.success_url fallback)."
    )


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------


def create_checkout_session(
    user: Any,
    plan: Any,
    workspace_id: str | None = None,
    success_url: str | None = None,
) -> dict[str, str]:
    """Create a hosted Creem checkout for a credit pack.

    Builds a checkout for the plan's Creem product (``plan.creem_product_id``).
    Provenance needed to fulfil the purchase on webhook — ``user_id``,
    ``plan_key`` and ``credits`` — is stored in the checkout ``metadata``. When
    ``workspace_id`` is supplied (an admin funding a workspace's shared pool) it
    is carried in ``metadata`` alongside the personal fields so the webhook can
    route the grant to the workspace pool; ``user_id`` still identifies the
    acting admin (recorded on the pool ledger row for audit).

    Args:
        user: The purchasing user (object with ``id`` or a mapping).
        plan: The plan/pack being bought (needs ``creem_product_id``, ``key`` /
            ``plan_key`` and ``credits``).
        workspace_id: Optional target workspace whose shared pool should be
            funded. ``None``/empty means a personal purchase (unchanged).

    Returns:
        ``{"checkout_url": <hosted url>, "session_id": <checkout id>}``.

    Raises:
        RuntimeError: If ``requests`` is missing, config is incomplete, or Creem
            returns a non-success response / a body without a usable id + url.
        ValueError: If required ``user``/``plan`` fields are missing.
    """
    _require_requests()
    api_key = _require_api_key()

    user_id = str(_read(user, "id", "") or "").strip()
    if not user_id:
        raise ValueError("create_checkout_session: user is missing an 'id'.")

    product_id = str(_read(plan, "creem_product_id", "") or "").strip()
    if not product_id:
        raise ValueError("create_checkout_session: plan is missing 'creem_product_id'.")

    # Plan exposes ``.key`` (dict payloads may use ``plan_key``); accept either so
    # the webhook provenance metadata is never silently blank.
    plan_key = str(_read(plan, "key", "") or _read(plan, "plan_key", "") or "").strip()
    credits = int(_read(plan, "credits", 0) or 0)

    metadata: dict[str, str] = {
        "user_id": user_id,
        "plan_key": plan_key,
        "credits": str(credits),
    }

    # Workspace-targeted purchase: carry the pool id so the webhook grants to the
    # shared pool instead of the actor's personal balance. Only add the key when a
    # real workspace id is present so a personal checkout's metadata stays
    # byte-for-byte unchanged.
    workspace_id = str(workspace_id or "").strip()
    if workspace_id:
        metadata["workspace_id"] = workspace_id

    body: dict[str, Any] = {
        "product_id": product_id,
        # A per-checkout return URL (e.g. the card check's onboarding page)
        # wins over the configured default.
        "success_url": str(success_url or "").strip() or _success_url(),
        # Correlation handle. Creem echoes it on events AND signs it into the
        # success redirect, so the redirect alone identifies who to credit.
        "request_id": encode_request_id(user_id, workspace_id or None),
        "metadata": metadata,
    }

    url = f"{_api_base()}{CHECKOUT_PATH}"
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        response = requests.post(
            url, headers=headers, json=body, timeout=_REQUEST_TIMEOUT
        )
    except Exception as exc:  # noqa: BLE001 - normalize transport errors
        logger.error(
            f"Creem checkout request failed for user={user_id!r} "
            f"plan={plan_key!r}: {exc}"
        )
        raise RuntimeError(f"Creem checkout request failed: {exc}") from exc

    status = int(getattr(response, "status_code", 0) or 0)
    if status < 200 or status >= 300:
        detail = _safe_response_text(response)
        logger.error(
            f"Creem checkout rejected (status={status}) for user={user_id!r} "
            f"plan={plan_key!r}: {detail}"
        )
        raise RuntimeError(f"Creem checkout rejected (status={status}): {detail}")

    try:
        data = response.json()
    except Exception as exc:  # noqa: BLE001 - malformed body
        logger.error(f"Creem checkout returned a non-JSON body: {exc}")
        raise RuntimeError(f"Creem checkout returned a non-JSON body: {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError("Creem checkout returned an unexpected (non-object) body.")

    session_id = str(data.get("id", "") or "").strip()
    checkout_url = str(
        data.get("checkout_url", "") or data.get("url", "") or ""
    ).strip()
    if not session_id or not checkout_url:
        raise RuntimeError(
            "Creem returned a checkout without an id/url "
            f"(session_id={session_id!r}, checkout_url={checkout_url!r})."
        )

    logger.info(
        f"Creem checkout created: session_id={session_id} user={user_id} "
        f"plan={plan_key} credits={credits} workspace={workspace_id or '-'}"
    )
    return {"checkout_url": checkout_url, "session_id": session_id}


def create_wallet_checkout_session(intent: Any) -> dict[str, str]:
    """Create a hosted Creem checkout for a variable USD **wallet top-up**.

    Unlike the fixed credit-pack ``create_checkout_session``, this funds an
    arbitrary wallet amount from a durable :class:`PaymentIntent`. The intent's
    ``id`` is threaded into ``metadata.payment_intent_id`` (and ``request_id``)
    so the webhook can map the confirmed payment back to exactly one intent and
    grant its credit once. The Creem product is a single operator-configured
    "wallet top-up" product (``config.creem.wallet_product_id``); the charged
    amount is the intent's ``total_charge_micros`` converted to minor units.

    Returns ``{"checkout_url": ..., "session_id": ...}``. Raises ``RuntimeError``
    when ``requests``/config is missing or Creem rejects the request.
    """
    _require_requests()
    api_key = _require_api_key()

    intent_id = str(_read(intent, "id", "") or "").strip()
    user_id = str(_read(intent, "user_id", "") or "").strip()
    if not intent_id:
        raise ValueError("create_wallet_checkout_session: intent is missing an 'id'.")

    product_id = str(_creem_config().get("wallet_product_id", "") or "").strip()
    if not product_id:
        raise RuntimeError(
            "Creem is not configured: missing config.creem.wallet_product_id."
        )

    total_micros = int(_read(intent, "total_charge_micros", 0) or 0)
    credit_micros = int(_read(intent, "credit_micros", 0) or 0)
    intent_meta = _read(intent, "meta", {}) or {}
    if not isinstance(intent_meta, dict):
        intent_meta = {}
    settlement_rail = str(intent_meta.get("settlement_rail", "local") or "local")
    mint_account_id = str(intent_meta.get("mint_account_id", "") or "").strip()
    # Creem charges in minor currency units (cents); never silently round a
    # durable intent because the webhook must prove the exact quoted charge.
    if total_micros <= 0 or total_micros % 10_000 != 0:
        raise ValueError(
            "create_wallet_checkout_session: total charge must be a positive "
            "whole number of USD cents."
        )
    amount_cents = total_micros // 10_000

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
        # Mint's Creem verifier reads this exact key from the authenticated
        # provider payload before it credits the account.
        metadata["account_id"] = mint_account_id
        metadata["mint_account_id"] = mint_account_id
    body: dict[str, Any] = {
        "product_id": product_id,
        "success_url": _success_url(),
        "request_id": intent_id,
        "amount": amount_cents,
        "metadata": metadata,
    }

    url = f"{_api_base()}{CHECKOUT_PATH}"
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        response = requests.post(
            url, headers=headers, json=body, timeout=_REQUEST_TIMEOUT
        )
    except Exception as exc:  # noqa: BLE001 - normalize transport errors
        logger.error(f"Creem wallet checkout failed for intent={intent_id!r}: {exc}")
        raise RuntimeError(f"Creem wallet checkout request failed: {exc}") from exc

    status = int(getattr(response, "status_code", 0) or 0)
    if status < 200 or status >= 300:
        detail = _safe_response_text(response)
        raise RuntimeError(
            f"Creem wallet checkout rejected (status={status}): {detail}"
        )

    try:
        data = response.json()
    except Exception as exc:  # noqa: BLE001 - malformed body
        raise RuntimeError(f"Creem wallet checkout non-JSON body: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Creem wallet checkout returned a non-object body.")

    session_id = str(data.get("id", "") or "").strip()
    checkout_url = str(
        data.get("checkout_url", "") or data.get("url", "") or ""
    ).strip()
    if not session_id or not checkout_url:
        raise RuntimeError("Creem wallet checkout returned no id/url.")
    logger.info(
        f"Creem wallet checkout created: session_id={session_id} intent={intent_id} "
        f"amount_cents={amount_cents}"
    )
    return {"checkout_url": checkout_url, "session_id": session_id}


def _safe_response_text(response: Any) -> str:
    """Best-effort short error detail from a response object (never raises)."""
    try:
        text = str(getattr(response, "text", "") or "")
    except Exception:  # noqa: BLE001 - defensive
        return "<unreadable response body>"
    return text[:500]


# ---------------------------------------------------------------------------
# Signed success redirect (credits land without a dashboard webhook)
# ---------------------------------------------------------------------------

# Parameters Creem appends to ``success_url`` and signs. Anything else in the
# query string (e.g. our own ``checkout=return``) is not part of the signature.
REDIRECT_SIGNED_PARAMS: frozenset[str] = frozenset(
    {
        "request_id",
        "checkout_id",
        "order_id",
        "customer_id",
        "subscription_id",
        "product_id",
    }
)

# ``request_id`` for a workspace-pool purchase: ``<user_id>~ws~<workspace_id>``.
_WORKSPACE_MARKER: str = "~ws~"


def encode_request_id(user_id: str, workspace_id: str | None = None) -> str:
    """Encode the buyer (and optional workspace pool) into Creem's ``request_id``.

    A personal purchase keeps the bare ``user_id`` (unchanged wire format).
    """
    user_id = str(user_id or "").strip()
    workspace_id = str(workspace_id or "").strip()
    if workspace_id:
        return f"{user_id}{_WORKSPACE_MARKER}{workspace_id}"
    return user_id


def decode_request_id(request_id: str) -> tuple[str, str | None]:
    """Inverse of :func:`encode_request_id`: ``(user_id, workspace_id|None)``."""
    raw = str(request_id or "").strip()
    if _WORKSPACE_MARKER in raw:
        user_id, workspace_id = raw.split(_WORKSPACE_MARKER, 1)
        return user_id.strip(), (workspace_id.strip() or None)
    return raw, None


def _redirect_digest(pairs: list[tuple[str, str]], api_key: str) -> str:
    """Creem's documented redirect signature.

    ``sha256("k1=v1|k2=v2|...|salt=<api_key>")`` over the appended params in the
    order they appear in the URL, skipping ``signature`` and empty/``null``
    values.
    """
    parts = [
        f"{key}={value}"
        for key, value in pairs
        if key != "signature" and value not in ("", "null")
    ]
    parts.append(f"salt={api_key}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def verify_redirect_signature(pairs: list[tuple[str, str]]) -> bool:
    """True iff ``pairs`` (the ordered success-URL query) carry a valid signature.

    The signature is salted with the Creem API key, so only Creem can produce it.
    The Creem-appended params are tried first; the full query (minus
    ``signature``) is accepted too, for a success URL without its own params.
    Constant-time comparison; never raises.
    """
    api_key = str(_creem_config().get("api_key", "") or "").strip()
    provided = ""
    for key, value in pairs:
        if key == "signature":
            provided = str(value or "").strip().lower()
    if not api_key or not provided:
        return False
    creem_only = [(k, v) for k, v in pairs if k in REDIRECT_SIGNED_PARAMS]
    candidates = [creem_only]
    if len(creem_only) != len([p for p in pairs if p[0] != "signature"]):
        candidates.append(list(pairs))
    return any(
        hmac.compare_digest(_redirect_digest(candidate, api_key), provided)
        for candidate in candidates
    )


def extract_redirect_purchase(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    """Purchase provenance from an already-VERIFIED success redirect.

    Returns ``{"checkout_id", "order_id", "product_id", "user_id",
    "workspace_id"}``. Raises ``ValueError`` when a field needed to credit the
    buyer is missing. Callers must run :func:`verify_redirect_signature` first.
    """
    values = {key: str(value or "").strip() for key, value in pairs}
    checkout_id = values.get("checkout_id", "")
    product_id = values.get("product_id", "")
    user_id, workspace_id = decode_request_id(values.get("request_id", ""))
    if not checkout_id:
        raise ValueError("Creem redirect is missing checkout_id.")
    if not product_id:
        raise ValueError("Creem redirect is missing product_id.")
    if not user_id:
        raise ValueError("Creem redirect is missing request_id (the buyer).")
    return {
        "checkout_id": checkout_id,
        "order_id": values.get("order_id", ""),
        "product_id": product_id,
        "subscription_id": values.get("subscription_id", ""),
        "user_id": user_id,
        "workspace_id": workspace_id,
    }


# ---------------------------------------------------------------------------
# Webhook verification + parsing
# ---------------------------------------------------------------------------


def verify_and_parse_webhook(payload: bytes, signature: str) -> Any:
    """Verify a Creem webhook signature and return the parsed event.

    Creem signs each webhook with HMAC-SHA256 over the raw request body using the
    configured ``config.creem.webhook_secret``; the hex digest is sent in the
    ``creem-signature`` header. Verification protects the credit-granting endpoint
    from forged requests, so a failure MUST propagate (the caller responds 400 and
    grants nothing). The comparison is constant-time.

    Args:
        payload: The raw, unparsed request body bytes (do NOT re-serialize —
            signature verification is byte-exact).
        signature: The value of the ``creem-signature`` request header.

    Returns:
        The verified event as a parsed ``dict``.

    Raises:
        RuntimeError: If ``webhook_secret`` is unset.
        ValueError: On a missing/invalid signature or a malformed JSON body.
    """
    webhook_secret = _require_webhook_secret()

    if not signature:
        raise ValueError("Creem webhook is missing the creem-signature header.")

    if not _signature_matches(payload, signature, webhook_secret):
        logger.warning("Creem webhook signature verification failed.")
        raise ValueError("Creem webhook signature verification failed.")

    try:
        event = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        logger.warning(f"Creem webhook payload is malformed JSON: {exc}")
        raise ValueError(f"Creem webhook payload is malformed JSON: {exc}") from exc

    return event


def _signature_matches(payload: bytes, signature: str, secret: str) -> bool:
    """Return True iff ``signature`` is a valid HMAC-SHA256 of ``payload``.

    Computes the expected hex digest and compares in constant time. Tolerates a
    ``sha256=`` prefix (a common webhook convention) so either form verifies.
    """
    if not isinstance(payload, (bytes, bytearray)):
        return False
    expected = hmac.new(
        secret.encode("utf-8"), bytes(payload), hashlib.sha256
    ).hexdigest()
    provided = signature.strip()
    if provided.lower().startswith("sha256="):
        provided = provided.split("=", 1)[1].strip()
    return hmac.compare_digest(expected, provided)


# ---------------------------------------------------------------------------
# Event extraction
# ---------------------------------------------------------------------------


def _event_get(event: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from an event/object (mapping- or attribute-style)."""
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


def _event_type(event: Any) -> str:
    """Resolve the event type across Creem's field-name variants."""
    return str(
        _event_get(event, "eventType", "")
        or _event_get(event, "event_type", "")
        or _event_get(event, "type", "")
        or ""
    ).strip()


def _event_object(event: Any) -> Any:
    """Resolve the event's payload object across Creem/Stripe-like envelopes.

    Creem nests the resource under ``object``; some deliveries wrap it as
    ``data.object`` (Stripe-style). Fall back to the event itself so a flat
    fixture still parses.
    """
    obj = _event_get(event, "object", None)
    if obj:
        return obj
    data = _event_get(event, "data", None)
    if data:
        nested = _event_get(data, "object", None)
        if nested:
            return nested
        return data
    return event


def extract_completed_purchase(event: Any) -> dict[str, Any] | None:
    """Extract purchase provenance from a completed-checkout Creem event.

    Returns ``None`` for any other event type (the caller acks with 200 and does
    nothing), so this is safe to call on every verified webhook.

    The returned ``session_id`` is the Creem checkout id — the value the service
    layer uses both for Redis ``SETNX`` idempotency and to encode ledger
    provenance as ``"purchase:creem:<session_id>"``.

    Args:
        event: A verified Creem event (from :func:`verify_and_parse_webhook`) or
            an equivalent mapping.

    Returns:
        ``{"user_id", "credits", "session_id", "plan_key", "workspace_id"}`` on a
        completed checkout with usable metadata, else ``None``. ``workspace_id``
        is the target shared pool for an admin's workspace purchase, or ``None``
        for an ordinary personal purchase.
    """
    if _event_type(event) not in COMPLETED_EVENT_TYPES:
        return None

    checkout = _event_object(event)

    session_id = str(_event_get(checkout, "id", "") or "").strip()
    if not session_id:
        logger.warning("Creem completed-checkout event has no id; ignoring.")
        return None

    metadata = _event_get(checkout, "metadata", {}) or {}
    if str(_event_get(metadata, "kind", "") or "") == "subscription":
        # Recurring workspace plan: fulfilled per period by the subscription
        # applier, never as a one-time pack.
        return None
    user_id = str(_event_get(metadata, "user_id", "") or "").strip()
    if not user_id:
        # Fall back to the correlation handle set at checkout creation.
        user_id, _ = decode_request_id(
            str(_event_get(checkout, "request_id", "") or "")
        )

    plan_key = str(_event_get(metadata, "plan_key", "") or "").strip()
    credits = _parse_credits(_event_get(metadata, "credits", 0))

    # ``None`` for a personal purchase; a real id when an admin funded a
    # workspace's shared pool (the service routes the grant accordingly).
    workspace_id = str(_event_get(metadata, "workspace_id", "") or "").strip() or None

    if not user_id or credits <= 0:
        logger.warning(
            "Creem completed-checkout missing user_id/credits in metadata "
            f"(session_id={session_id}, user_id={user_id!r}, credits={credits}); "
            "ignoring."
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
    """Coerce a metadata ``credits`` value to int, returning 0 on non-numeric.

    Creem metadata may echo the value as a string or an int; both parse. Anything
    non-numeric yields ``0`` so the caller treats it as an invalid/ignorable
    purchase rather than granting an unexpected amount.
    """
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return 0


__all__ = [
    "create_checkout_session",
    "encode_request_id",
    "decode_request_id",
    "verify_redirect_signature",
    "extract_redirect_purchase",
    "verify_and_parse_webhook",
    "extract_completed_purchase",
]
