"""Minimal RS256 JWT verification with ``cryptography`` (PyJWT-free fallback).

Used by :mod:`app.core.clerk` only when PyJWT is not installed in the running
image. Verifies the signature against a JWKS document (cached per URL for
``_JWKS_TTL_SECONDS``), then ``exp`` / ``nbf`` (with leeway), and ``iss`` /
``aud`` when configured. Anything unexpected raises :class:`TokenError`.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from typing import Any, Optional

_JWKS_TTL_SECONDS = 600
_LEEWAY_SECONDS = 30
_FETCH_TIMEOUT = (5, 10)

_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


class TokenError(Exception):
    """The token is malformed, unsigned by a known key, expired, or mis-scoped."""


def _b64url_decode(segment: str) -> bytes:
    padded = segment + "=" * (-len(segment) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except Exception as exc:  # noqa: BLE001 - any decode failure is a bad token
        raise TokenError("malformed token segment") from exc


def _json_segment(segment: str) -> dict[str, Any]:
    try:
        value = json.loads(_b64url_decode(segment))
    except TokenError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise TokenError("token segment is not JSON") from exc
    if not isinstance(value, dict):
        raise TokenError("token segment is not an object")
    return value


def _fetch_jwks(url: str, headers: dict[str, str]) -> dict[str, Any]:
    import requests

    response = requests.get(url, headers=headers or None, timeout=_FETCH_TIMEOUT)
    if response.status_code != 200:
        raise TokenError(f"JWKS fetch failed (HTTP {response.status_code})")
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
        raise TokenError("JWKS document has no keys")
    return data


def _key_for(kid: str, url: str, headers: dict[str, str]) -> dict[str, Any]:
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(url)
    fresh = cached is None or now - cached[0] >= _JWKS_TTL_SECONDS
    jwks = _fetch_jwks(url, headers) if fresh else cached[1]
    if fresh:
        with _cache_lock:
            _cache[url] = (time.monotonic(), jwks)
    key = _match(jwks, kid)
    if key is None and not fresh:
        # Unknown kid on a cached set: refetch once (key rotation).
        jwks = _fetch_jwks(url, headers)
        with _cache_lock:
            _cache[url] = (time.monotonic(), jwks)
        key = _match(jwks, kid)
    if key is None:
        raise TokenError("no JWKS key matches the token kid")
    return key


def _match(jwks: dict[str, Any], kid: str) -> Optional[dict[str, Any]]:
    for key in jwks.get("keys", []):
        if isinstance(key, dict) and key.get("kid") == kid and key.get("kty") == "RSA":
            return key
    return None


def _public_key(jwk: dict[str, Any]):
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers

    n = int.from_bytes(_b64url_decode(str(jwk.get("n", ""))), "big")
    e = int.from_bytes(_b64url_decode(str(jwk.get("e", ""))), "big")
    if n <= 0 or e <= 0:
        raise TokenError("JWKS key is not a usable RSA key")
    return RSAPublicNumbers(e, n).public_key()


def verify(
    token: str,
    *,
    jwks_url: str,
    headers: Optional[dict[str, str]] = None,
    issuer: Optional[str] = None,
    audience: Optional[str] = None,
    now: Optional[float] = None,
) -> dict[str, Any]:
    """Return the verified claims of an RS256 ``token`` or raise :class:`TokenError`."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    parts = (token or "").strip().split(".")
    if len(parts) != 3:
        raise TokenError("token is not a compact JWS")
    header = _json_segment(parts[0])
    if header.get("alg") != "RS256":
        raise TokenError("unsupported token algorithm")
    kid = str(header.get("kid") or "")
    if not kid:
        raise TokenError("token has no kid")

    key = _public_key(_key_for(kid, jwks_url, headers or {}))
    signature = _b64url_decode(parts[2])
    signed = f"{parts[0]}.{parts[1]}".encode("ascii")
    try:
        key.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature as exc:
        raise TokenError("signature verification failed") from exc

    claims = _json_segment(parts[1])
    current = time.time() if now is None else now
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or current > float(exp) + _LEEWAY_SECONDS:
        raise TokenError("token is expired")
    nbf = claims.get("nbf")
    if isinstance(nbf, (int, float)) and current + _LEEWAY_SECONDS < float(nbf):
        raise TokenError("token is not yet valid")
    if issuer and str(claims.get("iss") or "").rstrip("/") != issuer.rstrip("/"):
        raise TokenError("token issuer mismatch")
    if audience:
        aud = claims.get("aud")
        audiences = aud if isinstance(aud, list) else [aud]
        if audience not in audiences:
            raise TokenError("token audience mismatch")
    return claims


def reset_cache() -> None:
    with _cache_lock:
        _cache.clear()
