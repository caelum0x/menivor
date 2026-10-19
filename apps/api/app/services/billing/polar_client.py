"""Polar (polar.sh) checkout + webhook adapter for ReelForge billing.

Polar is a *merchant-of-record* checkout platform: it hosts the payment page,
handles tax/VAT, and notifies us via webhooks. This module mirrors the
interface of :mod:`app.services.billing.stripe_client` exactly and is a pure
transport/parsing adapter — it does exactly three jobs and nothing else:

1. :func:`create_checkout_session` — open a hosted checkout for a credit pack
   (``POST https://api.polar.sh/v1/checkouts/``) and return its url + id.
2. :func:`verify_and_parse_webhook` — cryptographically verify an inbound
   webhook using Polar's `Standard Webhooks <https://www.standardwebhooks.com>`_
   scheme (``webhook-id`` / ``webhook-timestamp`` / ``webhook-signature`` headers,
   HMAC-SHA256, base64, constant-time compare) and return the parsed event.
3. :func:`extract_completed_purchase` — pull the ``{user_id, credits,
   checkout_id, plan_key, workspace_id}`` provenance out of an ``order.created``
   or ``checkout.updated`` (``status == "succeeded"``) event (``workspace_id`` is
   ``None`` for a personal purchase; returns ``None`` for any other event).

It writes NO credits: the service layer owns the ledger and webhook idempotency
(Redis ``SETNX`` on the provider event id + a durable ledger-reason dedupe).

Secrets are read ONLY from ``config.polar`` (``access_token``,
``webhook_secret``, ``success_url``) — never hardcoded. The ``import requests``
is guarded so the module still parses/imports when the dependency is absent
(e.g. during ``py_compile`` in CI); the clear error is raised only when a
function that actually needs it is called.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Mapping

from loguru import logger

from app.config import config

try:  # ``requests`` is only needed to *create* a checkout; guard for py_compile.
    import requests

    _REQUESTS_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only without requests
    requests = None  # type: ignore[assignment]
    _REQUESTS_IMPORT_ERROR = exc


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Polar production API. A ``config.polar.base_url`` override lets the sandbox
# (``https://sandbox-api.polar.sh``) be targeted without touching this file.
_DEFAULT_BASE_URL: str = "https://api.polar.sh"
_CHECKOUT_PATH: str = "/v1/checkouts/"

# Events that represent a paid credit pack. ``order.created`` fires once the
# order is paid; ``checkout.updated`` is only a fulfilment signal when its
# ``status`` reaches ``succeeded``.
ORDER_CREATED_EVENT: str = "order.created"
CHECKOUT_UPDATED_EVENT: str = "checkout.updated"
_SUCCEEDED_STATUS: str = "succeeded"
_COMPLETED_EVENT_TYPES: frozenset[str] = frozenset(
    {ORDER_CREATED_EVENT, CHECKOUT_UPDATED_EVENT}
)

# Standard Webhooks: reject deliveries whose timestamp is outside this window
# (guards against replay of an old, captured request). 5 minutes each side.
_WEBHOOK_TOLERANCE_SECONDS: int = 5 * 60
_SIGNATURE_VERSION: str = "v1"
_HTTP_TIMEOUT_SECONDS: int = 30

_REQUIRED_ACCESS_TOKEN: str = "access_token"
_REQUIRED_WEBHOOK_SECRET: str = "webhook_secret"


# ---------------------------------------------------------------------------
# Config / object access helpers
# ---------------------------------------------------------------------------


def _polar_config() -> dict[str, Any]:
    """Return the ``[polar]`` config section as a plain dict, defensively.

    Read via ``getattr`` so this module imports cleanly even if the ``[polar]``
    config wiring lands later, mirroring the Stripe/iyzico adapters.
    """
    section = getattr(config, "polar", None)
    if section is None:
        return {}
    try:
        return dict(section)
    except Exception:  # noqa: BLE001 - non-mapping guard
        return {}


def _read(obj: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from either an attribute-style object or a mapping.

    ``user`` and ``plan`` may be SQLAlchemy models, dataclasses, or plain dicts
    depending on the caller, so support both access styles without assuming a
    concrete type.
    """
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _require_requests() -> None:
    """Raise a clear error if ``requests`` is unavailable."""
    if requests is None:
        raise RuntimeError(
            "The 'requests' package is required for Polar billing but is not "
            "installed. Add 'requests' to the environment "
            f"(original import error: {_REQUESTS_IMPORT_ERROR})."
        )


