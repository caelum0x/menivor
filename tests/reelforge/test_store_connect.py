"""Phase 3 "Connect your store" — App Store Connect + Play credential storage,
and the apps/version/rating read built on top.

Client tests (``AppStoreConnectClient`` / ``PlayDeveloperClient``) drive the
real request assembly / response parsing against a fake :class:`Transport` and
assert the exact API contract, mirroring
``tests/reelforge/test_native_publish.py``'s connector tests. Service tests run
on an in-memory SQLite database with the real encryption (reusing
``app.services.crypto_tokens``, the same Fernet helper that protects
``social_accounts``).
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.store_connect import service as store_service
from app.domains.store_connect.clients import (
    AppStoreConnectClient,
    AppStoreCredentials,
    PlayDeveloperClient,
    StoreConnectError,
)
from app.models.db.base import Base
from app.models.db.models import StoreConnection, User
from app.models.db.repositories import StoreConnectionRepository
from app.services import crypto_tokens

_TEST_TOKEN_KEY = "test-store-connect-token-key-do-not-use-in-prod"

# A throwaway EC P-256 key (freshly generated for this test file, never used
# against a real Apple account) — valid PEM/PKCS8 so AppStoreConnectClient's
# real ES256 signing path is exercised, exactly as it would be with an
# operator's actual .p8 key.
_FAKE_ASC_KEY = (
    "-----BEGIN PRIVATE KEY-----\n"
    "MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgFglDEkSEmQE5Jrwd\n"
    "LcpS7krC/alMRxfloqwevfDRp2ShRANCAASd2Q6BfsJpG4IKa+73edzqZVzCQG0x\n"
    "E5mgHnGrzjb7ESfq2Hqw4Vei96ocaPud5siOy/XDdXd+jUJ1zspXGuFe\n"
    "-----END PRIVATE KEY-----\n"
)
_FAKE_PLAY_JSON = (
    '{"type": "service_account", "client_email": "svc@proj.iam.gserviceaccount.com", '
    '"private_key": "-----BEGIN PRIVATE KEY-----\\nFAKE\\n-----END PRIVATE KEY-----\\n", '
    '"project_id": "proj"}'
)


class _Resp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {}

    def json(self):
        return self._body

    @property
    def text(self):
        return str(self._body)


class FakeTransport:
    """Records every request and replays a scripted queue of responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def request(self, method, url, *, headers=None, params=None, json=None):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "params": params or {}, "json": json})
        if not self._responses:
            raise AssertionError(f"unexpected extra request: {method} {url}")
        return self._responses.pop(0)


def _fake_play_credentials(_info: dict) -> SimpleNamespace:
    """A fake google-auth Credentials: `.refresh()` sets `.token`, never touches the network."""

    def _refresh(_request):
        creds.token = "play-access-token"

    creds = SimpleNamespace(token=None, refresh=_refresh)
    return creds


# --------------------------------------------------------------------------- #
# AppStoreConnectClient — real ASC API contract over a fake transport
# --------------------------------------------------------------------------- #
def test_appstore_client_signs_a_real_es256_jwt_and_lists_apps():
    creds = AppStoreCredentials(issuer_id="iss-1", key_id="key-1", private_key_pem=_FAKE_ASC_KEY)
    # A deterministic clock; we only assert the request shape, not a real signature.
    import jwt as pyjwt

    transport = FakeTransport([
        _Resp(200, {"data": [{"id": "app1", "attributes": {"name": "My App", "bundleId": "com.example.app"}}]}),
    ])
    client = AppStoreConnectClient(creds, transport=transport, clock=lambda: 1_700_000_000)
    apps = client.list_apps()

    assert apps == [{"id": "app1", "name": "My App", "bundle_id": "com.example.app"}]
    call = transport.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == "https://api.appstoreconnect.apple.com/v1/apps"
    auth = call["headers"]["Authorization"]
    assert auth.startswith("Bearer ")
    token = auth.split(" ", 1)[1]
    header = pyjwt.get_unverified_header(token)
    assert header["kid"] == "key-1"
    assert header["alg"] == "ES256"


def test_appstore_client_validate_raises_on_bad_key():
    creds = AppStoreCredentials(issuer_id="iss", key_id="key", private_key_pem="not a real key")
    transport = FakeTransport([])  # never reached — signing fails first
    client = AppStoreConnectClient(creds, transport=transport)
    with pytest.raises(StoreConnectError) as exc_info:
        client.validate()
    assert exc_info.value.provider == "appstore"
    assert "sign" in str(exc_info.value)


