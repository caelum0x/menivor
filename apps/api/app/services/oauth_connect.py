"""Provider-agnostic OAuth account-connect flow (Direct-Publish).

Behind this service a creator connects a social platform (TikTok / Instagram /
YouTube) so a finished reel can be posted straight to their account. It owns four
steps of the OAuth authorization-code flow plus token storage:

    build_authorize_url()  -> where to send the browser (carries the CSRF state)
    exchange_code()        -> swap the returned ?code=... for tokens (network)
    store_account()        -> encrypt + persist the tokens (one row per user+provider)
    refresh_if_needed()    -> transparently refresh an expired access token

Network isolation (prod-critical safety)
-----------------------------------------
The only steps that touch the network — :func:`exchange_code` and the refresh
inside :func:`refresh_if_needed` — go through an injectable
:class:`OAuthProviderClient` seam. The default client is a small, explicit HTTP
implementation for TikTok, Instagram, and YouTube. It validates credentials
before opening a socket, has a short timeout, and turns provider/network errors
into typed OAuth errors. Tests inject a mock client and never hit a provider.

Token secrecy
-------------
:func:`store_account` encrypts the access/refresh tokens via
:mod:`app.services.crypto_tokens` before they reach the DB; :func:`load_tokens`
decrypts on read. Plaintext tokens live only in memory, never in a row.

CSRF ``state`` contract (opaque, single-use)
--------------------------------------------
OAuth ``state`` defends the redirect against CSRF. The contract the CONTROLLER
must uphold (this service provides the primitives, not the storage):

    1. BEFORE redirect: mint an opaque, unguessable token with
       :func:`generate_state` (or ``store.issue()``) and persist it bound to the
       browser session / user (a short-TTL server-side store — Redis, signed
       cookie, or DB). Pass it to :func:`build_authorize_url`.
    2. Put NOTHING sensitive in ``state`` — it is opaque and round-trips through
       the provider and the user's browser.
    3. ON callback: read ``state`` from the query string and
       :meth:`SingleUseStateStore.consume` it. ``consume`` returns ``True``
       exactly ONCE per issued state and ``False`` for an unknown / already-used
       / blank value. A ``False`` MUST abort the callback (potential CSRF / replay)
       before any :func:`exchange_code`.
    4. Single-use: a consumed state is immediately invalidated so a replayed
       callback (same ``state`` twice) is rejected.

:class:`RedisSingleUseStateStore` is the production implementation: it stores
each opaque state in Redis with a short TTL and consumes it atomically.
:class:`SingleUseStateStore` remains an in-memory test/reference implementation.

Config/env keys (names only; NEVER hardcoded)
---------------------------------------------
Per provider ``<p>`` in {tiktok, instagram, youtube}, read from env first then
``config.app`` (env ``<P>_CLIENT_ID`` / ``<P>_CLIENT_SECRET``; config
``<p>_client_id`` / ``<p>_client_secret``). The token-encryption key is
``SOCIAL_TOKEN_KEY`` (see :mod:`app.services.crypto_tokens`). Presence is
validated at use — a missing client id raises :class:`OAuthConfigError`.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlencode

from loguru import logger

from app.config import config
from app.models.db.repositories import SOCIAL_PROVIDERS, _normalize_provider
from app.services import crypto_tokens

#: Provider OAuth *authorize* endpoints (where the browser is sent). The token
#: exchange / refresh endpoints live behind the injectable client seam.
_AUTHORIZE_ENDPOINTS: dict[str, str] = {
    "tiktok": "https://www.tiktok.com/v2/auth/authorize/",
    "instagram": "https://api.instagram.com/oauth/authorize",
    "youtube": "https://accounts.google.com/o/oauth2/v2/auth",
}

#: Default OAuth scopes requested per provider when the caller does not override.
_DEFAULT_SCOPES: dict[str, str] = {
    "tiktok": "user.info.basic,video.publish",
    "instagram": "instagram_basic,instagram_content_publish",
    "youtube": "https://www.googleapis.com/auth/youtube.upload",
}

#: Read-only scopes that let Menivor read each published post's numbers
#: (views, likes, comments, watch time) for the Results page. Requested on every
#: connect so a creator never has to type their numbers. An operator whose
#: platform app has not been approved for one of these can drop it with
#: ``OAUTH_METRICS_SCOPES_OFF=tiktok,instagram`` (or config
#: ``app.oauth_metrics_scopes_off``) so connecting keeps working.
_METRICS_SCOPES: dict[str, tuple[str, ...]] = {
    "tiktok": ("video.list",),
    "instagram": ("instagram_manage_insights",),
    "youtube": (
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    ),
}
_SCOPE_SEPARATOR: dict[str, str] = {"tiktok": ",", "instagram": ",", "youtube": " "}

_TOKEN_ENDPOINTS: dict[str, str] = {
    "tiktok": "https://open.tiktokapis.com/v2/oauth/token/",
    "instagram": "https://api.instagram.com/oauth/access_token",
    "youtube": "https://oauth2.googleapis.com/token",
}
_INSTAGRAM_REFRESH_ENDPOINT = "https://graph.instagram.com/refresh_access_token"


class OAuthError(Exception):
    """Base class for an account-connect flow failure."""


class OAuthConfigError(OAuthError):
    """Raised when required provider credentials are not configured (config/env)."""


class OAuthRefreshError(OAuthError):
    """Raised when an expired token cannot be refreshed (no refresh token)."""


class OAuthStateStoreError(OAuthError):
    """Raised when the shared CSRF-state store cannot be reached safely."""


@dataclass(frozen=True)
class OAuthTokens:
    """The credentials returned by an exchange/refresh, before encryption.

    ``expires_at`` is an aware UTC datetime (nullable when the provider does not
    disclose an expiry). ``refresh_token`` is nullable — not every provider issues
    one. Instances are immutable (frozen) so a token bundle is never mutated in
    place.
    """

    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    scopes: str = ""
    external_account_id: str = ""


@runtime_checkable
class OAuthProviderClient(Protocol):
    """The network seam: swaps an auth ``code`` (or refresh token) for tokens.

    Implementations perform the real provider HTTP calls; tests supply a mock.
    Both methods return a raw provider token dict which
    :func:`_tokens_from_response` normalizes into :class:`OAuthTokens`.
    """

    def exchange_code(
        self, provider: str, code: str, redirect_uri: str
    ) -> dict[str, Any]:
        """Exchange an authorization ``code`` for a raw token dict."""
        ...

    def refresh_token(
        self, provider: str, refresh_token: str
    ) -> dict[str, Any]:
        """Exchange a ``refresh_token`` for a fresh raw token dict."""


class RequestsOAuthProviderClient:
    """Production OAuth token client for TikTok, Instagram, and YouTube.

    A provider's credentials are read only when the relevant action is invoked;
    missing configuration therefore fails before any network call. ``http`` is
    injectable for hermetic tests and must expose ``post`` / ``get`` compatible
    with :mod:`requests`.
    """

    def __init__(self, http: Any | None = None, timeout_s: float | None = None) -> None:
        self._http = http
        self._timeout_s = timeout_s

    def _timeout(self) -> float:
        if self._timeout_s is not None:
            return max(0.1, float(self._timeout_s))
        try:
            return max(0.1, float(config.app.get("reelforge_oauth_http_timeout_s", 10)))
        except (TypeError, ValueError):
            return 10.0

    def _requests(self) -> Any:
        if self._http is not None:
            return self._http
        try:
            import requests

            return requests
        except Exception as exc:  # pragma: no cover - dependency is installed in prod
            raise OAuthConfigError(f"OAuth HTTP client is unavailable: {exc}") from exc

    @staticmethod
    def _response_json(response: Any, provider: str) -> dict[str, Any]:
        try:
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise OAuthError(f"{provider} OAuth token request failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise OAuthError(f"{provider} OAuth token response was not a JSON object")
        if payload.get("error"):
            detail = payload.get("error_description") or payload.get("error")
            raise OAuthError(f"{provider} OAuth token request was rejected: {detail}")
        return payload

    @staticmethod
    def _credentials(provider: str) -> tuple[str, str]:
        client_id = _client_id(provider)
        client_secret = _client_secret(provider)
        return client_id, client_secret

    def exchange_code(
        self, provider: str, code: str, redirect_uri: str
    ) -> dict[str, Any]:
        client_id, client_secret = self._credentials(provider)
        if provider == "tiktok":
            form = {
                "client_key": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            }
        else:
            form = {
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            }
        response = self._requests().post(
            _TOKEN_ENDPOINTS[provider], data=form, timeout=self._timeout()
        )
        return self._response_json(response, provider)

    def refresh_token(
        self, provider: str, refresh_token: str
    ) -> dict[str, Any]:
        client_id, client_secret = self._credentials(provider)
        http = self._requests()
        if provider == "instagram":
            # Instagram's long-lived-token refresh endpoint authenticates with
            # the existing access token; retain the client-credential validation
            # above so every live provider requires an explicit app configuration.
            response = http.get(
                _INSTAGRAM_REFRESH_ENDPOINT,
                params={"grant_type": "ig_refresh_token", "access_token": refresh_token},
                timeout=self._timeout(),
            )
        elif provider == "tiktok":
            response = http.post(
                _TOKEN_ENDPOINTS[provider],
                data={
                    "client_key": client_id,
                    "client_secret": client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                timeout=self._timeout(),
            )
        else:
            response = http.post(
                _TOKEN_ENDPOINTS[provider],
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                timeout=self._timeout(),
            )
        return self._response_json(response, provider)


#: Module-level default. A real client is used only after credentials validate;
#: callers may still inject a mock client for tests or a custom transport.
_DEFAULT_CLIENT: OAuthProviderClient = RequestsOAuthProviderClient()


# --------------------------------------------------------------------------- #
# CSRF state primitives
# --------------------------------------------------------------------------- #
def generate_state(nbytes: int = 32) -> str:
    """Return an opaque, unguessable URL-safe CSRF ``state`` token.

    Backed by :func:`secrets.token_urlsafe` (CSPRNG). The controller persists this
    bound to the browser session before redirect and validates it on callback
    (see the module CSRF contract).
    """
    return secrets.token_urlsafe(max(16, int(nbytes)))


class SingleUseStateStore:
    """In-memory, single-use CSRF ``state`` store (reference implementation).

    :meth:`issue` mints and remembers a state; :meth:`consume` returns ``True``
    exactly once for an issued state and ``False`` for an unknown / already-used /
    blank value — enforcing the single-use half of the CSRF contract. Suitable for
    a single process and for tests; production should back the same contract with
    a shared, expiring store (e.g. Redis).
    """

    def __init__(self) -> None:
        self._issued: set[str] = set()

    def issue(self, nbytes: int = 32) -> str:
        """Mint, remember, and return a fresh opaque state token."""
        state = generate_state(nbytes)
        self._issued.add(state)
        return state

    def consume(self, state: str | None) -> bool:
        """Validate + invalidate a state; ``True`` only on its first valid use."""
        if not state or state not in self._issued:
            return False
        self._issued.discard(state)  # single-use: invalidate immediately
        return True


_CONSUME_STATE_LUA = """
if redis.call('GET', KEYS[1]) then
    redis.call('DEL', KEYS[1])
    return 1