def _require_access_token() -> str:
    """Return the configured Polar access token or raise a clear error."""
    token = str(_polar_config().get(_REQUIRED_ACCESS_TOKEN, "") or "").strip()
    if not token:
        raise RuntimeError(
            "Polar is not configured: missing config.polar.access_token."
        )
    return token


def _base_url() -> str:
    """Resolve the Polar API base url (production unless overridden in config)."""
    return str(_polar_config().get("base_url", "") or "").strip() or _DEFAULT_BASE_URL


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------


def create_checkout_session(
    user: Any, plan: Any, workspace_id: str | None = None
) -> dict[str, str]:
    """Create a hosted Polar checkout for a credit pack.

    POSTs to ``/v1/checkouts/`` with the plan's Polar price id
    (``plan.polar_price_id``), a ``success_url`` and the provenance needed to
    fulfil the purchase on webhook — ``user_id``, ``plan_key`` and ``credits`` —
    stored in the checkout ``metadata`` (values coerced to strings so the shape
    matches the Stripe adapter and survives Polar's metadata typing).

    When ``workspace_id`` is supplied (an admin funding a workspace's shared
    credit pool) it is carried in ``metadata`` *alongside* the existing keys so
    the webhook routes the grant to the workspace pool instead of the actor's
    personal balance. The ``user_id`` still identifies the acting admin.

    Args:
        user: The purchasing user (object with ``id`` or a mapping).
        plan: The plan/pack being bought (needs ``polar_price_id``,
            ``key``/``plan_key`` and ``credits``).
        workspace_id: Optional target workspace whose shared pool should be
            funded. ``None``/empty means a personal purchase (unchanged).

    Returns:
        ``{"checkout_url": <hosted url>, "session_id": <checkout id>}``.

    Raises:
        RuntimeError: If ``requests`` is missing, config is incomplete, or Polar
            returns a non-2xx / malformed response.
        ValueError: If required ``user``/``plan`` fields are missing.
    """
    _require_requests()
    access_token = _require_access_token()

    user_id = str(_read(user, "id", "") or "").strip()
    if not user_id:
        raise ValueError("create_checkout_session: user is missing an 'id'.")

    price_id = str(_read(plan, "polar_price_id", "") or "").strip()
    if not price_id:
        raise ValueError(
            "create_checkout_session: plan is missing 'polar_price_id'."
        )

    # Plan exposes ``.key`` (dict payloads may use ``plan_key``); accept either so
    # the webhook provenance metadata is never silently blank.
    plan_key = str(
        _read(plan, "key", "") or _read(plan, "plan_key", "") or ""
    ).strip()
    credits = int(_read(plan, "credits", 0) or 0)

    cfg = _polar_config()
    success_url = str(cfg.get("success_url", "") or "").strip()
    if not success_url:
        raise RuntimeError(
            "Polar is not configured: missing config.polar.success_url."
        )

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

    payload: dict[str, Any] = {
        "product_price_id": price_id,
        "success_url": success_url,
        "customer_email": str(_read(user, "email", "") or "").strip() or None,
        "metadata": metadata,
    }
    # Drop null optional fields so Polar does not reject an empty email.
    payload = {key: value for key, value in payload.items() if value is not None}

    url = f"{_base_url().rstrip('/')}{_CHECKOUT_PATH}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        response = requests.post(
            url, json=payload, headers=headers, timeout=_HTTP_TIMEOUT_SECONDS
        )
    except Exception as exc:  # noqa: BLE001 - surface a clean error to the service
        logger.error(
            f"Polar checkout create failed (transport) for user={user_id!r} "
            f"plan={plan_key!r}: {exc}"
        )
        raise RuntimeError(f"Polar checkout create failed: {exc}") from exc

    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code < 200 or status_code >= 300:
        body = _safe_text(response)
        logger.error(
            f"Polar checkout create rejected (HTTP {status_code}) for "
            f"user={user_id!r} plan={plan_key!r}: {body}"
        )
        raise RuntimeError(
            f"Polar checkout create rejected with HTTP {status_code}: {body}"
        )

    data = _safe_json(response)
    session_id = str(data.get("id", "") or "").strip()
    checkout_url = str(data.get("url", "") or "").strip()
    if not session_id or not checkout_url:
        raise RuntimeError(
            "Polar returned a checkout without an id/url "
            f"(session_id={session_id!r})."
        )

    logger.info(
        f"Polar checkout created: session_id={session_id} user={user_id} "
        f"plan={plan_key} credits={credits} workspace={workspace_id or '-'}"
    )
    return {"checkout_url": checkout_url, "session_id": session_id}


