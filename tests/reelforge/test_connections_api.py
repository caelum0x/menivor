"""Direct-Publish Account-Connect (OAuth) API tests.

Covers ``app.controllers.v1.connections`` — the auth-gated, strictly owner-scoped
endpoints that connect a social platform via OAuth and publish the caller's own
completed job to it:

* ``GET    /me/connections``                   — TOKEN-FREE list (never a token).
* ``GET    /connections/{provider}/authorize`` — returns an opaque single-use state.
* ``GET    /connections/{provider}/callback``  — validates state (single-use, CSRF),
  exchanges the code, encrypts + stores the connection.
* ``DELETE /me/connections/{provider}``        — disconnect (owner-scoped; 404 when
  not connected / for a foreign provider).
* ``POST   /jobs/{id}/publish/{provider}``     — publish the caller's OWN completed
  job (403 foreign job, 409 not-connected / not-complete).

SECURITY anchors: no endpoint ever serialises an access/refresh token; a replayed
or unknown ``state`` is rejected BEFORE any code exchange.

No external I/O: Postgres is replaced by an in-memory SQLite DB behind a
``TestClient``; the OAuth token exchange, video presign, and provider upload are
all injected/monkeypatched, mirroring ``tests/reelforge/test_marketplace_api.py``.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.controllers.v1.connections as conn_mod
from app.models.const import TASK_STATE_COMPLETE, TASK_STATE_PROCESSING
from app.models.db.base import Base
from app.models.db.models import Job, SocialAccount, User
from app.models.exception import HttpException
from app.services import oauth_connect
from app.utils import utils

_API_KEY = "conn-key"
_KEY_HASH = hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}

_OTHER_KEY = "other-conn-key"
_OTHER_HASH = hashlib.sha256(_OTHER_KEY.encode("utf-8")).hexdigest()
_OTHER_HEADERS = {"x-api-key": _OTHER_KEY}

_TOKEN_KEY = "unit-test-social-token-key"


# =========================================================================== #
# Fixtures
# =========================================================================== #
@pytest.fixture(autouse=True)
def _grant_pro_entitlement(monkeypatch):
    """Grant RevenueCat Pro so these endpoint tests exercise the publish/connect
    logic rather than the orthogonal paid-entitlement gate (which has dedicated
    coverage in test_revenuecat_export_gate). ``require_pro_action`` resolves
    ``revenuecat_client.require_pro_entitlement`` at call time, so patching it
    here neutralizes the fail-closed gate for every call site in this module
    without a live RevenueCat secret.
    """
    from app.services.billing import revenuecat_client

    monkeypatch.setattr(
        revenuecat_client, "require_pro_entitlement", lambda *a, **k: None
    )


@pytest.fixture()
def db_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )
    return Factory


def _make_user(Factory, email="owner@example.com", key_hash=_KEY_HASH) -> str:
    with Factory() as s:
        u = User(email=email, api_key_hash=key_hash, credits=0)
        s.add(u)
        s.flush()
        uid = u.id
        s.commit()
    return uid


def _make_job(Factory, user_id, *, state=TASK_STATE_COMPLETE, result_key="results/x.mp4"):
    with Factory() as s:
        job = Job(user_id=user_id, state=state, result_key=result_key, params={})
        s.add(job)
        s.flush()
        jid = job.id
        s.commit()
    return jid


def _connect(Factory, user_id, provider="tiktok", access_token="live-access"):
    """Seed a stored (encrypted) connection for a user via the OAuth service."""
    with Factory() as s:
        oauth_connect.store_account(
            s,
            user_id,
            provider,
            oauth_connect.OAuthTokens(
                access_token=access_token,
                external_account_id="open_id_123",
                scopes="user.info.basic,video.publish",
            ),
        )
        s.commit()


@pytest.fixture()
def conn_client(monkeypatch, db_factory):
    """FastAPI TestClient wired to the connections router + in-memory SQLite.

    Returns ``(client, Factory)``. Sets the token-encryption key + a TikTok client
    id / redirect uri so the real OAuth service paths run; the network exchange /
    upload / presign are injected per-test.
    """
    Factory = db_factory

    monkeypatch.setenv("SOCIAL_TOKEN_KEY", _TOKEN_KEY)
    monkeypatch.setenv("TIKTOK_CLIENT_ID", "tt-client-id")
    monkeypatch.setenv("TIKTOK_REDIRECT_URI", "https://app.example/api/v1/connections/tiktok/callback")

    @contextmanager
    def _fake_get_session():
        session = Factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(conn_mod, "get_session", _fake_get_session)
    # Controller production default is Redis-backed and fail-closed. Keep API
    # tests hermetic by injecting the explicit in-memory test double.
    monkeypatch.setattr(conn_mod, "_STATE_STORE", oauth_connect.SingleUseStateStore())

    app = FastAPI()
    app.include_router(conn_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


# =========================================================================== #
# GET /me/connections  (token-free)
# =========================================================================== #
def test_list_connections_is_token_free(conn_client):
    client, Factory = conn_client
    uid = _make_user(Factory)
    _connect(Factory, uid, access_token="super-secret-token")

    resp = client.get("/api/v1/me/connections", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert len(data) == 1
    row = data[0]

    # Only the token-free public shape.
    assert row["provider"] == "tiktok"
    assert row["external_account_id"] == "open_id_123"
    assert row["connected"] is True
    assert row["status"] == "connected"
    # NEVER a token (plaintext OR encrypted blob) anywhere in the body.
    assert "super-secret-token" not in resp.text
    assert "access_token" not in row
    assert "access_token_enc" not in row
    assert "refresh_token_enc" not in row


def test_list_connections_owner_scoped(conn_client):
    client, Factory = conn_client
    _make_user(Factory)  # caller (no connections)
    other = _make_user(Factory, email="other@x.com", key_hash=_OTHER_HASH)
    _connect(Factory, other, provider="youtube")  # foreign connection

    resp = client.get("/api/v1/me/connections", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.json().get("data", []) == []  # caller has none; never sees other's


def test_list_connections_requires_auth_401(conn_client):
    client, _ = conn_client
    resp = client.get("/api/v1/me/connections")
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# GET /connections/{provider}/authorize  (mint state + url)
# =========================================================================== #
def test_authorize_returns_state_and_url(conn_client):
    client, Factory = conn_client
    _make_user(Factory)

    resp = client.get("/api/v1/connections/tiktok/authorize", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["provider"] == "tiktok"
    assert data["state"]
    assert data["state"] in data["authorize_url"]  # state is embedded in the url
    assert data["authorize_url"].startswith("https://www.tiktok.com/")


def test_authorize_unknown_provider_404(conn_client):
    client, Factory = conn_client
    _make_user(Factory)
    resp = client.get("/api/v1/connections/myspace/authorize", headers=_HEADERS)
    assert resp.status_code == 404, resp.text


def test_authorize_requires_auth_401(conn_client):
    client, _ = conn_client
    resp = client.get("/api/v1/connections/tiktok/authorize")
    assert resp.status_code == 401, resp.text


def test_authorize_fails_closed_when_shared_state_store_is_unavailable(
    conn_client, monkeypatch
):
    client, Factory = conn_client
    _make_user(Factory)

    class StateStoreDown:
        def issue(self):
            raise oauth_connect.OAuthStateStoreError("redis down")

    monkeypatch.setattr(conn_mod, "_STATE_STORE", StateStoreDown())
    resp = client.get("/api/v1/connections/tiktok/authorize", headers=_HEADERS)

    assert resp.status_code == 503, resp.text


# =========================================================================== #
# GET /connections/{provider}/callback  (validate state -> exchange -> store)
# =========================================================================== #
def test_callback_validates_state_and_stores(conn_client, monkeypatch):
    client, Factory = conn_client
    uid = _make_user(Factory)

    calls = []

    def _fake_exchange(provider, code, redirect_uri, **kw):
        calls.append((provider, code))
        return oauth_connect.OAuthTokens(
            access_token="freshly-exchanged-token",
            external_account_id="open_id_777",
            scopes="video.publish",
        )

    monkeypatch.setattr(oauth_connect, "exchange_code", _fake_exchange)

    state = conn_mod._STATE_STORE.issue()
    resp = client.get(
        "/api/v1/connections/tiktok/callback",
        params={"code": "auth-code", "state": state},
        headers=_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert calls == [("tiktok", "auth-code")]

    # The connection is stored ENCRYPTED (never plaintext) and the response never
    # leaks the token.
    assert "freshly-exchanged-token" not in resp.text
    with Factory() as s:
        row = s.query(SocialAccount).filter_by(user_id=uid, provider="tiktok").one()
        assert row.access_token_enc  # stored
        assert row.access_token_enc != "freshly-exchanged-token"  # encrypted


def test_callback_rejects_unknown_state_before_exchange(conn_client, monkeypatch):
    client, Factory = conn_client
    _make_user(Factory)

    exchanged = []
    monkeypatch.setattr(
        oauth_connect,
        "exchange_code",
        lambda *a, **k: exchanged.append(a) or oauth_connect.OAuthTokens("x"),
    )

    resp = client.get(
        "/api/v1/connections/tiktok/callback",
        params={"code": "auth-code", "state": "never-issued"},
        headers=_HEADERS,
    )
    assert resp.status_code == 400, resp.text
    assert exchanged == []  # CSRF gate ran BEFORE any exchange


def test_callback_replayed_state_is_single_use(conn_client, monkeypatch):
    client, Factory = conn_client
    _make_user(Factory)
    monkeypatch.setattr(
        oauth_connect,
        "exchange_code",
        lambda *a, **k: oauth_connect.OAuthTokens("tok", external_account_id="e"),
    )

    state = conn_mod._STATE_STORE.issue()
    first = client.get(
        "/api/v1/connections/tiktok/callback",
        params={"code": "c", "state": state},
        headers=_HEADERS,
    )
    assert first.status_code == 200, first.text
    # Replaying the SAME state must now be rejected (single-use).
    replay = client.get(
        "/api/v1/connections/tiktok/callback",
        params={"code": "c", "state": state},
        headers=_HEADERS,
    )
    assert replay.status_code == 400, replay.text


def test_callback_requires_auth_401(conn_client):
    client, _ = conn_client
    state = conn_mod._STATE_STORE.issue()
    resp = client.get(
        "/api/v1/connections/tiktok/callback",
        params={"code": "c", "state": state},
    )
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# DELETE /me/connections/{provider}  (owner-scoped disconnect)
# =========================================================================== #
def test_disconnect_own_connection(conn_client):
    client, Factory = conn_client
    uid = _make_user(Factory)
    _connect(Factory, uid, provider="tiktok")

    resp = client.delete("/api/v1/me/connections/tiktok", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == {"disconnected": True, "provider": "tiktok"}

    with Factory() as s:
        assert (
            s.query(SocialAccount).filter_by(user_id=uid, provider="tiktok").first()
            is None
        )


def test_disconnect_not_connected_404(conn_client):
    client, Factory = conn_client
    _make_user(Factory)
    resp = client.delete("/api/v1/me/connections/tiktok", headers=_HEADERS)
    assert resp.status_code == 404, resp.text


def test_disconnect_is_owner_scoped(conn_client):
    client, Factory = conn_client
    _make_user(Factory)  # caller (not connected)
    other = _make_user(Factory, email="other@x.com", key_hash=_OTHER_HASH)
    _connect(Factory, other, provider="tiktok")  # foreign connection

    # Caller disconnecting 'tiktok' they don't own is a 404; the foreign row stays.
    resp = client.delete("/api/v1/me/connections/tiktok", headers=_HEADERS)
    assert resp.status_code == 404, resp.text
    with Factory() as s:
        assert (
            s.query(SocialAccount).filter_by(user_id=other, provider="tiktok").first()
            is not None
        )


def test_disconnect_requires_auth_401(conn_client):
    client, _ = conn_client
    resp = client.delete("/api/v1/me/connections/tiktok")
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# POST /jobs/{id}/publish/{provider}  (direct publish)
# =========================================================================== #
class _MockUpload:
    """Records the token it was handed and returns a canned provider response."""

    def __init__(self):
        self.seen = []

    def upload(self, provider, access_token, video_url, *, caption="", **opts):
        self.seen.append((provider, access_token, video_url, caption))
        return {"id": "post_abc", "url": "https://tiktok.com/@me/video/post_abc"}


def _wire_publish(monkeypatch, upload=None):
    up = upload or _MockUpload()
    monkeypatch.setattr(conn_mod, "_upload_client", lambda provider: up)
    monkeypatch.setattr(
        conn_mod, "_resolve_video_url_by_key", lambda key, rid: f"https://cdn/{key}"
    )
    return up


def test_publish_happy_path(conn_client, monkeypatch):
    client, Factory = conn_client
    uid = _make_user(Factory)
    _connect(Factory, uid, provider="tiktok", access_token="the-live-token")
    job_id = _make_job(Factory, uid)
    up = _wire_publish(monkeypatch)

    resp = client.post(
        f"/api/v1/jobs/{job_id}/publish/tiktok",
        params={"caption": "hello world"},
        headers=_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["provider"] == "tiktok"
    assert data["external_post_id"] == "post_abc"
    assert data["status"] == "published"

    # The DECRYPTED token reached the upload client (used only for the outbound
    # call) but never appears in the response body.
    assert up.seen and up.seen[0][1] == "the-live-token"
    assert up.seen[0][3] == "hello world"
    assert "the-live-token" not in resp.text


def test_publish_foreign_job_403(conn_client, monkeypatch):
    client, Factory = conn_client
    _make_user(Factory)  # caller
    other = _make_user(Factory, email="other@x.com", key_hash=_OTHER_HASH)
    _connect(Factory, other, provider="tiktok")
    foreign_job = _make_job(Factory, other)
    _wire_publish(monkeypatch)

    resp = client.post(
        f"/api/v1/jobs/{foreign_job}/publish/tiktok", headers=_HEADERS
    )
    assert resp.status_code == 403, resp.text


def test_publish_unknown_job_404(conn_client, monkeypatch):
    client, Factory = conn_client
    uid = _make_user(Factory)
    _connect(Factory, uid, provider="tiktok")
    _wire_publish(monkeypatch)

    resp = client.post(
        "/api/v1/jobs/does-not-exist/publish/tiktok", headers=_HEADERS
    )
    assert resp.status_code == 404, resp.text


def test_publish_not_connected_409(conn_client, monkeypatch):
    client, Factory = conn_client
    uid = _make_user(Factory)
    job_id = _make_job(Factory, uid)  # completed, but no connection
    _wire_publish(monkeypatch)

    resp = client.post(
        f"/api/v1/jobs/{job_id}/publish/tiktok", headers=_HEADERS
    )
    assert resp.status_code == 409, resp.text


def test_publish_job_not_complete_409(conn_client, monkeypatch):
    client, Factory = conn_client
    uid = _make_user(Factory)
    _connect(Factory, uid, provider="tiktok")
    job_id = _make_job(Factory, uid, state=TASK_STATE_PROCESSING, result_key="")
    _wire_publish(monkeypatch)

    resp = client.post(
        f"/api/v1/jobs/{job_id}/publish/tiktok", headers=_HEADERS
    )
    assert resp.status_code == 409, resp.text


def test_publish_requires_auth_401(conn_client):
    client, Factory = conn_client
    uid = _make_user(Factory)
    job_id = _make_job(Factory, uid)
    resp = client.post(f"/api/v1/jobs/{job_id}/publish/tiktok")
    assert resp.status_code == 401, resp.text


def test_publish_held_by_content_gate_409(conn_client, monkeypatch):
    """A held content-gate verdict stops the publish (409) BEFORE any upload."""
    client, Factory = conn_client
    uid = _make_user(Factory)
    _connect(Factory, uid, provider="tiktok", access_token="the-live-token")
    job_id = _make_job(Factory, uid)
    up = _wire_publish(monkeypatch)

    from app.domains.publishing import content_gate as gate_mod

    held = gate_mod.GateResult(
        decision="needs_edit",
        reasons={"policy": "unsupported medical claim"},
        signals=None,
        degraded=False,
    )
    monkeypatch.setattr(gate_mod, "evaluate_content_sync", lambda *a, **k: held)

    resp = client.post(
        f"/api/v1/jobs/{job_id}/publish/tiktok",
        params={"caption": "this miracle cure works"},
        headers=_HEADERS,
    )
    assert resp.status_code == 409, resp.text
    # The gate ran IN FRONT of publish: the upload client was never called.
    assert up.seen == []


def test_publish_allowed_when_gate_passes(conn_client, monkeypatch):
    """An allow verdict lets the publish proceed to the upload client."""
    client, Factory = conn_client
    uid = _make_user(Factory)
    _connect(Factory, uid, provider="tiktok", access_token="the-live-token")
    job_id = _make_job(Factory, uid)
    up = _wire_publish(monkeypatch)

    from app.domains.publishing import content_gate as gate_mod

    ok = gate_mod.GateResult(
        decision="publish", reasons={}, signals=None, degraded=False
    )
    monkeypatch.setattr(gate_mod, "evaluate_content_sync", lambda *a, **k: ok)

    resp = client.post(
        f"/api/v1/jobs/{job_id}/publish/tiktok",
        params={"caption": "great tips"},
        headers=_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert up.seen and up.seen[0][1] == "the-live-token"