end
return 0
"""


class RedisSingleUseStateStore:
    """Redis-backed, expiring, single-use OAuth CSRF state store.

    Redis is mandatory for this security boundary: errors deliberately raise
    :class:`OAuthStateStoreError` instead of falling back to process memory.
    ``consume`` uses one Lua operation so two callbacks cannot both validate a
    state token between a separate read and delete.
    """

    _PREFIX = "reelforge:oauth:state:"

    def __init__(self, client: Any, ttl_s: int = 600) -> None:
        self._client = client
        self._ttl_s = max(1, int(ttl_s))

    @classmethod
    def from_config(cls) -> "RedisSingleUseStateStore":
        """Build a short-timeout Redis client from the shared app config."""
        try:
            import redis

            app_cfg = config.app
            client = redis.Redis(
                host=app_cfg.get("redis_host", "localhost"),
                port=int(app_cfg.get("redis_port", 6379)),
                db=int(app_cfg.get("redis_db", 0)),
                password=app_cfg.get("redis_password", "") or None,
                socket_timeout=0.25,
                socket_connect_timeout=0.25,
                decode_responses=False,
            )
            ttl_s = int(app_cfg.get("reelforge_oauth_state_ttl_s", 600))
            return cls(client, ttl_s)
        except Exception as exc:
            raise OAuthStateStoreError(
                f"unable to initialize Redis OAuth state store: {exc}"
            ) from exc

    def _key(self, state: str) -> str:
        return f"{self._PREFIX}{state}"

    def issue(self, nbytes: int = 32) -> str:
        """Persist a newly minted state with TTL, or fail closed on Redis error."""
        try:
            # Collision is extraordinarily unlikely, but SET NX makes the
            # guarantee explicit and keeps a malicious pre-created key harmless.
            for _ in range(3):
                state = generate_state(nbytes)
                if self._client.set(self._key(state), b"1", nx=True, ex=self._ttl_s):
                    return state
        except Exception as exc:
            raise OAuthStateStoreError(
                f"Redis OAuth state issuance failed: {exc}"
            ) from exc
        raise OAuthStateStoreError("could not reserve a unique OAuth state")

    def consume(self, state: str | None) -> bool:
        """Atomically validate and invalidate ``state`` (fail closed on error)."""
        if not state:
            return False
        try:
            return bool(self._client.eval(_CONSUME_STATE_LUA, 1, self._key(state)))
        except Exception as exc:
            raise OAuthStateStoreError(
                f"Redis OAuth state consume failed: {exc}"
            ) from exc


# --------------------------------------------------------------------------- #
# Provider credential resolution (config/env only)
# --------------------------------------------------------------------------- #
def _provider_credential(provider: str, suffix: str) -> str:
    """Read a provider credential from env, then ``config.app`` (``""`` if unset).

    ``suffix`` is ``"id"`` or ``"secret"``. Env ``<PROVIDER>_CLIENT_<SUFFIX>``
    wins over config ``<provider>_client_<suffix>``. Never raises.
    """
    env_name = f"{provider.upper()}_CLIENT_{suffix.upper()}"
    env = os.getenv(env_name, "").strip()
    if env:
        return env
    try:
        from app.config import config

        return str(
            config.app.get(f"{provider}_client_{suffix}", "") or ""
        ).strip()
    except Exception:  # pragma: no cover - config always bound in practice
        return ""


def _client_id(provider: str) -> str:
    """Return the provider's OAuth client id or raise :class:`OAuthConfigError`."""
    value = _provider_credential(provider, "id")
    if not value:
        raise OAuthConfigError(
            f"missing OAuth client id for {provider!r}: set "
            f"{provider.upper()}_CLIENT_ID or config.app['{provider}_client_id']"
        )
    return value


