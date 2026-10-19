"""Clerk JWT verification bridge (CTO §4: "Clerk JWT verified in FastAPI").

ReelForge fronts its API with Clerk for the hosted (multi-tenant) product while
keeping the Phase-1 ``x-api-key`` path for internal/single-key mode. This module
turns a Clerk-issued ``Authorization: Bearer <jwt>`` into verified claims:

* The signature is verified against Clerk's JWKS (RS256). The JWKS URL / issuer
  come from ``config.clerk`` (read defensively — an absent section disables the
  whole bridge, and behavior falls back to ``x-api-key`` only).
* ``PyJWT`` is imported behind a guard so this module (and anything importing it)
  stays import-safe even when the dependency is not installed — verification then
  raises a clean :class:`ClerkAuthError` at call time instead of crashing startup.
* The signing keys are fetched lazily and cached by :class:`jwt.PyJWKClient`
  (which caches per-``kid``); we cache the client itself per JWKS URL under a lock
  so concurrent requests share one key set and never re-fetch on the hot path.

The caller (``app/controllers/v1/jobs.py``) maps the returned ``sub``/``email``
claims to a ``User`` row (get-or-create); this module deliberately does not touch
the database so it stays a thin, testable verification unit.
"""

from __future__ import annotations

import threading
from typing import Any, Optional

from loguru import logger

from app.config import config

# --------------------------------------------------------------------------- #
# Guarded optional import (PyJWT). Absent dependency degrades to a clean
# ClerkAuthError at verification time rather than an ImportError at startup.
# --------------------------------------------------------------------------- #
try:
    import jwt
    from jwt import PyJWKClient

    _JWT_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # pragma: no cover - exercised only when PyJWT absent
    jwt = None  # type: ignore[assignment]
    PyJWKClient = None  # type: ignore[assignment,misc]
    _JWT_IMPORT_ERROR = exc


class ClerkAuthError(Exception):
    """Raised when a Clerk bearer token is missing, malformed, or invalid."""


# Default signing algorithm for Clerk-issued session JWTs.
_DEFAULT_ALGORITHMS: tuple[str, ...] = ("RS256",)

# Cached JWKS client keyed by the resolved JWKS URL (see ``_get_jwks_client``).
_jwks_lock = threading.Lock()
_jwks_client: Any = None
_jwks_client_url: str = ""


def _clerk_config() -> dict:
    """Return the ``[clerk]`` config section as a plain dict (defensively).

    Reads via ``getattr`` so a config build without a ``clerk`` attribute (the
    common case in internal/single-key mode) simply yields an empty mapping and
    disables the bridge instead of raising.
    """
    section = getattr(config, "clerk", {}) or {}
    try:
        return dict(section)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return {}


# Clerk Backend API JWKS. Authorized with the instance secret key, so it works
# even when the Frontend API domain (``clerk.<domain>``) is not reachable from
# the server (e.g. a proxied DNS record).
BACKEND_JWKS_URL: str = "https://api.clerk.com/v1/jwks"
# api.clerk.com sits behind Cloudflare, which answers 403 to urllib's default
# "Python-urllib/3.x" agent (PyJWKClient uses urllib). Without an explicit
# agent every web session JWT failed verification -> 401 on every signed-in call.
JWKS_USER_AGENT: str = "menivor-api/1.0 (+https://menivor.com)"


def _secret_key(cfg: dict) -> str:
    return str(cfg.get("secret_key") or "").strip()


def _jwks_url(cfg: dict) -> str:
    """Resolve the JWKS URL from config.

    Order: an explicit ``jwks_url``; the Backend API JWKS when a ``secret_key``
    is configured; otherwise the standard well-known path derived from the
    Clerk ``issuer`` (``<issuer>/.well-known/jwks.json``).
    """
    url = str(cfg.get("jwks_url") or "").strip()
    if url:
        return url
    if _secret_key(cfg):
        return BACKEND_JWKS_URL
    issuer = str(cfg.get("issuer") or "").strip().rstrip("/")
    if issuer:
        return f"{issuer}/.well-known/jwks.json"
    return ""


def _jwks_headers(cfg: dict, url: str) -> dict[str, str]:
    """Headers for the JWKS fetch: always a User-Agent; auth for the Backend API."""
    headers: dict[str, str] = {}
    secret = _secret_key(cfg)
    if secret and url == BACKEND_JWKS_URL:
        headers["Authorization"] = f"Bearer {secret}"
    headers["User-Agent"] = JWKS_USER_AGENT
    return headers


def is_configured() -> bool:
    """Return ``True`` only when Clerk verification can be attempted.

    Requires a resolvable JWKS URL (or issuer). When ``False`` the whole bridge
    is inert and auth falls back to the ``x-api-key`` path with unchanged
    behavior.
    """
    return bool(_jwks_url(_clerk_config()))


def extract_bearer_token(request: Any) -> Optional[str]:
    """Return the bare token from an ``Authorization: Bearer <jwt>`` header.

    Returns ``None`` when the header is absent or is not a Bearer credential, so
    the caller can fall back to ``x-api-key`` without raising.
    """
    try:
        header = request.headers.get("authorization") or request.headers.get(
            "Authorization"
        )
    except Exception:  # pragma: no cover - defensive against odd request objects
        return None
    if not header:
        return _jwt_from_api_key_header(request)
    parts = header.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def looks_like_jwt(value: str) -> bool:
    """True for a compact JWS (``eyJ...``.``...``.``...``); API keys never match."""
    value = (value or "").strip()
    return value.startswith("eyJ") and value.count(".") == 2 and " " not in value


