"""BYOK domain tests — encrypted store, secret-free views, revoke, resolve+audit.

Secrets are write-only: a stored key's plaintext is never returned by any
endpoint and is encrypted at rest. Identity via ``x-api-key``. In-memory SQLite;
a real Fernet key is set so encryption/decryption round-trips.
"""

from __future__ import annotations

import hashlib
import importlib
from contextlib import contextmanager

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.domains.byok.service import BYOKService
from app.models.db.base import Base
from app.models.db.marketplace import ProviderKey
from app.models.db.models import User
from app.models.exception import HttpException
from app.utils import utils

byok_mod = importlib.import_module("app.domains.byok.router")


@pytest.fixture(autouse=True)
def _fernet_key(monkeypatch):
    # A real Fernet secret so encrypt/decrypt round-trips in tests.
    monkeypatch.setenv("SOCIAL_TOKEN_KEY", Fernet.generate_key().decode())


def _key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@pytest.fixture()
def factory():
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
def env(monkeypatch, factory):
    @contextmanager
    def _fake_get_session():
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr(byok_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(byok_mod, "_DB_IMPORT_ERROR", None)
    app = FastAPI()
    app.include_router(byok_mod.router)

    def _http_handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), factory


@pytest.fixture()
def users(factory):
    out = {}
    with factory() as s:
        for label, raw in (("alice", "alice-key"), ("bob", "bob-key")):
            u = User(email=f"{label}@example.com", api_key_hash=_key_hash(raw))
            s.add(u)
            s.flush()
            out[label] = (u.id, raw)
        s.commit()
    return out


def _headers(raw: str) -> dict[str, str]:
    return {"x-api-key": raw}


# --------------------------------------------------------------------------- #
# HTTP: store never returns secret; encrypted at rest; owner scoping
# --------------------------------------------------------------------------- #
def test_add_key_never_returns_secret(env, users):
    client, factory = env
    _uid, key = users["alice"]
    resp = client.post(
        "/api/v1/byok/keys",
        json={"provider_key": "openrouter", "secret": "sk-supersecret-123", "label": "mine"},
        headers=_headers(key),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    # No raw secret / ciphertext anywhere in the response; only a masked prefix.
    body = resp.text
    assert "sk-supersecret-123" not in body
    assert data["key_prefix"] == "sk-…23"
    assert data["status"] == "active"

    # Stored ciphertext is not the plaintext.
    with factory() as s:
        row = s.query(ProviderKey).first()
        assert row.encrypted_secret != "sk-supersecret-123"
        assert row.encrypted_secret  # non-empty ciphertext


def test_list_is_owner_scoped_and_secret_free(env, users):
    client, _ = env
    _a, akey = users["alice"]
    _b, bkey = users["bob"]
    client.post(
        "/api/v1/byok/keys",
        json={"provider_key": "openrouter", "secret": "sk-alice-xyz"},
        headers=_headers(akey),
    )
    # Bob sees none of Alice's keys.
    bob = client.get("/api/v1/byok/keys", headers=_headers(bkey))
    assert bob.status_code == 200
    assert bob.json()["data"]["keys"] == []
    # Alice sees hers, without a secret.
    alice = client.get("/api/v1/byok/keys", headers=_headers(akey))
    keys = alice.json()["data"]["keys"]
    assert len(keys) == 1
    assert "encrypted_secret" not in keys[0]
    assert "secret" not in keys[0]


def test_revoke_owner_scoped(env, users):
    client, _ = env
    _a, akey = users["alice"]
    _b, bkey = users["bob"]
    created = client.post(
        "/api/v1/byok/keys",
        json={"provider_key": "openrouter", "secret": "sk-1"},
        headers=_headers(akey),
    ).json()["data"]
    key_id = created["id"]
    # Bob cannot revoke Alice's key (404, no existence leak).
    assert client.delete(f"/api/v1/byok/keys/{key_id}", headers=_headers(bkey)).status_code == 404
    # Alice can.
    revoked = client.delete(f"/api/v1/byok/keys/{key_id}", headers=_headers(akey))
    assert revoked.status_code == 200
    assert revoked.json()["data"]["status"] == "revoked"


def test_add_requires_auth(env, users):
    client, _ = env
    resp = client.post("/api/v1/byok/keys", json={"provider_key": "x", "secret": "y"})
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# Service: resolve_secret decrypts highest-priority active key + audits use
# --------------------------------------------------------------------------- #
def test_resolve_secret_picks_priority_and_audits(env, users):
    _client, factory = env
    uid, _ = users["alice"]
    with factory() as s:
        svc = BYOKService(s)
        svc.add_key(uid, provider_key="openrouter", secret="low", priority=1)
        svc.add_key(uid, provider_key="openrouter", secret="high", priority=5)
        s.commit()
    with factory() as s:
        secret = BYOKService(s).resolve_secret(uid, "openrouter")
        s.commit()
    assert secret == "high"
    # Use is audited on the chosen key.
    with factory() as s:
        row = (
            s.query(ProviderKey)
            .filter(ProviderKey.priority == 5)
            .first()
        )
        assert row.use_count == 1
        assert row.last_used_at is not None


def test_resolve_secret_none_when_revoked(env, users):
    _client, factory = env
    uid, _ = users["alice"]
    with factory() as s:
        svc = BYOKService(s)
        view = svc.add_key(uid, provider_key="heygen", secret="k")
        svc.revoke_key(uid, view["id"])
        s.commit()
    with factory() as s:
        assert BYOKService(s).resolve_secret(uid, "heygen") is None