def client_configured(provider: str) -> bool:
    """True when the operator set an OAuth client id for ``provider``."""
    return bool(_provider_credential(provider, "id"))


def _client_secret(provider: str) -> str:
    """Return a provider secret or fail before a network token request."""
    value = _provider_credential(provider, "secret")
    if not value:
        raise OAuthConfigError(
            f"missing OAuth client secret for {provider!r}: set "
            f"{provider.upper()}_CLIENT_SECRET or config.app['{provider}_client_secret']"
        )
    return value


# --------------------------------------------------------------------------- #
# Flow steps
# --------------------------------------------------------------------------- #
def build_authorize_url(
    provider: str, state: str, redirect_uri: str, *, scopes: str = ""
) -> str:
    """Build the provider authorize URL to send the browser to.

    ``provider`` is validated to :data:`SOCIAL_PROVIDERS`. ``state`` (opaque CSRF
    token) and ``redirect_uri`` must both be non-empty. The provider's client id
    is read from config/env (raising :class:`OAuthConfigError` when absent).
    ``scopes`` overrides the per-provider default. Raises ``ValueError`` on a
    blank ``state`` / ``redirect_uri``.
    """
    normalized = _normalize_provider(provider)
    if not (state or "").strip():
        raise ValueError("state must be a non-empty opaque token")
    if not (redirect_uri or "").strip():
        raise ValueError("redirect_uri must be a non-empty string")

    params = {
        "client_key" if normalized == "tiktok" else "client_id": _client_id(normalized),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
        "scope": (scopes or default_scopes(normalized)),
    }
    if normalized == "youtube":
        # Offline access so scheduled publishing and the Results page keep
        # working after the one-hour access token expires.
        params.update({"access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"})
    return f"{_AUTHORIZE_ENDPOINTS[normalized]}?{urlencode(params)}"