def test_appstore_client_validate_raises_on_401():
    creds = AppStoreCredentials(issuer_id="iss", key_id="key", private_key_pem=_FAKE_ASC_KEY)
    transport = FakeTransport([_Resp(401, {"errors": [{"title": "Not authenticated"}]})])
    client = AppStoreConnectClient(creds, transport=transport)
    with pytest.raises(StoreConnectError) as exc_info:
        client.validate()
    assert exc_info.value.status_code == 401


def test_appstore_client_latest_version_and_rating():
    creds = AppStoreCredentials(issuer_id="iss", key_id="key", private_key_pem=_FAKE_ASC_KEY)
    transport = FakeTransport([
        _Resp(200, {"data": [{"attributes": {"versionString": "2.3.0", "appStoreState": "READY_FOR_SALE"}}]}),
        _Resp(200, {"data": [
            {"attributes": {"rating": 5}}, {"attributes": {"rating": 3}}, {"attributes": {"rating": 4}},
        ]}),
    ])
    client = AppStoreConnectClient(creds, transport=transport)
    assert client.latest_version("app1") == {"version": "2.3.0", "state": "READY_FOR_SALE"}
    rating = client.rating_summary("app1")
    assert rating["average_rating"] == 4.0
    assert rating["sample_size"] == 3
    assert rating["approximate"] is True


def test_appstore_client_latest_version_none_when_no_versions():
    creds = AppStoreCredentials(issuer_id="iss", key_id="key", private_key_pem=_FAKE_ASC_KEY)
    transport = FakeTransport([_Resp(200, {"data": []})])
    client = AppStoreConnectClient(creds, transport=transport)
    assert client.latest_version("app1") is None


# --------------------------------------------------------------------------- #
# PlayDeveloperClient — real Android Publisher API contract over a fake transport
# --------------------------------------------------------------------------- #
def test_play_client_validate_authenticates_without_network():
    client = PlayDeveloperClient({"client_email": "svc@x"}, transport=FakeTransport([]),
                                  credentials_factory=_fake_play_credentials)
    client.validate()  # must not raise; no HTTP calls made


def test_play_client_validate_wraps_auth_failure():
    def _broken(_info):
        raise RuntimeError("bad key")

    client = PlayDeveloperClient({}, transport=FakeTransport([]), credentials_factory=_broken)
    with pytest.raises(StoreConnectError) as exc_info:
        client.validate()
    assert exc_info.value.provider == "play"
    assert "authenticate" in str(exc_info.value)


def test_play_client_current_version_opens_reads_and_discards_an_edit():
    transport = FakeTransport([
        _Resp(200, {"id": "edit-1"}),  # edits.insert
        _Resp(200, {"releases": [{"name": "7.1.0", "versionCodes": ["42"]}]}),  # tracks.get
        _Resp(200, {}),  # edits.delete
    ])
    client = PlayDeveloperClient({}, transport=transport, credentials_factory=_fake_play_credentials)
    version = client.current_version("com.example.app")
    assert version == {"version_code": "42", "version_name": "7.1.0", "track": "production"}
    methods = [c["method"] for c in transport.calls]
    assert methods == ["POST", "GET", "DELETE"]
    assert transport.calls[0]["url"].endswith("/applications/com.example.app/edits")
    assert transport.calls[2]["url"].endswith("/edits/edit-1")


def test_play_client_current_version_still_discards_edit_on_read_error():
    transport = FakeTransport([
        _Resp(200, {"id": "edit-1"}),
        _Resp(500, {"error": "boom"}),  # tracks.get fails
        _Resp(200, {}),  # edit is still cleaned up
    ])
    client = PlayDeveloperClient({}, transport=transport, credentials_factory=_fake_play_credentials)
    with pytest.raises(StoreConnectError) as exc_info:
        client.current_version("com.example.app")
    assert exc_info.value.status_code == 502
    # The edit cleanup (DELETE) still ran even though the read failed.
    assert [c["method"] for c in transport.calls] == ["POST", "GET", "DELETE"]


def test_play_client_rating_summary_averages_star_ratings():
    transport = FakeTransport([
        _Resp(200, {"reviews": [
            {"comments": [{"userComment": {"starRating": 5}}]},
            {"comments": [{"userComment": {"starRating": 1}}]},
        ]}),
    ])
    client = PlayDeveloperClient({}, transport=transport, credentials_factory=_fake_play_credentials)
    rating = client.rating_summary("com.example.app")
    assert rating == {"average_rating": 3.0, "sample_size": 2, "approximate": True}


