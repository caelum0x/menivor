"""Symmetric encryption for sensitive OAuth tokens (Direct-Publish).

AUTH-CRITICAL. This is the single boundary at which a plaintext OAuth
access/refresh token is turned into the opaque, encrypted blob persisted in
:class:`~app.models.db.models.SocialAccount` (``access_token_enc`` /
``refresh_token_enc``) — and back. A plaintext token is **never** written to the
database; only the output of :func:`encrypt` is stored.

Cipher
------
Uses :class:`cryptography.fernet.Fernet` (AES-128-CBC + HMAC-SHA256 authenticated
encryption with a rotating timestamp) — a vetted, misuse-resistant construction —
so this module never hand-rolls crypto. Fernet requires a 32-byte url-safe
base64 key; to let operators configure *any* sufficiently-random secret we stretch
the configured secret to that exact shape with SHA-256:

    fernet_key = urlsafe_b64encode( sha256(secret) )

This is deterministic, so the same secret always decrypts what it encrypted, and
any non-empty secret is a valid key (no special formatting required).

Key source (config/env ONLY — NEVER hardcoded)
----------------------------------------------
The secret is read, in order, from:

    1. the ``SOCIAL_TOKEN_KEY`` environment variable, else
    2. ``config.app["social_token_key"]``.

Presence is validated **at use** (lazily): if no secret is configured,
:func:`encrypt` / :func:`decrypt` raise :class:`MissingTokenKeyError` — a clean,
typed error the caller surfaces as a 5xx/clear failure — rather than persisting a
plaintext token or crashing at import time. Rotating the secret invalidates
previously-stored blobs (they can no longer be decrypted), which is the intended
fail-closed behavior for a compromised key.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

#: Environment variable holding the raw token-encryption secret.
_ENV_KEY: str = "SOCIAL_TOKEN_KEY"
#: ``config.app`` key holding the same secret (env takes precedence).
_CONFIG_KEY: str = "social_token_key"


class TokenCryptoError(Exception):
    """Base class for a token encrypt/decrypt failure."""


class MissingTokenKeyError(TokenCryptoError):
    """Raised when no token-encryption secret is configured (config/env).

    A clean, typed signal that ``SOCIAL_TOKEN_KEY`` (or ``config.app`` /
    ``social_token_key``) is unset — the caller must surface a clear error and
    must NOT fall back to storing a plaintext token.
    """


class TokenDecryptError(TokenCryptoError):
    """Raised when a stored blob cannot be decrypted (tampered / wrong key)."""


def _resolve_secret() -> str:
    """Resolve the raw encryption secret from env, then ``config.app``.

    Returns ``""`` when nothing is configured (the caller raises
    :class:`MissingTokenKeyError`). Reading ``config`` is guarded so a missing /
    unbound config section degrades to "no secret" rather than raising here.
    """
    env = os.getenv(_ENV_KEY, "").strip()
    if env:
        return env
    try:
        from app.config import config

        return str(config.app.get(_CONFIG_KEY, "") or "").strip()
    except Exception:  # pragma: no cover - config always bound in practice
        return ""


def _fernet() -> Fernet:
    """Build a :class:`Fernet` from the configured secret (stretched via SHA-256).

    Raises :class:`MissingTokenKeyError` when no secret is configured so a token
    is never encrypted/decrypted with an empty key.
    """
    secret = _resolve_secret()
    if not secret:
        raise MissingTokenKeyError(
            f"token encryption key is not configured: set the {_ENV_KEY} "
            f"environment variable or config.app['{_CONFIG_KEY}']"
        )
    fernet_key = base64.urlsafe_b64encode(
        hashlib.sha256(secret.encode("utf-8")).digest()
    )
    return Fernet(fernet_key)


def encrypt(plaintext: str) -> str:
    """Encrypt a plaintext token into an opaque, storable string blob.

    ``plaintext`` is coerced to ``str`` defensively. Raises
    :class:`MissingTokenKeyError` when no key is configured — so a caller can
    never silently persist an unencrypted token. Returns an ASCII token blob.
    """
    if plaintext is None:
        raise TokenCryptoError("cannot encrypt a None token")
    token = _fernet().encrypt(str(plaintext).encode("utf-8"))
    return token.decode("ascii")


def decrypt(blob: str) -> str:
    """Decrypt a blob produced by :func:`encrypt` back to the plaintext token.

    Raises :class:`MissingTokenKeyError` when no key is configured and
    :class:`TokenDecryptError` when the blob is tampered with, truncated, or was
    encrypted under a different key — never returns a partially-decrypted value.
    """
    if not blob:
        raise TokenCryptoError("cannot decrypt an empty blob")
    try:
        return _fernet().decrypt(str(blob).encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise TokenDecryptError(
            "token blob could not be decrypted (tampered or wrong key)"
        ) from exc


def is_configured() -> bool:
    """Return whether a token-encryption secret is available (config/env)."""
    return bool(_resolve_secret())


__all__ = [
    "TokenCryptoError",
    "MissingTokenKeyError",
    "TokenDecryptError",
    "encrypt",
    "decrypt",
    "is_configured",
]