def _metrics_scopes_off() -> set[str]:
    raw = os.getenv("OAUTH_METRICS_SCOPES_OFF", "")
    if not raw.strip():
        try:
            raw = str(config.app.get("oauth_metrics_scopes_off", "") or "")
        except Exception:  # pragma: no cover - config always bound in practice
            raw = ""
    return {part.strip().lower() for part in raw.replace(" ", ",").split(",") if part.strip()}


def default_scopes(provider: str) -> str:
    """Publish scopes plus the read-only stats scopes (unless switched off)."""
    base = _DEFAULT_SCOPES.get(provider, "")
    extra = () if provider in _metrics_scopes_off() else _METRICS_SCOPES.get(provider, ())
    sep = _SCOPE_SEPARATOR.get(provider, " ")
    parts = [p for p in base.split(sep) if p]
    parts += [p for p in extra if p not in parts]
    return sep.join(parts)


def _coerce_expires_at(raw: dict[str, Any]) -> datetime | None:
    """Derive an aware UTC expiry from a provider response.

    Accepts an explicit ``expires_at`` (ISO string or datetime) or a relative
    ``expires_in`` (seconds from now). Returns ``None`` when neither is present or
    parseable — an unknown expiry rather than a wrong one.
    """
    explicit = raw.get("expires_at")
    if isinstance(explicit, datetime):
        return explicit if explicit.tzinfo else explicit.replace(tzinfo=timezone.utc)
    if isinstance(explicit, str) and explicit.strip():
        try:
            parsed = datetime.fromisoformat(explicit.strip())
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    expires_in = raw.get("expires_in")
    if isinstance(expires_in, (int, float)) and expires_in > 0:
        from datetime import timedelta

        return datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
    return None


