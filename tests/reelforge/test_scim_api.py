"""SCIM 2.0 v1 API tests (Identity & SSO, Epic 2).

Exercises ``app.controllers.v1.scim`` end-to-end over a FastAPI ``TestClient`` with
Postgres replaced by in-memory SQLite. No external I/O.

Covered
-------
* TENANT ISOLATION — a SCIM bearer token minted for workspace *B* is rejected
  (``401``) against workspace *A*, and can never provision/read there;
* ``provision`` creates a tenant-scoped SCIM User; ``deactivate`` (DELETE)
  soft-disables it (``active=false``); ``list`` is workspace-scoped;
* a missing bearer -> ``401`` with a SCIM Error envelope;
* token management is RBAC-gated (``workspace.settings``): a viewer -> ``403``; the
  raw token is shown once on mint and NEVER on a list.
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

import app.controllers.v1.scim as scim_mod
from app.models.db.base import Base
from app.models.db.models import User, Workspace, WorkspaceMember
from app.models.exception import HttpException
from app.utils import utils


def _key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _headers(raw_key: str) -> dict[str, str]:
    return {"x-api-key": raw_key}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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
def scim_client(monkeypatch, db_factory):
    Factory = db_factory

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

    monkeypatch.setattr(scim_mod, "get_session", _fake_get_session)

    app = FastAPI()
    app.include_router(scim_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


@pytest.fixture()
def seeded(db_factory):
    """Seed two independent workspaces A and B, each with an owner + a viewer in A."""
    Factory = db_factory
    out: dict[str, object] = {}
    with Factory() as s:
        owner_a = User(email="ownerA@ex.com", api_key_hash=_key_hash("ownerA-key"))
        owner_b = User(email="ownerB@ex.com", api_key_hash=_key_hash("ownerB-key"))
        viewer_a = User(email="viewerA@ex.com", api_key_hash=_key_hash("viewerA-key"))
        s.add_all([owner_a, owner_b, viewer_a])
        s.flush()
        ws_a = Workspace(owner_id=owner_a.id, name="Acme-A")
        ws_b = Workspace(owner_id=owner_b.id, name="Beta-B")
        s.add_all([ws_a, ws_b])
        s.flush()
        s.add_all(
            [
                WorkspaceMember(workspace_id=ws_a.id, user_id=owner_a.id, role="owner"),
                WorkspaceMember(workspace_id=ws_a.id, user_id=viewer_a.id, role="viewer"),
                WorkspaceMember(workspace_id=ws_b.id, user_id=owner_b.id, role="owner"),
            ]
        )
        s.commit()
        out["ws_a"] = ws_a.id
        out["ws_b"] = ws_b.id
        out["owner_a_key"] = "ownerA-key"
        out["owner_b_key"] = "ownerB-key"
        out["viewer_a_key"] = "viewerA-key"
    return out


def _mint_token(client, wid, owner_key) -> str:
    resp = client.post(
        f"/api/v1/me/workspaces/{wid}/scim/tokens", headers=_headers(owner_key)
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["token"], "raw token must be shown once on mint"
    return data["token"]


# =========================================================================== #
# Token management (RBAC workspace.settings)
# =========================================================================== #
def test_viewer_cannot_mint_token_403(scim_client, seeded):
    client, _ = scim_client
    resp = client.post(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/scim/tokens",
        headers=_headers(seeded["viewer_a_key"]),
    )
    assert resp.status_code == 403, resp.text


def test_mint_shows_token_once_list_hides_it(scim_client, seeded):
    client, _ = scim_client
    wid = seeded["ws_a"]
    raw = _mint_token(client, wid, seeded["owner_a_key"])
    listing = client.get(
        f"/api/v1/me/workspaces/{wid}/scim/tokens",
        headers=_headers(seeded["owner_a_key"]),
    )
    assert listing.status_code == 200, listing.text
    rows = listing.json()["data"]
    assert len(rows) == 1
    assert rows[0]["token"] is None
    assert raw not in listing.text


def test_token_mgmt_requires_auth_401(scim_client, seeded):
    client, _ = scim_client
    resp = client.post(f"/api/v1/me/workspaces/{seeded['ws_a']}/scim/tokens")
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# Provisioning (bearer-token authenticated; tenant-scoped)
# =========================================================================== #
def test_missing_bearer_401(scim_client, seeded):
    client, _ = scim_client
    resp = client.get(f"/api/v1/scim/v2/{seeded['ws_a']}/Users")
    assert resp.status_code == 401, resp.text
    body = resp.json()
    assert body["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]


def test_wrong_workspace_bearer_rejected(scim_client, seeded):
    """A token minted for workspace B can NEVER touch workspace A."""
    client, _ = scim_client
    token_b = _mint_token(client, seeded["ws_b"], seeded["owner_b_key"])
    resp = client.get(
        f"/api/v1/scim/v2/{seeded['ws_a']}/Users", headers=_bearer(token_b)
    )
    assert resp.status_code in (401, 403), resp.text


def test_provision_get_and_deactivate(scim_client, seeded):
    client, _ = scim_client
    wid = seeded["ws_a"]
    token = _mint_token(client, wid, seeded["owner_a_key"])

    payload = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "externalId": "okta|abc",
        "userName": "abc@acme.com",
        "emails": [{"value": "abc@acme.com", "primary": True}],
        "active": True,
    }
    created = client.post(
        f"/api/v1/scim/v2/{wid}/Users", json=payload, headers=_bearer(token)
    )
    assert created.status_code == 201, created.text
    resource = created.json()
    assert resource["active"] is True
    rid = resource["id"]

    got = client.get(
        f"/api/v1/scim/v2/{wid}/Users/{rid}", headers=_bearer(token)
    )
    assert got.status_code == 200, got.text
    assert got.json()["active"] is True

    deleted = client.delete(
        f"/api/v1/scim/v2/{wid}/Users/{rid}", headers=_bearer(token)
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["active"] is False

    after = client.get(
        f"/api/v1/scim/v2/{wid}/Users/{rid}", headers=_bearer(token)
    )
    assert after.json()["active"] is False


def test_list_is_workspace_scoped(scim_client, seeded):
    client, _ = scim_client
    token_a = _mint_token(client, seeded["ws_a"], seeded["owner_a_key"])
    token_b = _mint_token(client, seeded["ws_b"], seeded["owner_b_key"])

    client.post(
        f"/api/v1/scim/v2/{seeded['ws_a']}/Users",
        json={"externalId": "in-a", "userName": "a@acme.com"},
        headers=_bearer(token_a),
    )
    client.post(
        f"/api/v1/scim/v2/{seeded['ws_b']}/Users",
        json={"externalId": "in-b", "userName": "b@beta.com"},
        headers=_bearer(token_b),
    )

    list_a = client.get(
        f"/api/v1/scim/v2/{seeded['ws_a']}/Users", headers=_bearer(token_a)
    ).json()
    subjects_a = {r["externalId"] for r in list_a["Resources"]}
    assert subjects_a == {"in-a"}
    assert "in-b" not in subjects_a


def test_patch_deactivate(scim_client, seeded):
    client, _ = scim_client
    wid = seeded["ws_a"]
    token = _mint_token(client, wid, seeded["owner_a_key"])
    created = client.post(
        f"/api/v1/scim/v2/{wid}/Users",
        json={"externalId": "okta|p", "userName": "p@acme.com"},
        headers=_bearer(token),
    ).json()
    rid = created["id"]
    patch = client.patch(
        f"/api/v1/scim/v2/{wid}/Users/{rid}",
        json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "active", "value": False}],
        },
        headers=_bearer(token),
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["active"] is False


def test_get_unknown_user_404(scim_client, seeded):
    client, _ = scim_client
    wid = seeded["ws_a"]
    token = _mint_token(client, wid, seeded["owner_a_key"])
    resp = client.get(
        f"/api/v1/scim/v2/{wid}/Users/does-not-exist", headers=_bearer(token)
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
