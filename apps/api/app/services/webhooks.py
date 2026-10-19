"""Job-completion webhook delivery for Menivor power users.

Public API
----------
``deliver_webhook(url, payload, secret=None, timeout_s=10.0, *, webhook_id=None) -> dict``
    POST a JSON ``payload`` to ``url``. When a ``secret`` is supplied the
    request is signed (see "Signatures" below) so receivers can verify
    authenticity and freshness.
``verify_signature(secret, headers, body, tolerance_s=300, now=None) -> str``
    Receiver-side check (also used by our tests): returns the scheme that
    verified (``"v1"`` or ``"legacy"``) or raises :class:`SignatureError`.

Signatures (Standard Webhooks, https://www.standardwebhooks.com)
-----------------------------------------------------------------
Every signed delivery carries:

* ``webhook-id``: the message id. Stable across every retry of the same
  delivery (the event's ``event_id`` when it has one), so receivers can dedupe.
* ``webhook-timestamp``: unix seconds at the moment of THIS attempt (each retry
  is re-signed with a fresh timestamp).
* ``webhook-signature``: ``v1,<base64(HMAC-SHA256(key, f"{id}.{timestamp}.{body}"))>``.

The HMAC key is the subscription secret exactly as it was shown at creation,
taken as its raw UTF-8 bytes. Menivor secrets are NOT ``whsec_``-prefixed
base64; do not base64-decode them (a generic Standard Webhooks library must be
given the raw key bytes, not the secret string). Receivers should reject a
timestamp more than 5 minutes away from their clock (stale or in the future).

Deprecated (transition window): every delivery still carries the body-only
``X-Menivor-Signature: sha256=<hex HMAC-SHA256(secret, body)>``, which has no
timestamp and so no replay protection. Receivers should move to the
``webhook-*`` headers; :func:`verify_signature` accepts the body-only header
only when the ``webhook-*`` headers are absent, and the body-only headers will
be dropped in a later release announced on the developer page first.

Header rename (deprecation)
---------------------------
The product was renamed ReelForge -> Menivor. During the transition every
signed delivery carries BOTH ``X-Menivor-Signature`` (canonical) and the legacy
``X-ReelForge-Signature`` with the identical value, so existing receivers keep
verifying. ``X-ReelForge-Signature`` is deprecated: new integrations should
read ``X-Menivor-Signature``; the legacy header will be dropped in a future
release announced on the developer page.

Security (SSRF hardening)
-------------------------
Webhook URLs are attacker-influenceable (a user can register any callback URL),
so this module refuses to deliver to obviously-internal targets — loopback,
link-local (incl. the ``169.254.169.254`` cloud metadata endpoint), private
RFC-1918 ranges, and well-known metadata hostnames. This mitigates SSRF where a
crafted URL would coerce the server into calling internal services. The block
can be lifted for trusted deployments via
``config.app["reelforge_webhook_allow_internal"] = true`` (default: off).

Delivery is best-effort: transient failures are retried a couple of times with
a short backoff. The function never raises to the caller — it always returns a
result envelope ``{"delivered": bool, "status": int | None, "error"?: str}``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import socket
import time
from typing import Any, Mapping, Optional
from urllib.parse import urlparse, urlunparse

from loguru import logger

# ``requests`` is a first-party dependency, but guard the import so this module
# still ``py_compile``s / imports in stripped-down environments.
try:  # pragma: no cover - exercised indirectly via monkeypatching
    import requests  # type: ignore
except Exception:  # pragma: no cover - requests is normally installed
    requests = None  # type: ignore

try:
    from app.config import config  # type: ignore
except Exception:  # pragma: no cover - keep import-safe without full app config
    config = None  # type: ignore


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
SIGNATURE_HEADER: str = "X-Menivor-Signature"
# Deprecated alias sent alongside SIGNATURE_HEADER (same value) until removal.
LEGACY_SIGNATURE_HEADER: str = "X-ReelForge-Signature"
SIGNATURE_PREFIX: str = "sha256="
# Standard Webhooks headers (the current scheme, timestamped).
WEBHOOK_ID_HEADER: str = "webhook-id"
WEBHOOK_TIMESTAMP_HEADER: str = "webhook-timestamp"
WEBHOOK_SIGNATURE_HEADER: str = "webhook-signature"
SIGNATURE_VERSION: str = "v1"
SIGNATURE_TOLERANCE_S: int = 5 * 60
_SAFE_ID = re.compile(r"^[A-Za-z0-9._:\-]{1,200}$")
USER_AGENT: str = "Menivor-Webhook/1.0"
DEFAULT_TIMEOUT_S: float = 10.0
MAX_ATTEMPTS: int = 3  # 1 initial try + 2 retries
RETRY_BACKOFF_S: float = 0.5
_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})

# Hostnames that must never be contacted regardless of DNS resolution.
_BLOCKED_HOSTNAMES: frozenset[str] = frozenset(
    {
        "localhost",
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
        "instance-data.ec2.internal",
    }
)


# --------------------------------------------------------------------------- #
# SSRF guard helpers
# --------------------------------------------------------------------------- #
def _allow_internal() -> bool:
    """Return whether config permits delivery to internal targets."""
    if config is None:
        return False
    try:
        return bool(config.app.get("reelforge_webhook_allow_internal", False))
    except Exception:  # pragma: no cover - defensive; config shape drift
        return False


def _ip_is_internal(ip: str) -> bool:
    """Return True if ``ip`` belongs to a loopback/link-local/private range."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        # Not parseable as an IP — treat conservatively as internal.
        return True
    return bool(
        addr.is_loopback
        or addr.is_link_local  # covers 169.254.0.0/16 and fe80::/10
        or addr.is_private
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _validate_and_resolve(url: str) -> tuple[Optional[str], Optional[str]]:
    """Validate scheme + SSRF policy and resolve a single pinned IP.

    Returns ``(error, pinned_ip)``. On success ``error`` is ``None`` and
    ``pinned_ip`` is the exact IP the connection must be made to. Resolving the
    hostname here — once — and pinning that address at connect time closes the
    DNS-rebinding TOCTOU window: without pinning, ``requests`` would re-resolve
    the name at connect time and could be steered to an internal address that
    differs from the one vetted here.
    """
    if not url or not isinstance(url, str):
        return "invalid url", None

    try:
        parsed = urlparse(url.strip())
    except Exception:
        return "invalid url", None

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return f"unsupported url scheme: {parsed.scheme or '(none)'}", None

    host = parsed.hostname
    if not host:
        return "url missing host", None

    allow_internal = _allow_internal()
    blocked = f"refusing to deliver to internal/blocked host: {host}"

    normalized = host.strip().lower().rstrip(".")
    # Strip IPv6 brackets, e.g. "[::1]".
    if normalized.startswith("[") and normalized.endswith("]"):
        normalized = normalized[1:-1]

    if not allow_internal and normalized in _BLOCKED_HOSTNAMES:
        return blocked, None

    # Direct IP literal? Nothing to resolve; pin to the literal itself.
    try:
        ipaddress.ip_address(normalized)
    except ValueError:
        pass
    else:
        if not allow_internal and _ip_is_internal(normalized):
            return blocked, None
        return None, normalized

    # Resolve the hostname once; reject on failure or any internal address.
    try:
        infos = socket.getaddrinfo(normalized, None)
    except (socket.gaierror, socket.error, UnicodeError):
        return blocked, None

    resolved_ips = [
        str(info[4][0]) for info in infos if info[4] and info[4][0]
    ]
    if not resolved_ips:
        return blocked, None

    if not allow_internal:
        for ip in resolved_ips:
            if _ip_is_internal(ip):
                return blocked, None

    # Pin the connection to the first vetted address.
    return None, resolved_ips[0]


# --------------------------------------------------------------------------- #
# Signing
# --------------------------------------------------------------------------- #
def _unix_now() -> int:
    return int(time.time())


class SignatureError(ValueError):
    """A delivery's signature is missing, malformed, stale or does not match."""


def compute_signature(body: bytes, secret: str) -> str:
    """Return ``sha256=<hexdigest>`` HMAC of ``body`` keyed by ``secret`` (deprecated body-only scheme)."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


def sign_standard(secret: str, webhook_id: str, timestamp: int | str, body: bytes) -> str:
    """Return ``v1,<base64>``: HMAC-SHA256 of ``f"{id}.{timestamp}.{body}"`` keyed by the secret's UTF-8 bytes."""
    content = f"{webhook_id}.{timestamp}.".encode("utf-8") + bytes(body)
    digest = hmac.new(secret.encode("utf-8"), content, hashlib.sha256).digest()
    return f"{SIGNATURE_VERSION},{base64.b64encode(digest).decode('ascii')}"


def message_id(payload: Mapping[str, Any] | None, webhook_id: Optional[str] = None) -> str:
    """The ``webhook-id`` for a delivery: explicit id, else the payload's ``event_id``, else a fresh one.

    An id that is not header-safe is replaced by a stable hash of it, so every
    retry of the same delivery still carries the same ``webhook-id``.
    """
    raw = str(webhook_id or (payload or {}).get("event_id") or "").strip()
    if not raw:
        return f"msg_{secrets.token_hex(16)}"
    if _SAFE_ID.match(raw):
        return raw
    return f"msg_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]}"


def signature_headers(body: bytes, secret: str, webhook_id: str, *, now: Optional[int] = None) -> dict[str, str]:
    """All signature headers for ONE attempt: Standard Webhooks plus the deprecated body-only pair."""
    timestamp = _unix_now() if now is None else int(now)
    legacy = compute_signature(body, secret)
    return {
        WEBHOOK_ID_HEADER: webhook_id,
        WEBHOOK_TIMESTAMP_HEADER: str(timestamp),
        WEBHOOK_SIGNATURE_HEADER: sign_standard(secret, webhook_id, timestamp, body),
        SIGNATURE_HEADER: legacy,
        LEGACY_SIGNATURE_HEADER: legacy,
    }


def _header_map(headers: Mapping[str, Any] | None) -> dict[str, str]:
    return {str(k).strip().lower(): "" if v is None else str(v) for k, v in (headers or {}).items()}


def verify_signature(secret: str, headers: Mapping[str, Any] | None, body: bytes, tolerance_s: int = SIGNATURE_TOLERANCE_S,
                     now: Optional[int] = None) -> str:
    """Verify a Menivor delivery; return ``"v1"`` or ``"legacy"``, or raise :class:`SignatureError`.

    With the ``webhook-*`` headers present, the Standard Webhooks signature is
    required and the timestamp must be within ``tolerance_s`` of ``now`` (stale
    and future timestamps are both refused); the body-only header is then
    ignored, so stripping the new headers is the only way to reach the legacy
    path. Transition window: when NONE of the ``webhook-*`` headers are present,
    the deprecated body-only ``X-Menivor-Signature`` (or ``X-ReelForge-Signature``)
    is accepted.
    """
    if not secret:
        raise SignatureError("no signing secret")
    if not isinstance(body, (bytes, bytearray)):
        raise SignatureError("body must be the raw request bytes")
    found = _header_map(headers)
    msg_id = found.get(WEBHOOK_ID_HEADER, "").strip()
    stamp = found.get(WEBHOOK_TIMESTAMP_HEADER, "").strip()
    signature = found.get(WEBHOOK_SIGNATURE_HEADER, "").strip()
    if msg_id or stamp or signature:
        if not (msg_id and stamp and signature):
            raise SignatureError("incomplete webhook-id / webhook-timestamp / webhook-signature")
        try:
            ts = int(stamp)
        except ValueError as exc:
            raise SignatureError("webhook-timestamp is not an integer") from exc
        current = _unix_now() if now is None else int(now)
        if abs(current - ts) > int(tolerance_s):
            raise SignatureError("webhook-timestamp is outside the tolerance window")
        expected = sign_standard(secret, msg_id, stamp, bytes(body)).partition(",")[2]
        for token in signature.split():
            version, _, candidate = token.partition(",")
            if version == SIGNATURE_VERSION and candidate and hmac.compare_digest(candidate, expected):
                return SIGNATURE_VERSION
        raise SignatureError("webhook-signature does not match")
    legacy = (found.get(SIGNATURE_HEADER.lower()) or found.get(LEGACY_SIGNATURE_HEADER.lower()) or "").strip()
    if not legacy:
        raise SignatureError("no signature headers")
    if hmac.compare_digest(legacy, compute_signature(bytes(body), secret)):
        return "legacy"
    raise SignatureError("X-Menivor-Signature does not match")


# --------------------------------------------------------------------------- #
# Transport (DNS-pinned, redirect-refusing)
# --------------------------------------------------------------------------- #
if requests is not None:  # pragma: no branch - requests is normally installed

    class _PinnedHTTPAdapter(requests.adapters.HTTPAdapter):  # type: ignore[misc]
        """Force the TCP connection to a pre-vetted IP address.

        ``requests`` would otherwise re-invoke the OS resolver at connect time,
        reopening the DNS-rebinding window the SSRF guard just closed. This
        adapter rewrites the request URL's host to ``pinned_ip`` while keeping
        the original hostname for the ``Host`` header and TLS SNI / certificate
        verification, so the socket lands on exactly the address we validated.
        """

        def __init__(self, pinned_ip: str, **kwargs: Any) -> None:
            self._pinned_ip = pinned_ip
            super().__init__(**kwargs)

        def _pin(self, request: Any) -> None:
            parsed = urlparse(request.url)
            hostname = parsed.hostname
            if not hostname or not self._pinned_ip:
                return

            # Defense in depth: never open a socket to an internal address.
            if not _allow_internal() and _ip_is_internal(self._pinned_ip):
                raise requests.exceptions.InvalidURL(
                    f"refusing to connect to internal address: {self._pinned_ip}"
                )

            if parsed.scheme == "https":
                # Verify the cert against the real hostname, not the IP literal.
                self.poolmanager.connection_pool_kw["server_hostname"] = hostname
                self.poolmanager.connection_pool_kw["assert_hostname"] = hostname

            # Preserve virtual-host routing via the Host header (keeps any port).
            request.headers["Host"] = parsed.netloc

            pinned = self._pinned_ip
            if ":" in pinned and not pinned.startswith("["):
                pinned = f"[{pinned}]"  # bracket IPv6 literals
            new_netloc = parsed.netloc.replace(hostname, pinned, 1)
            request.url = urlunparse(parsed._replace(netloc=new_netloc))

        def send(self, request: Any, **kwargs: Any) -> Any:  # type: ignore[override]
            if not kwargs.get("proxies"):
                self._pin(request)
            return super().send(request, **kwargs)

else:  # pragma: no cover - only when requests is unavailable
    _PinnedHTTPAdapter = None  # type: ignore


def _post(
    url: str,
    *,
    data: bytes,
    headers: dict[str, str],
    timeout: float,
    pinned_ip: Optional[str],
) -> Any:
    """Perform a single POST with redirects disabled and DNS pinned.

    Redirects are never followed (``allow_redirects=False``) so a malicious 3xx
    ``Location`` cannot bounce the signed request to an unvalidated internal
    target (e.g. the cloud metadata endpoint). The connection is pinned to the
    already-vetted ``pinned_ip`` to prevent DNS-rebinding at connect time.
    """
    session = requests.Session()
    try:
        if pinned_ip and _PinnedHTTPAdapter is not None:
            adapter = _PinnedHTTPAdapter(pinned_ip)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
        return session.post(
            url,
            data=data,
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
        )
    finally:
        session.close()


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def deliver_webhook(
    url: str,
    payload: dict[str, Any],
    secret: Optional[str] = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    *,
    webhook_id: Optional[str] = None,
) -> dict[str, Any]:
    """POST ``payload`` as JSON to ``url``; best-effort with retries.

    Args:
        url: Destination webhook URL (must be http/https, non-internal).
        payload: JSON-serializable dict to send as the request body.
        secret: Optional HMAC-SHA256 signing key. When set, every attempt carries
            ``webhook-id`` / ``webhook-timestamp`` / ``webhook-signature``
            (Standard Webhooks, re-signed with a fresh timestamp per attempt,
            same id) plus the deprecated body-only ``X-Menivor-Signature`` and
            ``X-ReelForge-Signature``.
        timeout_s: Per-attempt request timeout in seconds.
        webhook_id: The ``webhook-id`` to send; defaults to ``payload["event_id"]``
            (a fresh id when the payload has none). Pass the same value on every
            retry of one delivery.

    Returns:
        ``{"delivered": bool, "status": int | None, "error"?: str}``.
    """
    if requests is None:
        return {
            "delivered": False,
            "status": None,
            "error": "requests library not available",
        }

    # Validate/serialize the payload before any network work.
    try:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    except (TypeError, ValueError) as exc:
        return {
            "delivered": False,
            "status": None,
            "error": f"payload not JSON-serializable: {exc}",
        }

    url_error, pinned_ip = _validate_and_resolve(url)
    if url_error is not None:
        logger.warning(f"Webhook rejected: {url_error}")
        return {"delivered": False, "status": None, "error": url_error}

    try:
        effective_timeout = float(timeout_s)
        if effective_timeout <= 0:
            effective_timeout = DEFAULT_TIMEOUT_S
    except (TypeError, ValueError):
        effective_timeout = DEFAULT_TIMEOUT_S

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    msg_id = message_id(payload, webhook_id) if secret else ""

    last_error: Optional[str] = None
    last_status: Optional[int] = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        attempt_headers = dict(headers)
        if secret:
            # Re-signed on every attempt: a fresh timestamp, the same webhook-id.
            attempt_headers.update(signature_headers(body, secret, msg_id))
        try:
            response = _post(
                url,
                data=body,
                headers=attempt_headers,
                timeout=effective_timeout,
                pinned_ip=pinned_ip,
            )
            status = int(getattr(response, "status_code", 0) or 0)
            last_status = status

            if 200 <= status < 300:
                logger.info(f"Webhook delivered to {url} (status={status})")
                return {"delivered": True, "status": status}

            last_error = f"non-2xx response: {status}"
            # 4xx (except 429) are client errors — retrying will not help.
            if 400 <= status < 500 and status != 429:
                logger.warning(f"Webhook not retried ({last_error}) for {url}")
                return {"delivered": False, "status": status, "error": last_error}

            logger.warning(
                f"Webhook attempt {attempt}/{MAX_ATTEMPTS} failed ({last_error}) for {url}"
            )
        except Exception as exc:  # network error, timeout, etc.
            last_error = f"{type(exc).__name__}: {exc}"
            last_status = None
            logger.warning(
                f"Webhook attempt {attempt}/{MAX_ATTEMPTS} error ({last_error}) for {url}"
            )

        if attempt < MAX_ATTEMPTS:
            time.sleep(RETRY_BACKOFF_S * attempt)

    return {
        "delivered": False,
        "status": last_status,
        "error": last_error or "delivery failed",
    }