def _tokens_from_response(raw: dict[str, Any]) -> OAuthTokens:
    """Normalize a raw provider token dict into an :class:`OAuthTokens`.

    Tolerant of the common provider key spellings (``scope``/``scopes``,
    ``open_id``/``user_id``/``external_account_id``). Raises :class:`OAuthError`
    when no access token is present — an unusable connection must never be stored.
    """
    access = str(raw.get("access_token", "") or "").strip()
    if not access:
        raise OAuthError("provider response did not include an access_token")
    refresh = raw.get("refresh_token")
    scopes = raw.get("scopes", raw.get("scope", "")) or ""
    external = (
        raw.get("external_account_id")
        or raw.get("open_id")
        or raw.get("user_id")
        or ""
    )
    return OAuthTokens(
        access_token=access,
        refresh_token=(str(refresh).strip() or None) if refresh else None,
        expires_at=_coerce_expires_at(raw),
        scopes=str(scopes),
        external_account_id=str(external),
    )


def exchange_code(
    provider: str,
    code: str,
    redirect_uri: str,
    *,
    client: OAuthProviderClient | None = None,
) -> OAuthTokens:
    """Swap an authorization ``code`` for :class:`OAuthTokens` (network step).

    ``provider`` is validated to :data:`SOCIAL_PROVIDERS`. The exchange goes
    through the injected ``client`` (or the configured default) so tests never hit
    a real provider. Raises ``ValueError`` on
    a blank ``code`` / ``redirect_uri`` and :class:`OAuthError` when the response
    carries no access token.
    """
    normalized = _normalize_provider(provider)
    if not (code or "").strip():
        raise ValueError("code must be a non-empty string")
    if not (redirect_uri or "").strip():
        raise ValueError("redirect_uri must be a non-empty string")
    active = client or _DEFAULT_CLIENT
    raw = active.exchange_code(normalized, code, redirect_uri)
    return _tokens_from_response(dict(raw or {}))


