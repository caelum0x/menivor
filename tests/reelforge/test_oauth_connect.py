"""Tests for Direct-Publish OAuth account-connect (models / repo / services).

Exercises the AUTH-CRITICAL account-connect stack against an in-memory SQLite DB
(no Postgres / Redis / network):

* :mod:`app.services.crypto_tokens` — token round-trips (ciphertext != plaintext,
  decrypt restores), and a clean typed error when no key is configured.
* :class:`SocialAccountRepository` / :func:`oauth_connect.store_account` — the
  connection is a per-(user, provider) UPSERT (one row, updated in place), stored
  ENCRYPTED (never plaintext), read back decrypted, and strictly owner-scoped (a
  different user cannot read another user's account).
* :mod:`app.services.oauth_connect` — ``exchange_code`` via a MOCK provider client
  (no real network), the single-use CSRF ``state`` contract, and provider
  validation.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.base import Base
from app.models.db.models import SocialAccount, User
from app.models.db.repositories import SocialAccountRepository
from app.services import crypto_tokens, oauth_connect

_TEST_TOKEN_KEY = "test-social-token-key-do-not-use-in-prod"


@pytest.fixture()
def factory() -> Iterator[sessionmaker]:
    """In-memory SQLite session factory with the ORM schema created."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )
    engine.dispose()


