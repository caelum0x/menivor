"""Supabase Auth bridge: verify mobile sign-in JWTs and map them to a ``User``.

The mobile app signs creators in with Apple / Google through Supabase Auth. This
module verifies the Supabase access token server-side and resolves it to the
stable ReelForge ``User`` row, so:

* the same Apple / Google identity on a new phone (or after a reinstall) lands
  on the same account;
* a verified provider email that already belongs to a web (Clerk) account links
  to that account instead of creating a second one.

Configuration (server env):

* ``SUPABASE_URL`` — project URL (``https://<ref>.supabase.co``). Tokens are
  verified against ``<url>/auth/v1/.well-known/jwks.json`` (asymmetric keys) and
  the issuer ``<url>/auth/v1`` is enforced.
* ``SUPABASE_JWT_SECRET`` — optional HS256 secret for projects that sign user
  tokens with the shared environment secret (Scribase does by default).
* ``SUPABASE_JWKS_TIMEOUT_SECONDS`` (default 3) — JWKS fetch timeout.
* ``SUPABASE_JWKS_RETRY_SECONDS`` (default 30) — after a failed JWKS fetch,
  asymmetric tokens fail fast with :class:`SupabaseUnavailableError` for this
  long instead of hitting the network again.

``SUPABASE_URL`` is required: without it the issuer cannot be checked, so the
bridge is inert (``is_configured() is False``), bearer auth falls through to
Clerk, and ``POST /auth/device`` answers 503 for sign-in tokens. A token is
never trusted unverified. When the auth host is unreachable (the old shared
project went NXDOMAIN on 2026-10-06) verification fails closed with
:class:`SupabaseUnavailableError` (callers answer 503) within the timeout.

Import-safe: PyJWT is imported behind a guard.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Optional

from loguru import logger

try:
    import jwt
    from jwt import PyJWKClient

    _JWT_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # pragma: no cover - exercised only when PyJWT absent
    jwt = None  # type: ignore[assignment]
    PyJWKClient = None  # type: ignore[assignment,misc]
    _JWT_IMPORT_ERROR = exc


class SupabaseAuthError(Exception):
    """A Supabase bearer token is malformed, expired, or fails verification."""


class SupabaseUnavailableError(SupabaseAuthError):
    """The auth project's signing keys cannot be fetched (callers answer 503).

    A subclass so every existing ``except SupabaseAuthError`` still fails closed.
    """


_AUDIENCE = "authenticated"
_ASYMMETRIC_ALGORITHMS = ["ES256", "RS256"]
_ALLOWED_ALGORITHMS = frozenset(["HS256", *_ASYMMETRIC_ALGORITHMS])
# Providers whose email claim is verified by the identity provider itself.
_VERIFIED_EMAIL_PROVIDERS = frozenset({"apple", "google"})

_jwks_lock = threading.Lock()
_jwks_client: Any = None
_jwks_client_url = ""
# url -> monotonic time of the last failed JWKS fetch (negative cache).
_jwks_failures: dict[str, float] = {}


def _project_url() -> str:
    return os.getenv("SUPABASE_URL", "").strip().rstrip("/")


def _jwt_secret() -> str:
    return os.getenv("SUPABASE_JWT_SECRET", "").strip()


def _float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, "").strip() or default)
    except ValueError:
        return default
    return value if value >= 0 else default


def is_configured() -> bool:
    """Whether Supabase token verification can be attempted.

    The project URL is required (it fixes the issuer); the secret alone is not
    enough, because a token from any project signed with a leaked or reused
    secret could otherwise pass without an issuer check.
    """
    return bool(_project_url())


def startup_check() -> dict[str, Any]:
    """Log one line about mobile sign-in config at startup and return it."""
    url = _project_url()
    if not url:
        warning = (
            "SUPABASE_URL is not set: mobile Apple/Google sign-in linking is OFF "
            "(POST /api/v1/auth/device answers 503 for sign-in tokens; guest device "
            "sessions and web sign-in keep working). Set it to Menivor's Scribase project URL."
        )
        logger.warning(warning)
        return {"configured": False, "warning": warning}
    status = {
        "configured": True,
        "issuer": f"{url}/auth/v1",
        "hs256": bool(_jwt_secret()),
        "warning": "",
    }
    if jwt is None:
        status["warning"] = f"PyJWT is not installed: every mobile token is refused ({_JWT_IMPORT_ERROR})"
        logger.warning(status["warning"])
    else:
        logger.info(
            f"mobile sign-in: issuer {status['issuer']}, HS256 {'on' if status['hs256'] else 'off'}, ES256/RS256 via JWKS"
        )
    return status


def reset_jwks_failure() -> None:
    """Forget failed JWKS fetches (tests, or after fixing the config)."""
    with _jwks_lock:
        _jwks_failures.clear()


def _note_jwks_failure(url: str) -> None:
    with _jwks_lock:
        _jwks_failures[url] = time.monotonic()


def _recent_jwks_failure(url: str) -> bool:
    with _jwks_lock:
        failed_at = _jwks_failures.get(url)
    if failed_at is None:
        return False
    return time.monotonic() - failed_at < _float_env("SUPABASE_JWKS_RETRY_SECONDS", 30.0)


def looks_like_supabase_token(token: str) -> bool:
    """Cheap, unverified routing check: is this token issued by Supabase Auth?

    Only used to decide which verifier to run; the token is still fully
    verified before any identity is trusted.
    """
    if not token or jwt is None:
        return False
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except Exception:  # noqa: BLE001 - not a JWT -> not ours
        return False
    issuer = str(claims.get("iss") or "")
    return issuer.rstrip("/").endswith("/auth/v1")


def _jwks(url: str) -> Any:
    global _jwks_client, _jwks_client_url
    with _jwks_lock:
        if _jwks_client is None or _jwks_client_url != url:
            # Keys are cached (5 min for the set, per-kid LRU) and every fetch is
            # bounded by a short timeout, so a dead auth host cannot stall requests.
            _jwks_client = PyJWKClient(
                url,
                cache_keys=True,
                lifespan=300,
                timeout=_float_env("SUPABASE_JWKS_TIMEOUT_SECONDS", 3.0),
            )
            _jwks_client_url = url
        return _jwks_client


def _asymmetric_key(url: str, token: str) -> Any:
    jwks_url = f"{url}/auth/v1/.well-known/jwks.json"
    if _recent_jwks_failure(jwks_url):
        raise SupabaseUnavailableError("sign-in keys are temporarily unavailable")
    try:
        return _jwks(jwks_url).get_signing_key_from_jwt(token).key
    except jwt.exceptions.PyJWKClientConnectionError as exc:
        _note_jwks_failure(jwks_url)
        logger.warning(f"Supabase JWKS unreachable at {jwks_url}: {exc}")
        raise SupabaseUnavailableError("sign-in keys are temporarily unavailable") from exc


def verify_supabase_jwt(token: str) -> dict[str, Any]:
    """Verify a Supabase access token and return its claims (or raise)."""
    if not token:
        raise SupabaseAuthError("empty bearer token")
    if jwt is None:
        raise SupabaseAuthError(f"PyJWT is not installed: {_JWT_IMPORT_ERROR}")
    if not is_configured():
        raise SupabaseAuthError("Supabase auth is not configured")

    url = _project_url()
    issuer = f"{url}/auth/v1"
    try:
        header = jwt.get_unverified_header(token)
        alg = str(header.get("alg") or "")
        if alg not in _ALLOWED_ALGORITHMS:
            raise SupabaseAuthError(f"token algorithm {alg or 'none'!r} is not accepted")
        if alg == "HS256":
            secret = _jwt_secret()
            if not secret:
                raise SupabaseAuthError("HS256 tokens require SUPABASE_JWT_SECRET")
            key: Any = secret
            algorithms = ["HS256"]
        else:
            key = _asymmetric_key(url, token)
            algorithms = [alg]
        claims = jwt.decode(
            token,
            key,
            algorithms=algorithms,
            audience=_AUDIENCE,
            issuer=issuer,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except SupabaseAuthError:
        raise
    except Exception as exc:  # noqa: BLE001 - any decode/JWKS failure -> 401
        logger.warning(f"Supabase JWT verification failed: {exc}")
        raise SupabaseAuthError(f"invalid bearer token: {exc}") from exc
    if not isinstance(claims, dict) or not str(claims.get("sub") or "").strip():
        raise SupabaseAuthError("token has no subject")
    return claims


def verified_email(claims: dict[str, Any]) -> str:
    """The token's email when it is provider-verified, else ``""``.

    Only a verified email may link to an existing account (an unverified email
    could otherwise be used to take over someone else's account).
    """
    email = str(claims.get("email") or "").strip().lower()
    if not email:
        return ""
    app_meta = claims.get("app_metadata") if isinstance(claims.get("app_metadata"), dict) else {}
    user_meta = claims.get("user_metadata") if isinstance(claims.get("user_metadata"), dict) else {}
    provider = str(app_meta.get("provider") or "").lower()
    if provider in _VERIFIED_EMAIL_PROVIDERS or user_meta.get("email_verified") is True:
        return email
    return ""


def subject_email(claims: dict[str, Any]) -> str:
    """Stable synthetic email keyed on the Supabase subject (never collides)."""
    return f"supabase_{str(claims.get('sub') or '').strip()}@users.reelforge"


def find_identity_user(session: Any, claims: dict[str, Any]):
    """Return the existing ``User`` for this identity, or ``None``."""
    from app.models.db.models import User

    user = session.query(User).filter(User.email == subject_email(claims)).first()
    if user is not None:
        return user
    email = verified_email(claims)
    if email:
        return session.query(User).filter(User.email == email).first()
    return None


def identity_email(claims: dict[str, Any]) -> str:
    """The email a newly provisioned / adopted identity account should carry."""
    return verified_email(claims) or subject_email(claims)


def display_name(claims: dict[str, Any]) -> str:
    user_meta = claims.get("user_metadata") if isinstance(claims.get("user_metadata"), dict) else {}
    return str(user_meta.get("full_name") or user_meta.get("name") or "").strip()[:200]


__all__ = [
    "SupabaseAuthError",
    "SupabaseUnavailableError",
    "display_name",
    "find_identity_user",
    "identity_email",
    "is_configured",
    "looks_like_supabase_token",
    "reset_jwks_failure",
    "startup_check",
    "verified_email",
    "verify_supabase_jwt",
]