# --------------------------------------------------------------------------- #
# service.py — validate -> encrypt -> persist -> read (SQLite + real crypto)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(store_service, "get_session", _session)
    monkeypatch.setenv("SOCIAL_TOKEN_KEY", _TEST_TOKEN_KEY)
    return factory


def _make_user(factory: sessionmaker, email: str) -> str:
    session = factory()
    try:
        user = User(email=email, credits=0)
        session.add(user)
        session.commit()
        session.refresh(user)
        return user.id
    finally:
        session.close()


def test_connect_appstore_validates_then_encrypts_and_stores(db: sessionmaker):
    user_id = _make_user(db, "asc@example.com")
    transport = FakeTransport([_Resp(200, {"data": []})])  # the validate() call

    record = store_service.connect_appstore(user_id, "iss-1", "key-1", _FAKE_ASC_KEY, transport=transport)

    assert record["provider"] == "appstore"
    assert record["account_name"] == "iss-1"
    assert record["status"] == "connected"
    session = db()
    try:
        row = session.execute(select(StoreConnection).where(StoreConnection.user_id == user_id)).scalars().one()
        assert "iss-1" not in row.credentials_enc  # not plaintext-identifiable... but DOES decrypt back:
        assert _FAKE_ASC_KEY not in row.credentials_enc
        import json as _json

        decrypted = _json.loads(crypto_tokens.decrypt(row.credentials_enc))
        assert decrypted == {"issuer_id": "iss-1", "key_id": "key-1", "private_key_pem": _FAKE_ASC_KEY.strip()}
    finally:
        session.close()


def test_connect_appstore_rejects_bad_key_before_persisting(db: sessionmaker):
    user_id = _make_user(db, "badkey@example.com")
    transport = FakeTransport([_Resp(401, {"errors": [{"title": "nope"}]})])
    with pytest.raises(StoreConnectError):
        store_service.connect_appstore(user_id, "iss-1", "key-1", _FAKE_ASC_KEY, transport=transport)
    session = db()
    try:
        count = session.execute(select(func.count()).select_from(StoreConnection)).scalar_one()
        assert count == 0  # a rejected key is never stored
    finally:
        session.close()


def test_connect_appstore_rejects_missing_fields(db: sessionmaker):
    user_id = _make_user(db, "blank@example.com")
    with pytest.raises(StoreConnectError):
        store_service.connect_appstore(user_id, "", "key-1", _FAKE_ASC_KEY)
    with pytest.raises(StoreConnectError):
        store_service.connect_appstore(user_id, "iss-1", "key-1", "not a pem")


def test_connect_play_validates_then_encrypts_and_stores(db: sessionmaker):
    user_id = _make_user(db, "play@example.com")
    record = store_service.connect_play(
        user_id, _FAKE_PLAY_JSON, transport=FakeTransport([]), credentials_factory=_fake_play_credentials,
    )
    assert record["provider"] == "play"
    assert record["account_name"] == "svc@proj.iam.gserviceaccount.com"
    assert record["package_names"] == []


def test_connect_play_rejects_malformed_json(db: sessionmaker):
    user_id = _make_user(db, "badplay@example.com")
    with pytest.raises(StoreConnectError):
        store_service.connect_play(user_id, "not json", credentials_factory=_fake_play_credentials)


def test_connect_play_rejects_non_service_account_json(db: sessionmaker):
    user_id = _make_user(db, "badplay2@example.com")
    with pytest.raises(StoreConnectError):
        store_service.connect_play(user_id, '{"type": "user"}', credentials_factory=_fake_play_credentials)


def test_reconnect_appstore_upserts_single_row(db: sessionmaker):
    user_id = _make_user(db, "reconnect@example.com")
    store_service.connect_appstore(user_id, "iss-1", "key-1", _FAKE_ASC_KEY, transport=FakeTransport([_Resp(200, {"data": []})]))
    store_service.connect_appstore(user_id, "iss-2", "key-2", _FAKE_ASC_KEY, transport=FakeTransport([_Resp(200, {"data": []})]))
    session = db()
    try:
        count = session.execute(select(func.count()).select_from(StoreConnection)).scalar_one()
        assert count == 1
    finally:
        session.close()
    connections = store_service.list_connections(user_id)
    assert len(connections) == 1
    assert connections[0]["account_name"] == "iss-2"


