"""Scribase Auth tokens for channel viewers (MV6; dogfood: viewer identity on Scribase Auth).

The viewer signs in on the Menivor viewers project of Scribase Auth (email
code, from the browser or the app) and hands the access token to
``POST /ott/viewers/{handle}/session`` once. This module verifies it:

* HS256 with ``SCRIBASE_AUTH_JWT_SECRET`` (the project's JWT secret), or
  RS256/ES256 through ``SCRIBASE_AUTH_JWKS_URL`` (the project's JWKS);
* ``aud`` is ``authenticated`` (``SCRIBASE_AUTH_AUDIENCE`` overrides), ``iss``
  matches ``SCRIBASE_AUTH_ISSUER`` when set, the token is not expired, and it
  carries a subject and an email.

Without either key setting nothing verifies (fail closed).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional

SECRET_ENV = "SCRIBASE_AUTH_JWT_SECRET"
JWKS_ENV = "SCRIBASE_AUTH_JWKS_URL"
ISSUER_ENV = "SCRIBASE_AUTH_ISSUER"
AUDIENCE_ENV = "SCRIBASE_AUTH_AUDIENCE"
DEFAULT_AUDIENCE = "authenticated"
LEEWAY_S = 30


class AuthRefused(Exception):
    pass


@dataclass(frozen=True)
class Identity:
    subject: str
    email: str


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> Any:
    import jwt

    return jwt.PyJWKClient(url, cache_keys=True, lifespan=600)


def verify(token: str, env: Optional[Mapping[str, str]] = None, *, now: Optional[float] = None) -> Identity:
    import jwt

    env = env if env is not None else os.environ
    secret = (env.get(SECRET_ENV) or "").strip()
    jwks_url = (env.get(JWKS_ENV) or "").strip()
    if not secret and not jwks_url:
        raise AuthRefused("viewer sign-in is not configured")
    raw = str(token or "").strip()
    if not raw or raw.count(".") != 2:
        raise AuthRefused("malformed token")
    options: dict[str, Any] = {"require": ["exp", "sub", "aud"]}
    issuer = (env.get(ISSUER_ENV) or "").strip() or None
    audience = (env.get(AUDIENCE_ENV) or "").strip() or DEFAULT_AUDIENCE
    try:
        header = jwt.get_unverified_header(raw)
        alg = str(header.get("alg") or "")
        if alg == "HS256":
            if not secret:
                raise AuthRefused("unexpected token type")
            key: Any = secret
            algorithms = ["HS256"]
        elif alg in ("RS256", "ES256"):
            if not jwks_url:
                raise AuthRefused("unexpected token type")
            key = _jwks_client(jwks_url).get_signing_key_from_jwt(raw).key
            algorithms = [alg]
        else:
            raise AuthRefused("unexpected token type")
        claims = jwt.decode(raw, key=key, algorithms=algorithms, audience=audience, issuer=issuer,
                            leeway=LEEWAY_S, options=options)
    except AuthRefused:
        raise
    except jwt.PyJWTError as exc:
        raise AuthRefused(f"token refused: {type(exc).__name__}") from exc
    if now is not None and float(claims.get("exp", 0)) + LEEWAY_S < now:
        raise AuthRefused("token refused: ExpiredSignatureError")
    subject = str(claims.get("sub") or "").strip()
    email = str(claims.get("email") or "").strip().lower()
    if not subject or len(subject) > 64 or not email or len(email) > 254:
        raise AuthRefused("the token has no account")
    return Identity(subject=subject, email=email)


__all__ = ["AuthRefused", "Identity", "verify"]
