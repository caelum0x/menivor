"""Standard Webhooks signature verification (https://www.standardwebhooks.com).

Used by Dodo Payments: headers ``webhook-id`` / ``webhook-timestamp`` /
``webhook-signature``; signed content ``"<id>.<timestamp>.<raw body>"``;
HMAC-SHA256 keyed with the base64-decoded secret (``whsec_`` prefix stripped);
the signature header is a space-separated list of ``v1,<base64>`` entries and a
delivery is valid if any entry matches.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Mapping

TOLERANCE_SECONDS: int = 5 * 60


class SignatureError(ValueError):
    """The delivery is not authentic (or too old / malformed)."""


def secret_key_bytes(secret: str) -> bytes:
    raw = (secret or "").strip()
    if raw.startswith("whsec_"):
        raw = raw[len("whsec_") :]
    try:
        return base64.b64decode(raw, validate=True)
    except Exception:  # noqa: BLE001 - tolerate raw (non-base64) secrets
        return raw.encode("utf-8")


def sign(secret: str, msg_id: str, timestamp: str, payload: bytes) -> str:
    """Base64 HMAC-SHA256 of ``<id>.<ts>.<body>`` (exposed for tests/tools)."""
    content = f"{msg_id}.{timestamp}.".encode("utf-8") + bytes(payload)
    digest = hmac.new(secret_key_bytes(secret), content, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def _lookup(headers: Mapping[str, Any] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in (headers or {}).items():
        out[str(key).strip().lower()] = "" if value is None else str(value)
    return out


def verify(
    payload: bytes,
    headers: Mapping[str, Any] | None,
    secret: str,
    *,
    now: int | None = None,
    tolerance: int = TOLERANCE_SECONDS,
) -> dict:
    """Verify and return the parsed JSON body; raises :class:`SignatureError`."""
    if not secret:
        raise RuntimeError("webhook secret is not configured")
    if not isinstance(payload, (bytes, bytearray)):
        raise SignatureError("webhook payload must be raw bytes")
    lookup = _lookup(headers)
    msg_id = lookup.get("webhook-id", "")
    stamp = lookup.get("webhook-timestamp", "")
    header = lookup.get("webhook-signature", "")
    if not msg_id or not stamp or not header:
        raise SignatureError("missing webhook-id / webhook-timestamp / webhook-signature")
    try:
        ts = int(stamp.strip())
    except ValueError as exc:
        raise SignatureError("webhook-timestamp is not an integer") from exc
    current = int(time.time()) if now is None else int(now)
    if abs(current - ts) > tolerance:
        raise SignatureError("webhook timestamp is outside the allowed tolerance")
    expected = sign(secret, msg_id, stamp.strip(), bytes(payload))
    matched = False
    for token in header.split():
        version, _, candidate = token.partition(",")
        if version == "v1" and candidate and hmac.compare_digest(candidate, expected):
            matched = True
            break
    if not matched:
        raise SignatureError("webhook signature does not match")
    try:
        body = json.loads(bytes(payload).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise SignatureError(f"webhook body is not JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise SignatureError("webhook body is not a JSON object")
    body["_webhook_id"] = msg_id
    return body


__all__ = ["SignatureError", "TOLERANCE_SECONDS", "secret_key_bytes", "sign", "verify"]