def test_other_user_cannot_read_or_disconnect_connection(db: sessionmaker):
    owner = _make_user(db, "owner@example.com")
    intruder = _make_user(db, "intruder@example.com")
    store_service.connect_appstore(owner, "iss-1", "key-1", _FAKE_ASC_KEY, transport=FakeTransport([_Resp(200, {"data": []})]))

    assert store_service.list_connections(intruder) == []
    assert store_service.disconnect(intruder, "appstore") is False
    assert len(store_service.list_connections(owner)) == 1


def test_disconnect_removes_the_row(db: sessionmaker):
    user_id = _make_user(db, "bye@example.com")
    store_service.connect_appstore(user_id, "iss-1", "key-1", _FAKE_ASC_KEY, transport=FakeTransport([_Resp(200, {"data": []})]))
    assert store_service.disconnect(user_id, "appstore") is True
    assert store_service.list_connections(user_id) == []
    assert store_service.disconnect(user_id, "appstore") is False  # already gone


def test_connect_appstore_missing_token_key_never_persists(db: sessionmaker, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SOCIAL_TOKEN_KEY", raising=False)
    monkeypatch.setattr(crypto_tokens, "_resolve_secret", lambda: "")
    user_id = _make_user(db, "nokey@example.com")
    with pytest.raises(StoreConnectError):
        store_service.connect_appstore(user_id, "iss-1", "key-1", _FAKE_ASC_KEY, transport=FakeTransport([]))


# --------------------------------------------------------------------------- #
# list_appstore_apps / add_play_app / list_play_apps — the first feature
# --------------------------------------------------------------------------- #
def test_list_appstore_apps_returns_app_version_and_rating(db: sessionmaker):
    user_id = _make_user(db, "apps@example.com")
    store_service.connect_appstore(user_id, "iss-1", "key-1", _FAKE_ASC_KEY, transport=FakeTransport([_Resp(200, {"data": []})]))

    read_transport = FakeTransport([
        _Resp(200, {"data": [{"id": "app1", "attributes": {"name": "My App", "bundleId": "com.ex.app"}}]}),
        _Resp(200, {"data": [{"attributes": {"versionString": "1.0", "appStoreState": "READY_FOR_SALE"}}]}),
        _Resp(200, {"data": [{"attributes": {"rating": 5}}]}),
    ])
    apps = store_service.list_appstore_apps(user_id, transport=read_transport)
    assert apps == [{
        "id": "app1", "name": "My App", "bundle_id": "com.ex.app",
        "version": "1.0", "state": "READY_FOR_SALE",
        "average_rating": 5.0, "sample_size": 1, "approximate": True,
    }]


def test_list_appstore_apps_requires_a_connection_first(db: sessionmaker):
    user_id = _make_user(db, "noconn@example.com")
    with pytest.raises(StoreConnectError) as exc_info:
        store_service.list_appstore_apps(user_id)
    assert exc_info.value.status_code == 409


def test_add_play_app_registers_package_and_returns_it(db: sessionmaker):
    user_id = _make_user(db, "playapp@example.com")
    store_service.connect_play(user_id, _FAKE_PLAY_JSON, transport=FakeTransport([]), credentials_factory=_fake_play_credentials)

    add_transport = FakeTransport([
        _Resp(200, {"id": "edit-1"}),
        _Resp(200, {"releases": [{"name": "1.2.3", "versionCodes": ["9"]}]}),
        _Resp(200, {}),
        _Resp(200, {"reviews": [{"comments": [{"userComment": {"starRating": 4}}]}]}),
    ])
    result = store_service.add_play_app(
        user_id, "com.example.app", transport=add_transport, credentials_factory=_fake_play_credentials,
    )
    assert result["package_name"] == "com.example.app"
    assert result["version_name"] == "1.2.3"
    assert result["average_rating"] == 4.0

    connections = store_service.list_connections(user_id)
    assert connections[0]["package_names"] == ["com.example.app"]


def test_add_play_app_rejects_invalid_package_name(db: sessionmaker):
    user_id = _make_user(db, "badpkg@example.com")
    store_service.connect_play(user_id, _FAKE_PLAY_JSON, transport=FakeTransport([]), credentials_factory=_fake_play_credentials)
    with pytest.raises(StoreConnectError):
        store_service.add_play_app(user_id, "not a package", credentials_factory=_fake_play_credentials)


def test_list_play_apps_empty_before_any_package_registered(db: sessionmaker):
    user_id = _make_user(db, "emptyplay@example.com")
    store_service.connect_play(user_id, _FAKE_PLAY_JSON, transport=FakeTransport([]), credentials_factory=_fake_play_credentials)
    assert store_service.list_play_apps(user_id, credentials_factory=_fake_play_credentials) == []