def _safe_text(response: Any) -> str:
    """Best-effort textual body of a response for error logging (never raises)."""
    try:
        return str(getattr(response, "text", "") or "")[:500]
    except Exception:  # noqa: BLE001 - logging must not mask the real error
        return "<unreadable response body>"


def _safe_json(response: Any) -> dict[str, Any]:
    """Decode a JSON response body to a dict, tolerating malformed payloads."""
    try:
        parsed = response.json()
    except Exception as exc:  # noqa: BLE001 - normalize to a clean error
        raise RuntimeError(f"Polar returned a non-JSON response body: {exc}") from exc
    return parsed if isinstance(parsed, dict) else {}


# ---------------------------------------------------------------------------
# Webhook verification (Standard Webhooks) + parsing
# ---------------------------------------------------------------------------


def _webhook_secret() -> str:
    """Return the configured Polar webhook signing secret or raise."""
    secret = str(_polar_config().get(_REQUIRED_WEBHOOK_SECRET, "") or "").strip()
    if not secret:
        raise RuntimeError(
            "Polar is not configured: missing config.polar.webhook_secret."
        )
    return secret


def _secret_key_bytes(secret: str) -> bytes:
    """Derive the HMAC key bytes from a Standard-Webhooks secret.

    Standard Webhooks secrets are base64-encoded and conventionally prefixed
    with ``whsec_``. Strip the prefix and base64-decode; if the value is not
    valid base64 (some deployments configure a raw string), fall back to the
    raw UTF-8 bytes so verification still has a deterministic key.
    """
    raw = secret.strip()
    if raw.startswith("whsec_"):
        raw = raw[len("whsec_") :]
    try:
        return base64.b64decode(raw)
    except Exception:  # noqa: BLE001 - tolerate non-base64 raw secrets
        return secret.encode("utf-8")


def _header_lookup(headers: Mapping[str, Any] | dict[str, Any]) -> dict[str, str]:
    """Return a case-insensitive copy of ``headers`` (lower-cased keys)."""
    lookup: dict[str, str] = {}
    if not headers:
        return lookup
    try:
        items = headers.items()
    except Exception:  # noqa: BLE001 - non-mapping guard
        return lookup
    for key, value in items:
        lookup[str(key).strip().lower()] = str(value) if value is not None else ""
    return lookup


def _first_header(lookup: dict[str, str], *names: str) -> str:
    """Return the first present, non-empty header value among ``names``."""
    for name in names:
        value = lookup.get(name.lower(), "")
        if value:
            return value
    return ""


