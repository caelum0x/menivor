"""Verify Scribase partner tokens (dispatch contract 5.1, Menivor side).

A token is a JWT signed with Ed25519 (``alg: EdDSA``) with a ``kid`` header.
Claims: ``iss`` = ``https://api.scribase.com``; ``aud`` one of ``menivor``,
``rally``, ``railyard``; ``sub`` the Scribase project id; ``org`` the
Scribase org id; ``cap`` one of ``launch-video``, ``mail``, ``deploy``,
``analytics``; ``jti``; ``iat``; ``exp`` at most 90 days after ``iat``.

* Keys: ``GET <iss>/.well-known/partner-jwks.json``, cached for at most
  :data:`JWKS_TTL_S` (10 minutes). An unknown ``kid`` refetches once.
* Revocation: ``POST <iss>/v1/partner-tokens/introspect`` with the token,
  answered ``{active, sub, cap, aud, exp}``; each answer is cached for at
  most :data:`INTROSPECT_TTL_S` (60 s), which gives "revoked within 60 s".
  An unreachable introspection endpoint fails closed.

Configuration (names only): ``SCRIBASE_PARTNER_ISSUER``,
``SCRIBASE_PARTNER_JWKS_URL``, ``SCRIBASE_PARTNER_INTROSPECT_URL`` (derived
from the issuer when unset) and optional ``SCRIBASE_PARTNER_INTROSPECT_KEY``
(Bearer for the introspection call).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

DEFAULT_ISSUER = "https://api.scribase.com"
JWKS_PATH = "/.well-known/partner-jwks.json"
INTROSPECT_PATH = "/v1/partner-tokens/introspect"
AUDIENCES = frozenset({"menivor", "rally", "railyard"})
CAPABILITIES = frozenset({"launch-video", "mail", "deploy", "analytics"})
MAX_LIFETIME_S = 90 * 24 * 3600
JWKS_TTL_S = 600.0
INTROSPECT_TTL_S = 60.0
#: An unknown ``kid`` refetches the key set at most this often, so random key
#: ids in forged tokens cannot turn each request into a JWKS fetch.
KID_MISS_REFETCH_S = 30.0
LEEWAY_S = 30
_TIMEOUT_S = 5.0

#: ``(url) -> json``
FetchJson = Callable[[str], dict]
#: ``(url, json_body, headers) -> json``
PostJson = Callable[[str, dict, dict], dict]


class PartnerTokenError(Exception):
    """A refused token. ``code`` is stable for clients; nothing secret leaks."""

    def __init__(self, code: str, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class PartnerClaims:
    issuer: str
    audience: str
    capability: str
    project_id: str
    org_id: str
    jti: str
    issued_at: int
    expires_at: int
    #: Contract 5.4 (Wave P PM1.5): an add-on grant, e.g. ``addon-monthly-reel``, and its ``YYYY-MM``.
    grant: str = ""
    grant_period: str = ""


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip().rstrip("/")


def issuer() -> str:
    return _env("SCRIBASE_PARTNER_ISSUER", DEFAULT_ISSUER)


def jwks_url() -> str:
    return _env("SCRIBASE_PARTNER_JWKS_URL") or f"{issuer()}{JWKS_PATH}"


def introspect_url() -> str:
    return _env("SCRIBASE_PARTNER_INTROSPECT_URL") or f"{issuer()}{INTROSPECT_PATH}"


def _http_get_json(url: str) -> dict:
    import httpx

    resp = httpx.get(url, timeout=_TIMEOUT_S)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, dict) else {}


def _http_post_json(url: str, body: dict, headers: dict) -> dict:
    import httpx

    resp = httpx.post(url, json=body, headers=headers, timeout=_TIMEOUT_S)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, dict) else {}


class ScribaseTokenVerifier:
    """Verifies partner tokens with cached JWKS and cached introspection."""

    def __init__(
        self,
        *,
        fetch_json: FetchJson | None = None,
        post_json: PostJson | None = None,
        clock: Callable[[], float] | None = None,
        expected_issuer: str | None = None,
    ) -> None:
        self._fetch = fetch_json or _http_get_json
        self._post = post_json or _http_post_json
        self._clock = clock or time.time
        self._issuer = expected_issuer or issuer()
        self._lock = threading.Lock()
        self._keys: dict[str, Any] = {}
        self._keys_at = -1e18
        self._miss_refetch_at = -1e18
        self._introspected: dict[str, tuple[float, dict]] = {}

    # -- keys --------------------------------------------------------------
    def _load_keys(self) -> None:
        from jwt.algorithms import OKPAlgorithm

        try:
            doc = self._fetch(jwks_url())
        except Exception as exc:  # noqa: BLE001 - no keys -> refuse, never accept
            raise PartnerTokenError("jwks_unavailable", "partner keys are unavailable", 503) from exc
        keys: dict[str, Any] = {}
        for jwk in doc.get("keys", []) if isinstance(doc, dict) else []:
            if not isinstance(jwk, dict) or jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519":
                continue
            kid = str(jwk.get("kid") or "")
            if kid:
                keys[kid] = OKPAlgorithm.from_jwk(json.dumps(jwk))
        self._keys = keys
        self._keys_at = self._clock()

    def _key(self, kid: str) -> Any:
        with self._lock:
            fresh = self._clock() - self._keys_at < JWKS_TTL_S
            if not fresh:
                self._load_keys()
            key = self._keys.get(kid)
            now = self._clock()
            if key is None and fresh and now - self._miss_refetch_at >= KID_MISS_REFETCH_S:
                # A rotated key: refetch once before refusing (rate limited).
                self._miss_refetch_at = now
                self._load_keys()
                key = self._keys.get(kid)
        if key is None:
            raise PartnerTokenError("unknown_key", "the token was signed with an unknown key")
        return key

    # -- introspection -------------------------------------------------------
    def _introspect(self, token: str) -> dict:
        digest = hashlib.sha256(token.encode()).hexdigest()
        now = self._clock()
        with self._lock:
            cached = self._introspected.get(digest)
            if cached and now - cached[0] < INTROSPECT_TTL_S:
                return cached[1]
        headers = {"Content-Type": "application/json"}
        key = _env("SCRIBASE_PARTNER_INTROSPECT_KEY")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            answer = self._post(introspect_url(), {"token": token}, headers)
        except Exception as exc:  # noqa: BLE001 - revocation unknown -> fail closed
            raise PartnerTokenError("introspection_unavailable", "partner check is unavailable", 503) from exc
        answer = answer if isinstance(answer, dict) else {}
        with self._lock:
            self._introspected[digest] = (now, answer)
            if len(self._introspected) > 10_000:
                self._introspected.clear()
        return answer

    # -- verify --------------------------------------------------------------
    def verify(self, token: str, *, audience: str, capability: str) -> PartnerClaims:
        import jwt

        token = str(token or "").strip()
        if not token or len(token) > 4096:
            raise PartnerTokenError("malformed", "a partner token is required")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise PartnerTokenError("malformed", "the partner token is malformed") from exc
        if header.get("alg") != "EdDSA":
            raise PartnerTokenError("bad_algorithm", "the partner token must be signed with EdDSA")
        kid = str(header.get("kid") or "")
        if not kid:
            raise PartnerTokenError("missing_kid", "the partner token has no key id")
        key = self._key(kid)
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=["EdDSA"],
                audience=audience,
                issuer=self._issuer,
                leeway=LEEWAY_S,
                # Time checks run below against the verifier's clock.
                options={
                    "require": ["iss", "aud", "sub", "exp", "iat", "jti"],
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
        except jwt.InvalidAudienceError as exc:
            raise PartnerTokenError("wrong_audience", "the partner token is not for Menivor", 403) from exc
        except jwt.InvalidIssuerError as exc:
            raise PartnerTokenError("wrong_issuer", "the partner token has the wrong issuer") from exc
        except jwt.PyJWTError as exc:
            raise PartnerTokenError("invalid", "the partner token is not valid") from exc
        cap = str(claims.get("cap") or "")
        if cap not in CAPABILITIES or cap != capability:
            raise PartnerTokenError("wrong_capability", "the partner token does not allow this action", 403)
        iat, exp = int(claims["iat"]), int(claims["exp"])
        if exp <= self._clock() - LEEWAY_S:
            raise PartnerTokenError("expired", "the partner link has expired")
        if exp - iat > MAX_LIFETIME_S:
            raise PartnerTokenError("lifetime_too_long", "the partner token lives longer than 90 days")
        if iat > self._clock() + LEEWAY_S:
            raise PartnerTokenError("not_yet_valid", "the partner token is not valid yet")
        answer = self._introspect(token)
        if answer.get("active") is not True:
            raise PartnerTokenError("revoked", "the partner link was revoked")
        if str(answer.get("cap") or cap) != cap or str(answer.get("sub") or claims["sub"]) != str(claims["sub"]):
            raise PartnerTokenError("revoked", "the partner link no longer matches")
        aud = claims.get("aud")
        return PartnerClaims(
            issuer=str(claims["iss"]),
            audience=audience if isinstance(aud, list) else str(aud),
            capability=cap,
            project_id=str(claims["sub"]),
            org_id=str(claims.get("org") or ""),
            jti=str(claims["jti"]),
            issued_at=iat,
            expires_at=exp,
            grant=str(claims.get("grant") or ""),
            grant_period=str(claims.get("grant_period") or ""),
        )


_DEFAULT: ScribaseTokenVerifier | None = None
_DEFAULT_LOCK = threading.Lock()


def default_verifier() -> ScribaseTokenVerifier:
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = ScribaseTokenVerifier()
        return _DEFAULT
