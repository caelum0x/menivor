"""Enterprise SSO v1 API tests (Identity & SSO, Epic 2).

Exercises ``app.controllers.v1.sso`` end-to-end over a FastAPI ``TestClient`` with
Postgres replaced by in-memory SQLite. No external I/O, no xmlsec.

Covered
-------
* connection config is RBAC-gated (``workspace.settings``) — a viewer PUT -> ``403``;
* ``GET`` NEVER returns the IdP certificate — only a ``has_certificate`` flag;
* the SAML ACS validates through the MOCKABLE seam: a bad/foreign assertion -> ``401``
  (never trusted) while a mock-VALIDATED assertion issues a session token;
* the ACS degrades to ``503`` when the native SAML toolkit is unavailable;
* SP metadata + SP-initiated login redirect work without xmlsec.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.controllers.v1.sso as sso_mod
from app.models.db.base import Base
from app.models.db.models import (
    AuditLog,
    ExternalIdentity,
    SSOConnection,
    User,
    Workspace,
    WorkspaceMember,
)
from app.models.exception import HttpException
from app.services import sso as sso_service
from app.utils import utils


@pytest.fixture(autouse=True)
def _sso_on(monkeypatch):
    """These tests cover the SSO code behind the MN7a flag, so switch it on."""
    monkeypatch.setenv(sso_mod.SSO_FLAG_ENV, "1")


def _key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _headers(raw_key: str) -> dict[str, str]:
    return {"x-api-key": raw_key}


@pytest.fixture()
def db_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )


@pytest.fixture()
def sso_client(monkeypatch, db_factory):
    Factory = db_factory

    # The IdP signing cert is Fernet-encrypted at the service boundary; provide the
    # key so the real encrypt/decrypt paths run (as in test_connections_api).
    monkeypatch.setenv("SOCIAL_TOKEN_KEY", "unit-test-sso-token-key")

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

    monkeypatch.setattr(sso_mod, "get_session", _fake_get_session)

    # Replay protection: pin an ISOLATED in-memory cache per test so the ACS tests
    # are deterministic and never share state with a developer's local Redis (whose
    # replay keys persist for the assertion TTL across runs and would otherwise
    # spuriously 409 a "first" assertion). CI (no Redis) already gets a fresh
    # in-memory fallback; this makes the behaviour identical everywhere.
    _replay = sso_service.InMemoryReplayCache()
    monkeypatch.setattr(sso_service, "default_replay_cache", lambda: _replay)

    app = FastAPI()
    app.include_router(sso_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


@pytest.fixture()
def seeded(db_factory):
    """Seed a workspace with owner/admin/viewer members + a stranger."""
    Factory = db_factory
    out: dict[str, object] = {}
    specs = {
        "owner": ("owner@ex.com", "owner-key", "owner"),
        "admin": ("admin@ex.com", "admin-key", "admin"),
        "viewer": ("viewer@ex.com", "viewer-key", "viewer"),
        "stranger": ("stranger@ex.com", "stranger-key", None),
    }
    with Factory() as s:
        ids: dict[str, str] = {}
        for label, (email, raw, _role) in specs.items():
            u = User(email=email, api_key_hash=_key_hash(raw), credits=0)
            s.add(u)
            s.flush()
            ids[label] = u.id
            out[label] = (u.id, raw)
        ws = Workspace(owner_id=ids["owner"], name="Acme")
        s.add(ws)
        s.flush()
        for label, (_email, _raw, role) in specs.items():
            if role is None:
                continue
            s.add(WorkspaceMember(workspace_id=ws.id, user_id=ids[label], role=role))
        s.commit()
        out["workspace_id"] = ws.id
    return out


def _configure(client, wid, key, *, enabled=True, cert="-----CERT-----", sso_url=None):
    body = {
        "protocol": "saml",
        "idp_entity_id": "https://idp.example.com/entity",
        "idp_sso_url": sso_url or "https://idp.example.com/sso",
        "idp_x509_cert": cert,
        "sp_acs_url": "https://sp.reelforge.com/api/v1/sso/{}/acs".format(wid),
        "enabled": enabled,
    }
    return client.put(
        f"/api/v1/me/workspaces/{wid}/sso", json=body, headers=_headers(key)
    )


# =========================================================================== #
# Connection config — RBAC gated + cert-free
# =========================================================================== #
def test_viewer_cannot_configure_sso_403(sso_client, seeded):
    client, _ = sso_client
    wid = seeded["workspace_id"]
    _vid, viewer_key = seeded["viewer"]
    resp = _configure(client, wid, viewer_key)
    assert resp.status_code == 403, resp.text


def test_config_requires_auth_401(sso_client, seeded):
    client, _ = sso_client
    wid = seeded["workspace_id"]
    resp = client.put(f"/api/v1/me/workspaces/{wid}/sso", json={"protocol": "saml"})
    assert resp.status_code == 401, resp.text


def test_owner_configures_and_get_never_returns_cert(sso_client, seeded):
    client, Factory = sso_client
    wid = seeded["workspace_id"]
    _oid, owner_key = seeded["owner"]

    resp = _configure(client, wid, owner_key, cert="SUPER-SECRET-CERT-PEM")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["has_certificate"] is True
    assert "SUPER-SECRET-CERT-PEM" not in resp.text
    assert "idp_x509_cert" not in data

    got = client.get(
        f"/api/v1/me/workspaces/{wid}/sso", headers=_headers(owner_key)
    )
    assert got.status_code == 200, got.text
    gdata = got.json()["data"]
    assert gdata["has_certificate"] is True
    assert gdata["enabled"] is True
    assert "SUPER-SECRET-CERT-PEM" not in got.text
    assert "idp_x509_cert" not in gdata

    # The cert is persisted ENCRYPTED (never plaintext).
    with Factory() as s:
        row = s.execute(select(SSOConnection)).scalars().first()
        assert row.idp_x509_cert_enc
        assert "SUPER-SECRET-CERT-PEM" not in (row.idp_x509_cert_enc or "")


def test_viewer_cannot_read_sso_config_403(sso_client, seeded):
    client, _ = sso_client
    wid = seeded["workspace_id"]
    _oid, owner_key = seeded["owner"]
    _vid, viewer_key = seeded["viewer"]
    assert _configure(client, wid, owner_key).status_code == 200
    resp = client.get(
        f"/api/v1/me/workspaces/{wid}/sso", headers=_headers(viewer_key)
    )
    assert resp.status_code == 403, resp.text


def test_delete_connection(sso_client, seeded):
    client, _ = sso_client
    wid = seeded["workspace_id"]
    _oid, owner_key = seeded["owner"]
    assert _configure(client, wid, owner_key).status_code == 200
    resp = client.delete(
        f"/api/v1/me/workspaces/{wid}/sso", headers=_headers(owner_key)
    )
    assert resp.status_code == 200, resp.text
    got = client.get(
        f"/api/v1/me/workspaces/{wid}/sso", headers=_headers(owner_key)
    )
    assert got.json()["data"] is None


# =========================================================================== #
# Metadata + login
# =========================================================================== #
def test_sp_metadata_xml(sso_client, seeded):
    client, _ = sso_client
    wid = seeded["workspace_id"]
    _oid, owner_key = seeded["owner"]
    assert _configure(client, wid, owner_key).status_code == 200
    resp = client.get(f"/api/v1/sso/{wid}/metadata")
    assert resp.status_code == 200, resp.text
    assert "EntityDescriptor" in resp.text
    assert "AssertionConsumerService" in resp.text


def test_login_redirects_to_idp(sso_client, seeded):
    client, _ = sso_client
    wid = seeded["workspace_id"]
    _oid, owner_key = seeded["owner"]
    assert _configure(client, wid, owner_key, enabled=True).status_code == 200
    resp = client.get(f"/api/v1/sso/{wid}/login", follow_redirects=False)
    assert resp.status_code == 302, resp.text
    location = resp.headers["location"]
    assert location.startswith("https://idp.example.com/sso")
    assert "SAMLRequest=" in location


def test_login_unconfigured_404(sso_client, seeded):
    client, _ = sso_client
    wid = seeded["workspace_id"]
    resp = client.get(f"/api/v1/sso/{wid}/login", follow_redirects=False)
    assert resp.status_code == 404, resp.text


# =========================================================================== #
# ACS — validates via the mock seam; never trusts a bad/foreign assertion
# =========================================================================== #
def test_acs_rejects_bad_assertion_401(sso_client, seeded, monkeypatch):
    client, _ = sso_client
    wid = seeded["workspace_id"]
    _oid, owner_key = seeded["owner"]
    assert _configure(client, wid, owner_key, enabled=True).status_code == 200

    def _reject(connection, saml_response, relay_state=""):
        raise sso_service.SsoValidationError("bad signature / foreign assertion")

    monkeypatch.setattr(sso_service, "_validate_saml_response", _reject)
    resp = client.post(
        f"/api/v1/sso/{wid}/acs", data={"SAMLResponse": "Zm9yZ2Vk"}
    )
    assert resp.status_code == 401, resp.text


def test_acs_success_issues_session(sso_client, seeded, monkeypatch):
    client, Factory = sso_client
    wid = seeded["workspace_id"]
    _oid, owner_key = seeded["owner"]
    assert _configure(client, wid, owner_key, enabled=True).status_code == 200

    def _valid(connection, saml_response, relay_state=""):
        return sso_service.ValidatedAssertion(
            subject="okta|user-123",
            email="newhire@acme.com",
            assertion_id="assertion-abc-1",
        )

    monkeypatch.setattr(sso_service, "_validate_saml_response", _valid)
    resp = client.post(
        f"/api/v1/sso/{wid}/acs", data={"SAMLResponse": "dmFsaWQ=", "RelayState": "/app"}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["session_token"]
    assert data["token_type"] == "Bearer"
    assert data["email"] == "newhire@acme.com"
    assert data["workspace_id"] == wid
    assert data["is_new_user"] is True

    # The provisioned identity is tenant-scoped to this workspace.
    with Factory() as s:
        identity = s.execute(select(ExternalIdentity)).scalars().first()
        assert identity.workspace_id == wid
        assert identity.idp_subject == "okta|user-123"
        assert identity.provisioned is True
        # An audit row records the provisioning.
        actions = {r.action for r in s.execute(select(AuditLog)).scalars().all()}
        assert "sso.provisioned" in actions


def test_acs_replay_rejected_409(sso_client, seeded, monkeypatch):
    client, _ = sso_client
    wid = seeded["workspace_id"]
    _oid, owner_key = seeded["owner"]
    assert _configure(client, wid, owner_key, enabled=True).status_code == 200

    def _valid(connection, saml_response, relay_state=""):
        return sso_service.ValidatedAssertion(
            subject="okta|user-9",
            email="dup@acme.com",
            assertion_id="assertion-replay-1",
        )

    monkeypatch.setattr(sso_service, "_validate_saml_response", _valid)
    first = client.post(f"/api/v1/sso/{wid}/acs", data={"SAMLResponse": "eA=="})
    assert first.status_code == 200, first.text
    second = client.post(f"/api/v1/sso/{wid}/acs", data={"SAMLResponse": "eA=="})
    assert second.status_code == 409, second.text


def test_acs_degrades_to_503_without_xmlsec(sso_client, seeded, monkeypatch):
    client, _ = sso_client
    wid = seeded["workspace_id"]
    _oid, owner_key = seeded["owner"]
    assert _configure(client, wid, owner_key, enabled=True).status_code == 200

    # Force the "native SAML toolkit absent" path deterministically.
    monkeypatch.setattr(sso_service, "saml_available", lambda: False)
    resp = client.post(f"/api/v1/sso/{wid}/acs", data={"SAMLResponse": "eA=="})
    assert resp.status_code == 503, resp.text


def test_acs_missing_saml_response_401(sso_client, seeded):
    client, _ = sso_client
    wid = seeded["workspace_id"]
    _oid, owner_key = seeded["owner"]
    assert _configure(client, wid, owner_key, enabled=True).status_code == 200
    resp = client.post(f"/api/v1/sso/{wid}/acs", data={})
    assert resp.status_code == 401, resp.text