def _jwt_from_api_key_header(request: Any) -> Optional[str]:
    """A session JWT the web client sent in ``x-api-key`` (it sends every
    credential there). Device/user API keys are never JWT-shaped, so they keep
    resolving through the key path."""
    try:
        value = str(request.headers.get("x-api-key") or "").strip()
    except Exception:  # pragma: no cover - defensive against odd request objects
        return None
    return value if looks_like_jwt(value) else None


def _get_jwks_client(url: str) -> Any:
    """Return a process-wide cached :class:`PyJWKClient` for ``url``.

    ``PyJWKClient`` caches signing keys per ``kid`` internally; caching the
    client under a lock means concurrent requests reuse one key set instead of
    each re-fetching the JWKS document.
    """
    global _jwks_client, _jwks_client_url
    if PyJWKClient is None:  # pragma: no cover - guarded caller already raised
        raise ClerkAuthError(f"PyJWT is not installed: {_JWT_IMPORT_ERROR}")
    headers = _jwks_headers(_clerk_config(), url)
    with _jwks_lock:
        if _jwks_client is None or _jwks_client_url != url:
            _jwks_client = PyJWKClient(url, headers=headers)
            _jwks_client_url = url
        return _jwks_client


def verify_clerk_jwt(token: str) -> dict[str, Any]:
    """Verify a Clerk session JWT and return its decoded claims.

    Raises :class:`ClerkAuthError` when PyJWT is unavailable, Clerk is not
    configured, or the token fails signature/issuer/audience/expiry validation.
    The audience is only enforced when an ``audience`` is configured.
    """
    if not token:
        raise ClerkAuthError("empty bearer token")

    cfg = _clerk_config()
    url = _jwks_url(cfg)
    if not url:
        raise ClerkAuthError("Clerk is not configured")

    issuer = str(cfg.get("issuer") or "").strip() or None
    audience = str(cfg.get("audience") or "").strip() or None
    algorithms = list(cfg.get("algorithms") or _DEFAULT_ALGORITHMS)

    if jwt is None:
        # PyJWT absent (slim image): verify RS256 with ``cryptography`` instead.
        from app.core import clerk_rs256

        try:
            return clerk_rs256.verify(
                token,
                jwks_url=url,
                headers=_jwks_headers(cfg, url),
                issuer=issuer,
                audience=audience,
            )
        except clerk_rs256.TokenError as exc:
            logger.warning(f"Clerk JWT verification failed: {exc}")
            raise ClerkAuthError(f"invalid bearer token: {exc}") from exc

    try:
        signing_key = _get_jwks_client(url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=algorithms,
            issuer=issuer,
            audience=audience,
            options={"verify_aud": audience is not None},
        )
    except ClerkAuthError:
        raise
    except Exception as exc:  # noqa: BLE001 - any decode/JWKS failure -> 401
        logger.warning(f"Clerk JWT verification failed: {exc}")
        raise ClerkAuthError(f"invalid bearer token: {exc}") from exc

    if not isinstance(claims, dict):  # pragma: no cover - PyJWT always returns dict
        raise ClerkAuthError("unexpected token payload")
    return claims


def reset_cache() -> None:
    """Clear the cached JWKS client (used by tests / after config changes)."""
    global _jwks_client, _jwks_client_url
    with _jwks_lock:
        _jwks_client = None
        _jwks_client_url = ""


__all__ = [
    "ClerkAuthError",
    "extract_bearer_token",
    "looks_like_jwt",
    "is_configured",
    "reset_cache",
    "verify_clerk_jwt",
]


# ---------------------------------------------------------------------------
# Primary email lookup (session tokens carry no email claim by default)
# ---------------------------------------------------------------------------

BACKEND_USERS_URL: str = "https://api.clerk.com/v1/users"
_EMAIL_LOOKUP_TIMEOUT_S: float = 5.0
_email_cache: dict[str, str] = {}
_email_cache_lock = threading.Lock()


def _primary_verified_email(payload: dict[str, Any]) -> str:
    primary_id = payload.get("primary_email_address_id")
    for item in payload.get("email_addresses") or []:
        if not isinstance(item, dict) or item.get("id") != primary_id:
            continue
        verification = item.get("verification") or {}
        if verification.get("status") != "verified":
            return ""
        return str(item.get("email_address") or "").strip().lower()
    return ""


def fetch_primary_email(sub: str) -> str:
    """The user's primary VERIFIED email from the Backend API, or ``""``.

    Best-effort: any failure (no secret key, network, non-200) returns ``""``
    so sign-in falls back to the synthetic address instead of failing.
    """
    sub = (sub or "").strip()
    secret = _secret_key(_clerk_config())
    if not sub or not secret or "/" in sub:
        return ""
    with _email_cache_lock:
        if sub in _email_cache:
            return _email_cache[sub]
    try:
        import requests

        response = requests.get(
            f"{BACKEND_USERS_URL}/{sub}",
            headers={"Authorization": f"Bearer {secret}", "User-Agent": JWKS_USER_AGENT},
            timeout=_EMAIL_LOOKUP_TIMEOUT_S,
        )
        if response.status_code != 200:
            logger.warning(f"clerk email lookup for {sub} returned {response.status_code}")
            return ""
        email = _primary_verified_email(response.json())
    except Exception as exc:  # noqa: BLE001 - never block sign-in on the lookup
        logger.warning(f"clerk email lookup for {sub} failed: {type(exc).__name__}")
        return ""
    if email:
        with _email_cache_lock:
            _email_cache[sub] = email
    return email
