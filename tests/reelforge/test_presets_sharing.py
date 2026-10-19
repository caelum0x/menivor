"""SHARED BRAND KITS — shared-workspace preset tests (Phase: Shared Workspaces).

Exercises the sharing behaviour added to ``app.controllers.v1.me`` end-to-end
over a FastAPI ``TestClient`` with Postgres replaced by in-memory SQLite. No
external I/O.

Identity is switched per request via the ``x-api-key`` header: several users are
seeded, each with a distinct raw key (whose SHA-256 is stored as
``User.api_key_hash``), so the same client can act as the workspace owner, an
invited member, a second member, or a stranger simply by swapping the header —
mirroring how the real auth gate resolves the caller.

Scenarios covered
-----------------
* a member SHARES a preset to a workspace (``workspace_id`` in the body) and it
  is marked ``shared`` with its ``workspace_id`` in the response
* a teammate (owner / another member) sees the shared preset via ``GET /me/presets``
* a stranger (non-member) does NOT see it
* a non-member's share attempt -> ``403``; an unknown workspace -> ``403``
* a personal preset (no ``workspace_id``) stays private to its creator
* a shared preset is deletable by its creator OR a workspace ``admin``+
* a plain member who is neither creator nor admin cannot delete it -> ``403``
* a non-member cannot delete (and cannot learn it exists) -> ``404``
* a personal preset stays creator-only on delete -> ``404`` for a foreign id
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

import app.controllers.v1.me as me_mod
from app.models.db.base import Base
from app.models.db.models import User
from app.models.exception import HttpException
from app.services import workspaces as ws_service
from app.utils import utils


def _key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _headers(raw_key: str) -> dict[str, str]:
    return {"x-api-key": raw_key}


# =========================================================================== #
# Fixtures
# =========================================================================== #
@pytest.fixture()
def db_factory():
    """In-memory SQLite engine + session factory with the schema created."""
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


@pytest.fixture()
def me_client(monkeypatch, db_factory):
    """FastAPI TestClient wired to the ``me`` router over SQLite."""
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

    # me.py holds its own imported ``get_session`` reference — patch it there.
    monkeypatch.setattr(me_mod, "get_session", _fake_get_session)

    app = FastAPI()
    app.include_router(me_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


# Distinct identities; each raw key hashes to the stored ``api_key_hash``.
_SPECS = {
    "owner": ("owner@example.com", "owner-key"),
    "member": ("member@example.com", "member-key"),
    "member2": ("member2@example.com", "member2-key"),
    "stranger": ("stranger@example.com", "stranger-key"),
}


@pytest.fixture()
def users(db_factory):
    """Seed the four users; return {label: (user_id, raw_key)}."""
    Factory = db_factory
    seeded: dict[str, tuple[str, str]] = {}
    with Factory() as s:
        for label, (email, raw) in _SPECS.items():
            u = User(email=email, api_key_hash=_key_hash(raw), credits=0)
            s.add(u)
            s.flush()
            seeded[label] = (u.id, raw)
        s.commit()
    return seeded


@pytest.fixture()
def workspace(db_factory, users):
    """Create a workspace owned by ``owner`` with ``member`` + ``member2`` as
    plain members; return its id."""
    Factory = db_factory
    owner_id, _ = users["owner"]
    with Factory() as s:
        ws = ws_service.create_workspace(s, owner_id, "Acme Studio")
        wid = ws.id
        ws_service.invite_member(s, wid, owner_id, "member@example.com", "member")
        ws_service.invite_member(s, wid, owner_id, "member2@example.com", "member")
        s.commit()
    return wid


# =========================================================================== #
# Helpers
# =========================================================================== #
def _share_preset(client, raw_key, workspace_id, name="Team Kit", config=None):
    body = {"name": name, "config": config or {"layout": "hook_intro"}}
    if workspace_id is not None:
        body["workspace_id"] = workspace_id
    return client.post("/api/v1/me/presets", json=body, headers=_headers(raw_key))


def _list_preset_ids(client, raw_key) -> list[str]:
    resp = client.get("/api/v1/me/presets", headers=_headers(raw_key))
    assert resp.status_code == 200, resp.text
    return [p["id"] for p in resp.json()["data"]]


# =========================================================================== #
# Share + visibility
# =========================================================================== #
def test_member_shares_preset_marked_shared(me_client, users, workspace):
    client, _ = me_client
    _member_id, member_key = users["member"]

    resp = _share_preset(client, member_key, workspace, name="Brand A")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["name"] == "Brand A"
    assert data["workspace_id"] == workspace
    assert data["shared"] is True
    assert data["id"]


def test_teammate_sees_shared_preset_stranger_does_not(me_client, users, workspace):
    client, _ = me_client
    _member_id, member_key = users["member"]
    _owner_id, owner_key = users["owner"]
    _stranger_id, stranger_key = users["stranger"]

    shared = _share_preset(client, member_key, workspace)
    assert shared.status_code == 200, shared.text
    preset_id = shared.json()["data"]["id"]

    # The sharer sees their own preset.
    assert preset_id in _list_preset_ids(client, member_key)
    # A teammate (the owner) sees the shared preset.
    assert preset_id in _list_preset_ids(client, owner_key)
    # A stranger (non-member) never sees it.
    assert preset_id not in _list_preset_ids(client, stranger_key)
    assert _list_preset_ids(client, stranger_key) == []


def test_shared_preset_marked_shared_for_teammate(me_client, users, workspace):
    client, _ = me_client
    _member_id, member_key = users["member"]
    _owner_id, owner_key = users["owner"]

    _share_preset(client, member_key, workspace, name="Kit")
    resp = client.get("/api/v1/me/presets", headers=_headers(owner_key))
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["shared"] is True
    assert data[0]["workspace_id"] == workspace


# =========================================================================== #
# Share authorization
# =========================================================================== #
def test_non_member_share_attempt_forbidden_403(me_client, users, workspace):
    client, _ = me_client
    _stranger_id, stranger_key = users["stranger"]

    resp = _share_preset(client, stranger_key, workspace)
    assert resp.status_code == 403, resp.text


def test_share_to_unknown_workspace_forbidden_403(me_client, users, workspace):
    client, _ = me_client
    _member_id, member_key = users["member"]

    resp = _share_preset(client, member_key, "does-not-exist")
    assert resp.status_code == 403, resp.text


def test_share_requires_auth_401(me_client, users, workspace):
    client, _ = me_client
    resp = client.post(
        "/api/v1/me/presets",
        json={"name": "NoAuth", "workspace_id": workspace},
    )
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# Personal presets stay private
# =========================================================================== #
def test_personal_preset_not_shared_and_private(me_client, users, workspace):
    client, _ = me_client
    _member_id, member_key = users["member"]
    _owner_id, owner_key = users["owner"]

    resp = _share_preset(client, member_key, None, name="Private")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["workspace_id"] is None
    assert data["shared"] is False
    preset_id = data["id"]

    # A teammate does NOT see a personal (unshared) preset.
    assert preset_id not in _list_preset_ids(client, owner_key)
    # But the creator still sees it.
    assert preset_id in _list_preset_ids(client, member_key)


# =========================================================================== #
# Delete authorization
# =========================================================================== #
def test_creator_can_delete_own_shared_preset(me_client, users, workspace):
    client, _ = me_client
    _member_id, member_key = users["member"]

    preset_id = _share_preset(client, member_key, workspace).json()["data"]["id"]

    resp = client.delete(
        f"/api/v1/me/presets/{preset_id}", headers=_headers(member_key)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["deleted"] is True
    assert preset_id not in _list_preset_ids(client, member_key)


def test_workspace_admin_can_delete_shared_preset(me_client, users, workspace):
    client, _ = me_client
    _member_id, member_key = users["member"]
    _owner_id, owner_key = users["owner"]

    preset_id = _share_preset(client, member_key, workspace).json()["data"]["id"]

    # The owner (>= admin) can delete a teammate's shared brand kit.
    resp = client.delete(
        f"/api/v1/me/presets/{preset_id}", headers=_headers(owner_key)
    )
    assert resp.status_code == 200, resp.text
    assert preset_id not in _list_preset_ids(client, member_key)


def test_plain_member_cannot_delete_others_shared_preset_403(
    me_client, users, workspace
):
    client, _ = me_client
    _member_id, member_key = users["member"]
    _member2_id, member2_key = users["member2"]

    preset_id = _share_preset(client, member_key, workspace).json()["data"]["id"]

    # member2 is a plain member: neither creator nor admin -> 403 (they can see
    # it in their list, but may not delete it).
    resp = client.delete(
        f"/api/v1/me/presets/{preset_id}", headers=_headers(member2_key)
    )
    assert resp.status_code == 403, resp.text
    # Still visible + still present.
    assert preset_id in _list_preset_ids(client, member2_key)


def test_non_member_cannot_delete_shared_preset_404(me_client, users, workspace):
    client, _ = me_client
    _member_id, member_key = users["member"]
    _stranger_id, stranger_key = users["stranger"]

    preset_id = _share_preset(client, member_key, workspace).json()["data"]["id"]

    # A non-member cannot even learn the preset exists -> 404 (no leak).
    resp = client.delete(
        f"/api/v1/me/presets/{preset_id}", headers=_headers(stranger_key)
    )
    assert resp.status_code == 404, resp.text
    # Untouched: the creator still sees it.
    assert preset_id in _list_preset_ids(client, member_key)


def test_personal_preset_delete_is_creator_only_404(me_client, users, workspace):
    client, _ = me_client
    _member_id, member_key = users["member"]
    _owner_id, owner_key = users["owner"]

    preset_id = _share_preset(client, member_key, None).json()["data"]["id"]

    # Even the workspace owner cannot delete another user's PERSONAL preset; it
    # is indistinguishable from a missing one -> 404.
    resp = client.delete(
        f"/api/v1/me/presets/{preset_id}", headers=_headers(owner_key)
    )
    assert resp.status_code == 404, resp.text
    assert preset_id in _list_preset_ids(client, member_key)


def test_delete_unknown_preset_404(me_client, users, workspace):
    client, _ = me_client
    _member_id, member_key = users["member"]
    resp = client.delete(
        "/api/v1/me/presets/does-not-exist", headers=_headers(member_key)
    )
    assert resp.status_code == 404, resp.text