def store_account(
    session: Any, user_id: str, provider: str, tokens: OAuthTokens
) -> Any:
    """Encrypt ``tokens`` and UPSERT the user's connection for ``provider``.

    The access token (and refresh token, when present) are encrypted via
    :mod:`app.services.crypto_tokens` — a plaintext token never reaches the DB.
    Owner-scoped and idempotent per ``(user_id, provider)`` (the repository UPSERT
    replaces the row's blobs in place). Raises ``ValueError`` on a blank
    ``user_id`` and :class:`~app.services.crypto_tokens.MissingTokenKeyError` when
    no encryption key is configured (so a token is never stored in the clear).
    Returns the persisted :class:`~app.models.db.models.SocialAccount`.
    """
    from app.models.db.repositories import SocialAccountRepository

    if not (user_id or "").strip():
        raise ValueError("user_id must be a non-empty string")

    access_enc = crypto_tokens.encrypt(tokens.access_token)
    refresh_enc = (
        crypto_tokens.encrypt(tokens.refresh_token)
        if tokens.refresh_token
        else None
    )
    repo = SocialAccountRepository(session)
    return repo.upsert(
        user_id=user_id,
        provider=provider,
        access_token_enc=access_enc,
        refresh_token_enc=refresh_enc,
        external_account_id=tokens.external_account_id,
        token_expires_at=tokens.expires_at,
        scopes=tokens.scopes,
    )


def get_account(session: Any, user_id: str, provider: str) -> Any | None:
    """Return the user's :class:`SocialAccount` for ``provider`` (owner-scoped).

    Returns ``None`` when the user has no connection for that provider — a caller
    can never read another creator's connection (the repository scopes by
    ``user_id``).
    """
    from app.models.db.repositories import SocialAccountRepository

    return SocialAccountRepository(session).get(user_id, provider)


def load_tokens(session: Any, user_id: str, provider: str) -> OAuthTokens | None:
    """Return the user's DECRYPTED :class:`OAuthTokens` for ``provider``, or ``None``.

    Owner-scoped: resolves the connection via :func:`get_account` (so another
    creator's tokens are never returned) and decrypts the stored blobs via
    :mod:`app.services.crypto_tokens`. Returns ``None`` when there is no
    connection. Raises :class:`~app.services.crypto_tokens.TokenDecryptError` if a
    stored blob cannot be decrypted (tampered / wrong key).
    """
    account = get_account(session, user_id, provider)
    if account is None:
        return None
    return _decrypt_account(account)


def _decrypt_account(account: Any) -> OAuthTokens:
    """Decrypt a :class:`SocialAccount`'s stored blobs into :class:`OAuthTokens`."""
    access = crypto_tokens.decrypt(account.access_token_enc)
    refresh = (
        crypto_tokens.decrypt(account.refresh_token_enc)
        if account.refresh_token_enc
        else None
    )
    return OAuthTokens(
        access_token=access,
        refresh_token=refresh,
        expires_at=account.token_expires_at,
        scopes=account.scopes or "",
        external_account_id=account.external_account_id or "",
    )