@contextmanager
def _session(factory: sessionmaker) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _token_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject a token-encryption key via env (the documented test injection)."""
    monkeypatch.setenv("SOCIAL_TOKEN_KEY", _TEST_TOKEN_KEY)


def _make_user(factory: sessionmaker, email: str) -> str:
    with _session(factory) as s:
        user = User(email=email, credits=0)
        s.add(user)
        s.flush()
        return user.id


class _MockProviderClient:
    """A mock :class:`OAuthProviderClient` — records calls, returns canned tokens."""

    def __init__(self, exchange: dict[str, Any] | None = None,
                 refresh: dict[str, Any] | None = None) -> None:
        self._exchange = exchange or {}
        self._refresh = refresh or {}
        self.calls: list[tuple[str, ...]] = []

    def exchange_code(self, provider: str, code: str, redirect_uri: str) -> dict:
        self.calls.append(("exchange", provider, code, redirect_uri))
        return dict(self._exchange)

    def refresh_token(self, provider: str, refresh_token: str) -> dict:
        self.calls.append(("refresh", provider, refresh_token))
        return dict(self._refresh)


# --------------------------------------------------------------------------- #
# crypto_tokens — round-trip + missing key
# --------------------------------------------------------------------------- #
def test_encrypt_decrypt_round_trip() -> None:
    plaintext = "ya29.super-secret-access-token"
    blob = crypto_tokens.encrypt(plaintext)
    # Ciphertext must not equal (or contain) the plaintext.
    assert blob != plaintext
    assert plaintext not in blob
    # Decrypt restores the exact original.
    assert crypto_tokens.decrypt(blob) == plaintext


def test_encrypt_is_nondeterministic_but_decrypts() -> None:
    # Fernet embeds a random IV so two encryptions differ, yet both decrypt back.
    a = crypto_tokens.encrypt("same-token")
    b = crypto_tokens.encrypt("same-token")
    assert a != b
    assert crypto_tokens.decrypt(a) == "same-token"
    assert crypto_tokens.decrypt(b) == "same-token"


def test_missing_key_raises_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    # No env key and no config secret -> a clean, typed MissingTokenKeyError.
    monkeypatch.delenv("SOCIAL_TOKEN_KEY", raising=False)
    monkeypatch.setattr(crypto_tokens, "_resolve_secret", lambda: "")
    with pytest.raises(crypto_tokens.MissingTokenKeyError):
        crypto_tokens.encrypt("token")
    with pytest.raises(crypto_tokens.MissingTokenKeyError):
        crypto_tokens.decrypt("gAAAAA-anything")


def test_decrypt_tampered_blob_raises() -> None:
    # A malformed / non-Fernet blob must surface a clean typed decrypt error
    # rather than a partially-decrypted value or a raw cryptography exception.
    with pytest.raises(crypto_tokens.TokenDecryptError):
        crypto_tokens.decrypt("this-is-not-a-valid-fernet-token")
    # Corrupting the authenticated ciphertext body also fails the HMAC check.
    blob = crypto_tokens.encrypt("token")
    corrupted = blob[:20] + ("A" if blob[20] != "A" else "B") + blob[21:]
    with pytest.raises(crypto_tokens.TokenDecryptError):
        crypto_tokens.decrypt(corrupted)


# --------------------------------------------------------------------------- #
# store_account — per-user upsert, encrypted at rest, decrypt on read
# --------------------------------------------------------------------------- #
def test_store_account_upserts_one_row_per_user_provider(
    factory: sessionmaker,
) -> None:
    user_id = _make_user(factory, "connect@example.com")
    with _session(factory) as s:
        oauth_connect.store_account(
            s, user_id, "tiktok",
            oauth_connect.OAuthTokens(access_token="tok-1", scopes="video.publish"),
        )
    # Re-connect the SAME provider with fresh tokens -> updates in place.
    with _session(factory) as s:
        oauth_connect.store_account(
            s, user_id, "tiktok",
            oauth_connect.OAuthTokens(
                access_token="tok-2", refresh_token="ref-2",
                external_account_id="open-123",
            ),
        )
    with _session(factory) as s:
        count = s.execute(
            select(func.count())
            .select_from(SocialAccount)
            .where(
                SocialAccount.user_id == user_id,
                SocialAccount.provider == "tiktok",
            )
        ).scalar_one()
        assert count == 1  # UNIQUE(user_id, provider) — upsert, never duplicated
        tokens = oauth_connect.load_tokens(s, user_id, "tiktok")
        assert tokens is not None
        assert tokens.access_token == "tok-2"
        assert tokens.refresh_token == "ref-2"
        assert tokens.external_account_id == "open-123"


def test_store_account_persists_ciphertext_not_plaintext(
    factory: sessionmaker,
) -> None:
    user_id = _make_user(factory, "cipher@example.com")
    plaintext = "plaintext-access-token-value"
    with _session(factory) as s:
        oauth_connect.store_account(
            s, user_id, "instagram",
            oauth_connect.OAuthTokens(
                access_token=plaintext, refresh_token="refresh-plain"
            ),
        )
    with _session(factory) as s:
        row = s.execute(
            select(SocialAccount).where(SocialAccount.user_id == user_id)
        ).scalars().one()
        # The raw columns must NOT contain the plaintext tokens.
        assert row.access_token_enc != plaintext
        assert plaintext not in row.access_token_enc
        assert row.refresh_token_enc is not None
        assert "refresh-plain" not in row.refresh_token_enc
        # But they decrypt back to the originals.
        assert crypto_tokens.decrypt(row.access_token_enc) == plaintext
        assert crypto_tokens.decrypt(row.refresh_token_enc) == "refresh-plain"


def test_get_account_decrypts_via_load_tokens(factory: sessionmaker) -> None:
    user_id = _make_user(factory, "decrypt@example.com")
    with _session(factory) as s:
        oauth_connect.store_account(
            s, user_id, "youtube",
            oauth_connect.OAuthTokens(
                access_token="yt-access", refresh_token="yt-refresh",
                scopes="youtube.upload",
            ),
        )
    with _session(factory) as s:
        account = oauth_connect.get_account(s, user_id, "youtube")
        assert account is not None and account.provider == "youtube"
        tokens = oauth_connect.load_tokens(s, user_id, "youtube")
        assert tokens is not None
        assert tokens.access_token == "yt-access"
        assert tokens.refresh_token == "yt-refresh"
        assert tokens.scopes == "youtube.upload"


def test_other_user_cannot_read_account(factory: sessionmaker) -> None:
    owner = _make_user(factory, "owner@example.com")
    intruder = _make_user(factory, "intruder@example.com")
    with _session(factory) as s:
        oauth_connect.store_account(
            s, owner, "tiktok",
            oauth_connect.OAuthTokens(access_token="owner-only-token"),
        )
    with _session(factory) as s:
        # The owner sees their connection...
        assert oauth_connect.get_account(s, owner, "tiktok") is not None
        # ...a different user gets None for the SAME provider (owner-scoped).
        assert oauth_connect.get_account(s, intruder, "tiktok") is None
        assert oauth_connect.load_tokens(s, intruder, "tiktok") is None
        # list_for_user is likewise scoped.
        assert SocialAccountRepository(s).list_for_user(intruder) == []


def test_store_account_missing_key_never_persists_plaintext(
    factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    # With no key configured, store_account raises BEFORE any row is written.
    monkeypatch.delenv("SOCIAL_TOKEN_KEY", raising=False)
    monkeypatch.setattr(crypto_tokens, "_resolve_secret", lambda: "")
    user_id = _make_user(factory, "nokey@example.com")
    with _session(factory) as s:
        with pytest.raises(crypto_tokens.MissingTokenKeyError):
            oauth_connect.store_account(
                s, user_id, "tiktok",
                oauth_connect.OAuthTokens(access_token="should-not-persist"),
            )
    with _session(factory) as s:
        count = s.execute(
            select(func.count()).select_from(SocialAccount)
        ).scalar_one()
        assert count == 0


def test_invalid_provider_rejected(factory: sessionmaker) -> None:
    user_id = _make_user(factory, "badprovider@example.com")
    with _session(factory) as s:
        with pytest.raises(ValueError):
            oauth_connect.store_account(
                s, user_id, "myspace",
                oauth_connect.OAuthTokens(access_token="tok"),
            )


# --------------------------------------------------------------------------- #
# exchange_code — mocked provider client (no real network)
# --------------------------------------------------------------------------- #
def test_exchange_code_uses_injected_client() -> None:
    client = _MockProviderClient(
        exchange={
            "access_token": "exchanged-access",
            "refresh_token": "exchanged-refresh",
            "expires_in": 3600,
            "scope": "video.publish",
            "open_id": "tt-open-42",
        }
    )
    tokens = oauth_connect.exchange_code(
        "tiktok", "auth-code-abc", "https://app/callback", client=client
    )
    assert tokens.access_token == "exchanged-access"
    assert tokens.refresh_token == "exchanged-refresh"
    assert tokens.scopes == "video.publish"
    assert tokens.external_account_id == "tt-open-42"
    assert tokens.expires_at is not None
    assert client.calls == [("exchange", "tiktok", "auth-code-abc", "https://app/callback")]


def test_default_client_refuses_network_without_config() -> None:
    # The prod-critical path must fail before a network call when unconfigured.
    with pytest.raises(oauth_connect.OAuthConfigError):
        oauth_connect.exchange_code("tiktok", "code", "https://app/callback")


class _FakeOAuthResponse:
    def __init__(self, payload: dict, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error

    def raise_for_status(self) -> None:
        if self.error is not None:
            raise self.error

    def json(self) -> dict:
        return self.payload


class _FakeOAuthHTTP:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def post(self, url, *, data, timeout):
        self.calls.append(("post", url, data, timeout))
        return _FakeOAuthResponse({"access_token": "access", "expires_in": 3600})

    def get(self, url, *, params, timeout):
        self.calls.append(("get", url, params, timeout))
        return _FakeOAuthResponse({"access_token": "refreshed", "expires_in": 3600})


def test_live_client_uses_tiktok_v2_form_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIKTOK_CLIENT_ID", "client-key")
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "client-secret")
    http = _FakeOAuthHTTP()
    client = oauth_connect.RequestsOAuthProviderClient(http=http, timeout_s=2)

    raw = client.exchange_code("tiktok", "auth-code", "https://app/callback")
    refreshed = client.refresh_token("tiktok", "refresh-token")

    assert raw["access_token"] == "access"
    assert refreshed["access_token"] == "access"
    assert http.calls == [
        (
            "post",
            "https://open.tiktokapis.com/v2/oauth/token/",
            {
                "client_key": "client-key",
                "client_secret": "client-secret",
                "code": "auth-code",
                "grant_type": "authorization_code",
                "redirect_uri": "https://app/callback",
            },
            2.0,
        ),
        (
            "post",
            "https://open.tiktokapis.com/v2/oauth/token/",
            {
                "client_key": "client-key",
                "client_secret": "client-secret",
                "grant_type": "refresh_token",
                "refresh_token": "refresh-token",
            },
            2.0,
        ),
    ]


def test_live_client_uses_instagram_refresh_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INSTAGRAM_CLIENT_ID", "ig-client")
    monkeypatch.setenv("INSTAGRAM_CLIENT_SECRET", "ig-secret")
    http = _FakeOAuthHTTP()
    client = oauth_connect.RequestsOAuthProviderClient(http=http, timeout_s=3)

    raw = client.refresh_token("instagram", "long-lived-token")

    assert raw["access_token"] == "refreshed"
    assert http.calls == [
        (
            "get",
            "https://graph.instagram.com/refresh_access_token",
            {"grant_type": "ig_refresh_token", "access_token": "long-lived-token"},
            3.0,
        )
    ]


def test_exchange_and_store_end_to_end(factory: sessionmaker) -> None:
    user_id = _make_user(factory, "e2e@example.com")
    client = _MockProviderClient(
        exchange={"access_token": "acc", "refresh_token": "ref", "open_id": "x1"}
    )
    with _session(factory) as s:
        tokens = oauth_connect.exchange_code(
            "instagram", "code", "https://app/cb", client=client
        )
        oauth_connect.store_account(s, user_id, "instagram", tokens)
    with _session(factory) as s:
        loaded = oauth_connect.load_tokens(s, user_id, "instagram")
        assert loaded is not None and loaded.access_token == "acc"


def test_refresh_if_needed_refreshes_expired_token(factory: sessionmaker) -> None:
    user_id = _make_user(factory, "refresh@example.com")
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    with _session(factory) as s:
        oauth_connect.store_account(
            s, user_id, "youtube",
            oauth_connect.OAuthTokens(
                access_token="old-access", refresh_token="the-refresh",
                expires_at=past,
            ),
        )
    client = _MockProviderClient(
        refresh={"access_token": "new-access", "expires_in": 3600}
    )
    with _session(factory) as s:
        account = oauth_connect.refresh_if_needed(
            s, user_id, "youtube", client=client
        )
        assert account is not None
        tokens = oauth_connect.load_tokens(s, user_id, "youtube")
        assert tokens is not None
        assert tokens.access_token == "new-access"
        # A refresh response omitting the refresh token keeps the existing one.
        assert tokens.refresh_token == "the-refresh"
    assert client.calls == [("refresh", "youtube", "the-refresh")]


def test_refresh_if_needed_noop_when_valid(factory: sessionmaker) -> None:
    user_id = _make_user(factory, "valid@example.com")
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    with _session(factory) as s:
        oauth_connect.store_account(
            s, user_id, "tiktok",
            oauth_connect.OAuthTokens(
                access_token="still-valid", refresh_token="r", expires_at=future,
            ),
        )
    client = _MockProviderClient(refresh={"access_token": "should-not-be-used"})
    with _session(factory) as s:
        oauth_connect.refresh_if_needed(s, user_id, "tiktok", client=client)
        tokens = oauth_connect.load_tokens(s, user_id, "tiktok")
        assert tokens is not None and tokens.access_token == "still-valid"
    assert client.calls == []  # no network call for a still-valid token


def test_refresh_if_needed_raises_without_refresh_token(
    factory: sessionmaker,
) -> None:
    user_id = _make_user(factory, "norefresh@example.com")
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    with _session(factory) as s:
        oauth_connect.store_account(
            s, user_id, "tiktok",
            oauth_connect.OAuthTokens(access_token="expired", expires_at=past),
        )
    with _session(factory) as s:
        with pytest.raises(oauth_connect.OAuthRefreshError):
            oauth_connect.refresh_if_needed(s, user_id, "tiktok")


def test_sweep_expiring_accounts_refreshes_each_account_independently(
    factory: sessionmaker,
) -> None:
    expired = _make_user(factory, "sweep-expired@example.com")
    no_refresh = _make_user(factory, "sweep-no-refresh@example.com")
    valid = _make_user(factory, "sweep-valid@example.com")
    moment = datetime.now(timezone.utc)
    with _session(factory) as s:
        oauth_connect.store_account(
            s,
            expired,
            "youtube",
            oauth_connect.OAuthTokens(
                access_token="old", refresh_token="refresh-ok", expires_at=moment
            ),
        )
        oauth_connect.store_account(
            s,
            no_refresh,
            "tiktok",
            oauth_connect.OAuthTokens(access_token="old", expires_at=moment),
        )
        oauth_connect.store_account(
            s,
            valid,
            "instagram",
            oauth_connect.OAuthTokens(
                access_token="valid",
                refresh_token="not-used",
                expires_at=moment + timedelta(hours=1),
            ),
        )

    client = _MockProviderClient(
        refresh={"access_token": "new", "expires_in": 3600}
    )
    summary = oauth_connect.sweep_expiring_accounts(
        now=moment,
        leeway_s=300,
        client=client,
        session_scope=lambda: _session(factory),
    )

    assert summary == {"considered": 2, "refreshed": 1, "failed": 1}
    assert client.calls == [("refresh", "youtube", "refresh-ok")]
    with _session(factory) as s:
        tokens = oauth_connect.load_tokens(s, expired, "youtube")
        assert tokens is not None and tokens.access_token == "new"


# --------------------------------------------------------------------------- #
# build_authorize_url — carries state + client id from config/env
# --------------------------------------------------------------------------- #
def test_build_authorize_url_includes_state_and_client_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TIKTOK_CLIENT_ID", "tt-client-id")
    url = oauth_connect.build_authorize_url(
        "tiktok", "opaque-state-xyz", "https://app/callback"
    )
    assert url.startswith("https://www.tiktok.com/")
    assert "state=opaque-state-xyz" in url
    assert "client_key=tt-client-id" in url
    assert "response_type=code" in url


def test_build_authorize_url_requires_client_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("YOUTUBE_CLIENT_ID", raising=False)
    monkeypatch.setattr(
        oauth_connect, "_provider_credential", lambda provider, suffix: ""
    )
    with pytest.raises(oauth_connect.OAuthConfigError):
        oauth_connect.build_authorize_url(
            "youtube", "state", "https://app/callback"
        )


# --------------------------------------------------------------------------- #
# CSRF state — single-use contract
# --------------------------------------------------------------------------- #
class _FakeStateRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    def set(self, key, value, *, nx, ex):
        assert nx is True
        assert ex > 0
        if key in self.values:
            return False
        self.values[key] = value
        return True

    def eval(self, script, keys, key):
        assert keys == 1
        if key not in self.values:
            return 0
        del self.values[key]
        return 1


def test_single_use_state_store_consumes_once() -> None:
    store = oauth_connect.SingleUseStateStore()
    state = store.issue()
    assert state  # opaque, non-empty
    # Valid exactly once...
    assert store.consume(state) is True
    # ...then invalidated (replay rejected).
    assert store.consume(state) is False


def test_single_use_state_store_rejects_unknown_and_blank() -> None:
    store = oauth_connect.SingleUseStateStore()
    store.issue()
    assert store.consume("never-issued") is False
    assert store.consume("") is False
    assert store.consume(None) is False


def test_redis_single_use_state_store_consumes_once() -> None:
    store = oauth_connect.RedisSingleUseStateStore(_FakeStateRedis(), ttl_s=60)
    state = store.issue()

    assert state
    assert store.consume(state) is True
    assert store.consume(state) is False


def test_redis_single_use_state_store_fails_closed_on_redis_error() -> None:
    class BrokenRedis:
        def set(self, *args, **kwargs):
            raise OSError("redis down")

        def eval(self, *args, **kwargs):
            raise OSError("redis down")

    store = oauth_connect.RedisSingleUseStateStore(BrokenRedis(), ttl_s=60)
    with pytest.raises(oauth_connect.OAuthStateStoreError):
        store.issue()
    with pytest.raises(oauth_connect.OAuthStateStoreError):
        store.consume("issued-somewhere-else")


def test_generate_state_is_opaque_and_unique() -> None:
    a = oauth_connect.generate_state()
    b = oauth_connect.generate_state()
    assert a and b and a != b