def _sign_content(secret: str, msg_id: str, timestamp: str, payload: bytes) -> str:
    """Compute the base64 HMAC-SHA256 signature for a Standard-Webhooks message.

    The signed content is ``<id>.<timestamp>.<body>`` (body is the raw request
    bytes — signature verification is byte-exact). Exposed at module scope so
    tests can generate a valid header without duplicating the scheme.
    """
    key = _secret_key_bytes(secret)
    body = payload.decode("utf-8") if isinstance(payload, (bytes, bytearray)) else str(payload)
    signed_content = f"{msg_id}.{timestamp}.{body}".encode("utf-8")
    digest = hmac.new(key, signed_content, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _timestamp_within_tolerance(timestamp: str) -> bool:
    """True if ``timestamp`` (unix seconds) is within the allowed replay window."""
    try:
        ts = int(str(timestamp).strip())
    except (TypeError, ValueError):
        return False
    now = int(time.time())
    return abs(now - ts) <= _WEBHOOK_TOLERANCE_SECONDS


def verify_and_parse_webhook(payload: bytes, headers: dict[str, Any]) -> Any:
    """Verify a Polar (Standard Webhooks) signature and return the parsed event.

    Verification protects the credit-granting endpoint from forged requests, so a
    failure MUST propagate (the caller responds 400 and grants nothing). The
    steps follow the Standard Webhooks spec:

    1. Read the ``webhook-id`` / ``webhook-timestamp`` / ``webhook-signature``
       headers (case-insensitive; ``svix-*`` aliases accepted).
    2. Reject a timestamp outside the ±5min tolerance (anti-replay).
    3. Recompute ``HMAC-SHA256(secret, "<id>.<ts>.<body>")`` and constant-time
       compare it against every ``v1,<sig>`` entry in the signature header.
    4. Only then ``json.loads`` the raw body and return it.

    Args:
        payload: The raw, unparsed request body bytes (do NOT re-serialize —
            signature verification is byte-exact).
        headers: The inbound request headers (mapping; case-insensitive).

    Returns:
        The verified event as a ``dict``.

    Raises:
        RuntimeError: If ``webhook_secret`` is unset.
        ValueError: On missing headers, expired timestamp, signature mismatch, or
            malformed JSON.
    """
    secret = _webhook_secret()

    if not isinstance(payload, (bytes, bytearray)):
        raise ValueError("Polar webhook payload must be raw bytes.")

    lookup = _header_lookup(headers)
    msg_id = _first_header(lookup, "webhook-id", "svix-id")
    msg_timestamp = _first_header(lookup, "webhook-timestamp", "svix-timestamp")
    signature_header = _first_header(lookup, "webhook-signature", "svix-signature")

    if not msg_id or not msg_timestamp or not signature_header:
        raise ValueError(
            "Polar webhook is missing required Standard-Webhooks headers "
            "(webhook-id / webhook-timestamp / webhook-signature)."
        )

    if not _timestamp_within_tolerance(msg_timestamp):
        logger.warning(
            f"Polar webhook timestamp {msg_timestamp!r} is outside the allowed "
            "tolerance; rejecting as a possible replay."
        )
        raise ValueError("Polar webhook timestamp is outside the allowed tolerance.")

    expected = _sign_content(secret, msg_id, msg_timestamp, bytes(payload))

    # The header is a space-delimited list of ``<version>,<base64sig>`` entries;
    # accept the delivery if ANY v1 signature matches (secret rotation support).
    matched = False
    for token in signature_header.split(" "):
        token = token.strip()
        if not token:
            continue
        version, _, candidate = token.partition(",")
        if not candidate:
            # Some senders omit the version prefix; treat the whole token as sig.
            candidate = version
        if hmac.compare_digest(candidate, expected):
            matched = True
            break

    if not matched:
        logger.warning("Polar webhook signature verification failed.")
        raise ValueError("Polar webhook signature verification failed.")

    try:
        event = json.loads(bytes(payload).decode("utf-8"))
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        logger.warning(f"Polar webhook payload is malformed JSON: {exc}")
        raise ValueError(f"Polar webhook payload is malformed JSON: {exc}") from exc

    return event


# ---------------------------------------------------------------------------
# Event extraction
# ---------------------------------------------------------------------------


def _event_get(event: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from an event/object (mapping- or attribute-style)."""
    if event is None:
        return default
    if isinstance(event, Mapping):
        return event.get(key, default)
    getter = getattr(event, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except TypeError:  # pragma: no cover - non-standard get signature
            pass
    return getattr(event, key, default)


def extract_completed_purchase(event: Any) -> dict[str, Any] | None:
    """Extract purchase provenance from a completed Polar event.

    Fulfilment events are ``order.created`` (fires once an order is paid) and
    ``checkout.updated`` **only** when its ``status == "succeeded"``. Any other
    event type (or a non-succeeded checkout update) returns ``None`` so the
    caller acks with 200 and does nothing — safe to call on every verified
    webhook.

    The returned ``checkout_id`` is the value the service layer uses both for
    Redis ``SETNX`` idempotency and to encode ledger provenance as
    ``"purchase:polar:<checkout_id>"``.

    Args:
        event: A verified Polar event (from :func:`verify_and_parse_webhook`) or
            an equivalent mapping.

    Returns:
        ``{"user_id", "credits", "checkout_id", "plan_key", "workspace_id"}`` on
        a completed purchase with usable metadata, else ``None``. ``workspace_id``
        is the target shared pool for an admin's workspace purchase, or ``None``
        for an ordinary personal purchase.
    """
    event_type = str(_event_get(event, "type", "") or "")
    if event_type not in _COMPLETED_EVENT_TYPES:
        return None

    data = _event_get(event, "data", {}) or {}

    # ``checkout.updated`` is only a fulfilment signal at the succeeded status.
    if event_type == CHECKOUT_UPDATED_EVENT:
        status = str(_event_get(data, "status", "") or "").strip().lower()
        if status != _SUCCEEDED_STATUS:
            return None

    # Metadata lives on the object itself; for an order it may instead ride on
    # the nested checkout snapshot, so fall back to that.
    metadata = _event_get(data, "metadata", None)
    if not metadata:
        checkout = _event_get(data, "checkout", {}) or {}
        metadata = _event_get(checkout, "metadata", {}) or {}
    metadata = metadata or {}
    if str(_event_get(metadata, "kind", "") or "") == "subscription" or _event_get(
        data, "subscription_id", None
    ):
        # Recurring workspace plan (checkout or renewal order): fulfilled per
        # period by the subscription applier, never as a one-time pack.
        return None

    # The dedupe/provenance handle: prefer the stable checkout id, else the
    # order's own id so a foreign-shaped order is still uniquely identified.
    checkout_id = str(
        _event_get(data, "checkout_id", "")
        or _event_get(data, "id", "")
        or ""
    ).strip()
    if not checkout_id:
        logger.warning(
            f"Polar {event_type} event has no checkout/order id; ignoring."
        )
        return None

    user_id = str(_event_get(metadata, "user_id", "") or "").strip()
    plan_key = str(_event_get(metadata, "plan_key", "") or "").strip()
    credits = _parse_credits(_event_get(metadata, "credits", 0))

    # ``None`` for a personal purchase; a real id when an admin funded a
    # workspace's shared pool (the service routes the grant accordingly).
    workspace_id = (
        str(_event_get(metadata, "workspace_id", "") or "").strip() or None
    )

    if not user_id or credits <= 0:
        logger.warning(
            f"Polar {event_type} missing user_id/credits in metadata "
            f"(checkout_id={checkout_id}, user_id={user_id!r}, "
            f"credits={credits}); ignoring."
        )
        return None

    return {
        "user_id": user_id,
        "credits": credits,
        "checkout_id": checkout_id,
        "plan_key": plan_key,
        "workspace_id": workspace_id,
    }


def _parse_credits(raw: Any) -> int:
    """Coerce a metadata ``credits`` value to int, returning ``0`` if invalid.

    Polar metadata values may be strings or numbers; anything non-numeric maps
    to ``0`` so the caller treats it as an invalid/ignorable purchase rather
    than granting an unexpected amount.
    """
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return 0


__all__ = [
    "create_checkout_session",
    "verify_and_parse_webhook",
    "extract_completed_purchase",
]