def refresh_if_needed(
    session: Any,
    user_id: str,
    provider: str,
    *,
    now: datetime | None = None,
    leeway_s: int = 60,
    client: OAuthProviderClient | None = None,
) -> Any | None:
    """Refresh + re-store the connection's access token when it is (near) expired.

    Owner-scoped. Returns the current :class:`SocialAccount` unchanged when there
    is no connection (``None``), when the expiry is unknown (``token_expires_at``
    NULL), or when the token is still valid beyond ``leeway_s`` seconds. Otherwise
    it decrypts the refresh token, exchanges it via the injected ``client`` (the
    only network step) and UPSERTs the fresh tokens. ``now`` is injectable for
    deterministic tests. Raises :class:`OAuthRefreshError` when the token is
    expired but no refresh token is stored.
    """
    account = get_account(session, user_id, provider)
    if account is None:
        return None
    expires_at = account.token_expires_at
    if expires_at is None:
        return account  # unknown expiry — nothing to proactively refresh

    moment = now or datetime.now(timezone.utc)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    from datetime import timedelta

    if expires_at - timedelta(seconds=max(0, int(leeway_s))) > moment:
        return account  # still valid

    tokens = _decrypt_account(account)
    if not tokens.refresh_token:
        raise OAuthRefreshError(
            f"access token for {provider!r} is expired and no refresh token is "
            f"stored; the user must re-connect the account"
        )
    active = client or _DEFAULT_CLIENT
    raw = active.refresh_token(_normalize_provider(provider), tokens.refresh_token)
    refreshed = _tokens_from_response(dict(raw or {}))
    # A refresh response may omit the refresh token — keep the existing one.
    if refreshed.refresh_token is None and tokens.refresh_token:
        refreshed = OAuthTokens(
            access_token=refreshed.access_token,
            refresh_token=tokens.refresh_token,
            expires_at=refreshed.expires_at,
            scopes=refreshed.scopes or tokens.scopes,
            external_account_id=(
                refreshed.external_account_id or tokens.external_account_id
            ),
        )
    return store_account(session, user_id, provider, refreshed)


def sweep_expiring_accounts(
    *,
    now: datetime | None = None,
    leeway_s: int = 300,
    limit: int = 100,
    client: OAuthProviderClient | None = None,
    session_scope: Any = None,
) -> dict[str, int]:
    """Proactively refresh a bounded batch of soon-expiring connections.

    The sweep snapshots candidate identities, then refreshes each account in its
    own short transaction. A provider or crypto failure is isolated to that one
    connection; a Celery beat tick never raises or prevents other accounts from
    being refreshed. The normal direct-publish path still calls
    :func:`refresh_if_needed` immediately before publishing as its final guard.
    """
    from datetime import timedelta

    if session_scope is None:
        from app.models.db.base import get_session

        session_scope = get_session

    moment = now or datetime.now(timezone.utc)
    threshold = moment + timedelta(seconds=max(0, int(leeway_s)))
    summary = {"considered": 0, "refreshed": 0, "failed": 0}

    try:
        from app.models.db.repositories import SocialAccountRepository

        with session_scope() as session:
            candidates = [
                (row.user_id, row.provider)
                for row in SocialAccountRepository(session).list_expiring_before(
                    threshold, limit=limit
                )
            ]
    except Exception as exc:  # noqa: BLE001 - periodic sweep is best effort
        logger.warning(f"OAuth token refresh sweep could not build worklist: {exc}")
        return summary

    summary["considered"] = len(candidates)
    for user_id, provider in candidates:
        try:
            with session_scope() as session:
                refreshed = refresh_if_needed(
                    session,
                    user_id,
                    provider,
                    now=moment,
                    leeway_s=leeway_s,
                    client=client,
                )
                if refreshed is not None:
                    summary["refreshed"] += 1
        except Exception as exc:  # noqa: BLE001 - one account never aborts batch
            summary["failed"] += 1
            logger.warning(
                f"OAuth token refresh sweep failed for provider={provider!r}: {exc}"
            )
    return summary


__all__ = [
    "SOCIAL_PROVIDERS",
    "OAuthError",
    "OAuthConfigError",
    "OAuthRefreshError",
    "OAuthStateStoreError",
    "OAuthTokens",
    "OAuthProviderClient",
    "SingleUseStateStore",
    "RedisSingleUseStateStore",
    "generate_state",
    "build_authorize_url",
    "exchange_code",
    "store_account",
    "get_account",
    "load_tokens",
    "refresh_if_needed",
    "sweep_expiring_accounts",
]
