"""Team Workspaces v1 API tests.

Exercises ``app.controllers.v1.workspaces`` end-to-end over a FastAPI
``TestClient`` with Postgres replaced by in-memory SQLite. No external I/O.

Identity is switched per request via the ``x-api-key`` header: several users are
seeded, each with a distinct raw key (whose SHA-256 is stored as
``User.api_key_hash``), so the same client can act as the owner, an invited
member, or a stranger simply by swapping the header — mirroring how the real
auth gate resolves the caller.

Scenarios covered
-----------------
* owner creates a workspace (becomes ``owner``) and lists it via ``/me/workspaces``
* owner invites a second user; that user then appears in the roster and can list it
* a plain member's invite attempt -> ``403``
* a non-member listing members -> ``403`` (real workspace) / ``404`` (unknown id)
* inviting an unknown email -> ``400``
* inviting an already-member -> ``409``
* role change (admin+) and self-removal / leave
* auth required (missing key -> ``401``)
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

import app.controllers.v1.workspaces as ws_mod
from app.models.db.base import Base
from app.models.db.models import User
from app.models.exception import HttpException
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
def ws_client(monkeypatch, db_factory):
    """FastAPI TestClient wired to the workspaces router over SQLite."""
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

    # The controller imported get_session into its own namespace (from jobs).
    monkeypatch.setattr(ws_mod, "get_session", _fake_get_session)

    app = FastAPI()
    app.include_router(ws_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


@pytest.fixture()
def users(db_factory):
    """Seed three users; return {label: (user_id, raw_key)}."""
    Factory = db_factory
    seeded: dict[str, tuple[str, str]] = {}
    specs = {
        "owner": ("owner@example.com", "owner-key"),
        "member": ("member@example.com", "member-key"),
        "stranger": ("stranger@example.com", "stranger-key"),
    }
    with Factory() as s:
        for label, (email, raw) in specs.items():
            u = User(email=email, api_key_hash=_key_hash(raw), credits=0)
            s.add(u)
            s.flush()
            seeded[label] = (u.id, raw)
        s.commit()
    return seeded


# Note: ``ws_client`` and ``users`` both build their own factory from the shared
# ``db_factory`` fixture — pytest caches a fixture instance per test, so both
# receive the *same* Factory (and thus the same in-memory engine).


def _create_workspace(client, raw_key: str, name: str = "Acme Studio"):
    return client.post(
        "/api/v1/workspaces", json={"name": name}, headers=_headers(raw_key)
    )


# =========================================================================== #
# Create + list
# =========================================================================== #
def test_create_workspace_makes_caller_owner(ws_client, users):
    client, _ = ws_client
    owner_id, owner_key = users["owner"]

    resp = _create_workspace(client, owner_key, "Acme Studio")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["name"] == "Acme Studio"
    assert data["owner_id"] == owner_id
    assert data["role"] == "owner"
    assert data["id"]


def test_list_my_workspaces_returns_role(ws_client, users):
    client, _ = ws_client
    _owner_id, owner_key = users["owner"]

    _create_workspace(client, owner_key, "One")
    _create_workspace(client, owner_key, "Two")

    resp = client.get("/api/v1/me/workspaces", headers=_headers(owner_key))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert {w["name"] for w in data} == {"One", "Two"}
    assert all(w["role"] == "owner" for w in data)


def test_create_workspace_blank_name_400(ws_client, users):
    client, _ = ws_client
    _owner_id, owner_key = users["owner"]
    resp = _create_workspace(client, owner_key, "   ")
    assert resp.status_code == 400, resp.text


def test_create_requires_auth(ws_client, users):
    client, _ = ws_client
    resp = client.post("/api/v1/workspaces", json={"name": "NoAuth"})
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# Invite + roster
# =========================================================================== #
def _owner_workspace_id(client, owner_key: str) -> str:
    resp = _create_workspace(client, owner_key)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["id"]


def test_owner_invites_second_user_and_roster_lists_them(ws_client, users):
    client, _ = ws_client
    _owner_id, owner_key = users["owner"]
    member_id, member_key = users["member"]
    wid = _owner_workspace_id(client, owner_key)

    # Owner invites the member by email (default role = member).
    resp = client.post(
        f"/api/v1/workspaces/{wid}/invite",
        json={"email": "member@example.com"},
        headers=_headers(owner_key),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["user_id"] == member_id
    assert resp.json()["data"]["role"] == "member"

    # The invited member can now list the roster and sees both users.
    resp = client.get(
        f"/api/v1/workspaces/{wid}/members", headers=_headers(member_key)
    )
    assert resp.status_code == 200, resp.text
    roster = resp.json()["data"]
    by_email = {m["email"]: m["role"] for m in roster}
    assert by_email == {
        "owner@example.com": "owner",
        "member@example.com": "member",
    }


def test_invite_admin_can_be_granted_then_admin_invites(ws_client, users):
    client, _ = ws_client
    _owner_id, owner_key = users["owner"]
    _member_id, member_key = users["member"]
    stranger_id, _stranger_key = users["stranger"]
    wid = _owner_workspace_id(client, owner_key)

    # Owner promotes the member straight to admin via invite.
    resp = client.post(
        f"/api/v1/workspaces/{wid}/invite",
        json={"email": "member@example.com", "role": "admin"},
        headers=_headers(owner_key),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["role"] == "admin"

    # That admin can now invite a third user.
    resp = client.post(
        f"/api/v1/workspaces/{wid}/invite",
        json={"email": "stranger@example.com"},
        headers=_headers(member_key),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["user_id"] == stranger_id


def test_member_invite_attempt_forbidden_403(ws_client, users):
    client, _ = ws_client
    _owner_id, owner_key = users["owner"]
    _member_id, member_key = users["member"]
    wid = _owner_workspace_id(client, owner_key)

    # Add member as a plain member first.
    client.post(
        f"/api/v1/workspaces/{wid}/invite",
        json={"email": "member@example.com"},
        headers=_headers(owner_key),
    )

    # A plain member cannot invite anyone.
    resp = client.post(
        f"/api/v1/workspaces/{wid}/invite",
        json={"email": "stranger@example.com"},
        headers=_headers(member_key),
    )
    assert resp.status_code == 403, resp.text


def test_non_member_listing_members_forbidden_403(ws_client, users):
    client, _ = ws_client
    _owner_id, owner_key = users["owner"]
    _stranger_id, stranger_key = users["stranger"]
    wid = _owner_workspace_id(client, owner_key)

    # A real workspace the stranger is not a member of -> 403 (not a 404 leak).
    resp = client.get(
        f"/api/v1/workspaces/{wid}/members", headers=_headers(stranger_key)
    )
    assert resp.status_code == 403, resp.text


def test_members_unknown_workspace_404(ws_client, users):
    client, _ = ws_client
    _owner_id, owner_key = users["owner"]
    resp = client.get(
        "/api/v1/workspaces/does-not-exist/members", headers=_headers(owner_key)
    )
    assert resp.status_code == 404, resp.text


def test_invite_unknown_email_creates_pending_invite(ws_client, users):
    # Inviting an email with no account no longer fails: it creates a pending,
    # token-backed invite the recipient accepts after signing up.
    client, _ = ws_client
    _owner_id, owner_key = users["owner"]
    wid = _owner_workspace_id(client, owner_key)

    resp = client.post(
        f"/api/v1/workspaces/{wid}/invite",
        json={"email": "nobody@nowhere.example"},
        headers=_headers(owner_key),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "pending"
    assert data["invitee_has_account"] is False
    assert data["token"]
    assert data["accept_url"].endswith(data["token"])


def test_invite_duplicate_member_409(ws_client, users):
    client, _ = ws_client
    _owner_id, owner_key = users["owner"]
    wid = _owner_workspace_id(client, owner_key)

    first = client.post(
        f"/api/v1/workspaces/{wid}/invite",
        json={"email": "member@example.com"},
        headers=_headers(owner_key),
    )
    assert first.status_code == 200, first.text

    dup = client.post(
        f"/api/v1/workspaces/{wid}/invite",
        json={"email": "member@example.com"},
        headers=_headers(owner_key),
    )
    assert dup.status_code == 409, dup.text


def test_invite_duplicate_race_unique_constraint_409(ws_client, users, monkeypatch):
    """A duplicate that slips past the read-time pre-check maps to 409, not 500.

    Simulates two concurrent admin sessions: both read ``get_membership`` as
    ``None`` and reach ``add_member``. We reproduce that window by forcing the
    invitee's duplicate pre-check to return ``None`` after a row already exists,
    so the second flush hits the ``(workspace_id, user_id)`` UNIQUE constraint
    and raises ``IntegrityError`` — which the controller must surface as 409.
    """
    client, _ = ws_client
    _owner_id, owner_key = users["owner"]
    member_id, _member_key = users["member"]
    wid = _owner_workspace_id(client, owner_key)

    # First invite creates the real membership row.
    first = client.post(
        f"/api/v1/workspaces/{wid}/invite",
        json={"email": "member@example.com"},
        headers=_headers(owner_key),
    )
    assert first.status_code == 200, first.text

    # Force the invitee's duplicate pre-check to miss the existing row (the
    # concurrent read-time window), leaving only the DB UNIQUE constraint.
    original = ws_mod.ws_service.WorkspaceRepository.get_membership

    def _blind_invitee(self, workspace_id, user_id):
        if user_id == member_id:
            return None
        return original(self, workspace_id, user_id)

    monkeypatch.setattr(
        ws_mod.ws_service.WorkspaceRepository, "get_membership", _blind_invitee
    )

    dup = client.post(
        f"/api/v1/workspaces/{wid}/invite",
        json={"email": "member@example.com"},
        headers=_headers(owner_key),
    )
    assert dup.status_code == 409, dup.text


def test_invite_unknown_workspace_404(ws_client, users):
    client, _ = ws_client
    _owner_id, owner_key = users["owner"]
    resp = client.post(
        "/api/v1/workspaces/nope/invite",
        json={"email": "member@example.com"},
        headers=_headers(owner_key),
    )
    assert resp.status_code == 404, resp.text


# =========================================================================== #
# Role change + removal + leave
# =========================================================================== #
def test_owner_sets_member_role_to_admin(ws_client, users):
    client, _ = ws_client
    _owner_id, owner_key = users["owner"]
    member_id, member_key = users["member"]
    wid = _owner_workspace_id(client, owner_key)

    client.post(
        f"/api/v1/workspaces/{wid}/invite",
        json={"email": "member@example.com"},
        headers=_headers(owner_key),
    )

    resp = client.post(
        f"/api/v1/workspaces/{wid}/members/{member_id}/role",
        json={"role": "admin"},
        headers=_headers(owner_key),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["role"] == "admin"

    # The promoted member now sees their role as admin in /me/workspaces.
    resp = client.get("/api/v1/me/workspaces", headers=_headers(member_key))
    assert resp.json()["data"][0]["role"] == "admin"


def test_set_role_invalid_role_400(ws_client, users):
    client, _ = ws_client
    _owner_id, owner_key = users["owner"]
    member_id, _member_key = users["member"]
    wid = _owner_workspace_id(client, owner_key)
    client.post(
        f"/api/v1/workspaces/{wid}/invite",
        json={"email": "member@example.com"},
        headers=_headers(owner_key),
    )

    resp = client.post(
        f"/api/v1/workspaces/{wid}/members/{member_id}/role",
        json={"role": "wizard"},
        headers=_headers(owner_key),
    )
    assert resp.status_code == 400, resp.text


def test_member_leaves_workspace(ws_client, users):
    client, _ = ws_client
    _owner_id, owner_key = users["owner"]
    _member_id, member_key = users["member"]
    wid = _owner_workspace_id(client, owner_key)
    client.post(
        f"/api/v1/workspaces/{wid}/invite",
        json={"email": "member@example.com"},
        headers=_headers(owner_key),
    )

    resp = client.post(
        f"/api/v1/workspaces/{wid}/leave", headers=_headers(member_key)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["left"] is True

    # After leaving, the ex-member can no longer read the roster.
    resp = client.get(
        f"/api/v1/workspaces/{wid}/members", headers=_headers(member_key)
    )
    assert resp.status_code == 403, resp.text


def test_owner_cannot_leave_403(ws_client, users):
    client, _ = ws_client
    _owner_id, owner_key = users["owner"]
    wid = _owner_workspace_id(client, owner_key)

    resp = client.post(
        f"/api/v1/workspaces/{wid}/leave", headers=_headers(owner_key)
    )
    assert resp.status_code == 403, resp.text


def test_admin_removes_member(ws_client, users):
    client, _ = ws_client
    _owner_id, owner_key = users["owner"]
    member_id, _member_key = users["member"]
    wid = _owner_workspace_id(client, owner_key)
    client.post(
        f"/api/v1/workspaces/{wid}/invite",
        json={"email": "member@example.com"},
        headers=_headers(owner_key),
    )

    resp = client.delete(
        f"/api/v1/workspaces/{wid}/members/{member_id}",
        headers=_headers(owner_key),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["removed"] is True

    roster = client.get(
        f"/api/v1/workspaces/{wid}/members", headers=_headers(owner_key)
    ).json()["data"]
    assert all(m["user_id"] != member_id for m in roster)


def test_member_cannot_remove_other_member_403(ws_client, users):
    client, _ = ws_client
    _owner_id, owner_key = users["owner"]
    _member_id, member_key = users["member"]
    stranger_id, _stranger_key = users["stranger"]
    wid = _owner_workspace_id(client, owner_key)
    # Two plain members.
    client.post(
        f"/api/v1/workspaces/{wid}/invite",
        json={"email": "member@example.com"},
        headers=_headers(owner_key),
    )
    client.post(
        f"/api/v1/workspaces/{wid}/invite",
        json={"email": "stranger@example.com"},
        headers=_headers(owner_key),
    )

    # A plain member cannot remove another member.
    resp = client.delete(
        f"/api/v1/workspaces/{wid}/members/{stranger_id}",
        headers=_headers(member_key),
    )
    assert resp.status_code == 403, resp.text
