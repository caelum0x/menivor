"""Unit tests for the append-only, tenant-scoped audit trail (Access & Governance).

Runs against an in-memory SQLite DB built from the live ORM metadata. Covered
behaviour:

* :func:`audit.record` appends immutable rows (newest-first read back);
* the trail is APPEND-ONLY — neither the service nor the repository exposes any
  update / delete;
* :func:`audit.query` is ``audit.read`` gated: a member of workspace *B* cannot
  read workspace *A*'s trail (tenant isolation), a non-member is denied, an
  under-privileged (viewer) member is denied, and an admin/owner is allowed;
* the query returns ONLY the target workspace's rows.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.base import Base
from app.models.db.models import User, Workspace, WorkspaceMember
from app.models.db.repositories import AuditLogRepository
from app.services import audit, rbac


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture()
def session_factory():
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


@contextmanager
def _session(factory):
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _make_user(session, email: str) -> str:
    user = User(email=email, credits=0)
    session.add(user)
    session.flush()
    return user.id


def _make_workspace(session, owner_id: str, name: str = "Tenant") -> str:
    ws = Workspace(owner_id=owner_id, name=name)
    session.add(ws)
    session.flush()
    return ws.id


def _add_member(session, workspace_id: str, user_id: str, role: str) -> None:
    session.add(
        WorkspaceMember(
            workspace_id=workspace_id, user_id=user_id, role=role
        )
    )
    session.flush()


# --------------------------------------------------------------------------- #
# record — append-only insert
# --------------------------------------------------------------------------- #
def test_record_appends_row_with_fields(session_factory):
    with _session(session_factory) as s:
        actor = _make_user(s, "actor@example.com")
        ws = _make_workspace(s, actor)

        row = audit.record(
            s,
            actor_user_id=actor,
            action="members.role_changed",
            workspace_id=ws,
            target_type="user",
            target_id="target-123",
            metadata={"from": "viewer", "to": "editor"},
            ip="203.0.113.7",
        )

        assert row.id is not None
        assert row.actor_user_id == actor
        assert row.action == "members.role_changed"
        assert row.workspace_id == ws
        assert row.target_type == "user"
        assert row.target_id == "target-123"
        assert row.meta == {"from": "viewer", "to": "editor"}
        assert row.ip == "203.0.113.7"


def test_record_copies_metadata_defensively(session_factory):
    with _session(session_factory) as s:
        actor = _make_user(s, "actor@example.com")
        ws = _make_workspace(s, actor)
        payload = {"k": "v"}
        row = audit.record(
            s, actor_user_id=actor, action="x", workspace_id=ws, metadata=payload
        )
        payload["k"] = "mutated"
        assert row.meta == {"k": "v"}


def test_record_requires_actor_and_action(session_factory):
    with _session(session_factory) as s:
        ws_owner = _make_user(s, "o@example.com")
        ws = _make_workspace(s, ws_owner)
        with pytest.raises(ValueError):
            audit.record(s, actor_user_id="", action="x", workspace_id=ws)
        with pytest.raises(ValueError):
            audit.record(s, actor_user_id=ws_owner, action="  ", workspace_id=ws)


def test_trail_is_append_only_no_mutation_api():
    """Neither the repository nor the service exposes an update/delete."""
    for name in ("update", "delete", "remove", "edit", "set"):
        assert not hasattr(AuditLogRepository, name)
    assert not hasattr(audit, "update")
    assert not hasattr(audit, "delete")


# --------------------------------------------------------------------------- #
# query — audit.read gated + tenant scoped
# --------------------------------------------------------------------------- #
def test_query_returns_workspace_rows_newest_first(session_factory):
    with _session(session_factory) as s:
        owner = _make_user(s, "owner@example.com")
        ws = _make_workspace(s, owner)
        _add_member(s, ws, owner, rbac.ROLE_OWNER)

        audit.record(s, actor_user_id=owner, action="a1", workspace_id=ws)
        audit.record(s, actor_user_id=owner, action="a2", workspace_id=ws)
        audit.record(s, actor_user_id=owner, action="a3", workspace_id=ws)

        rows = audit.query(s, ws, owner, limit=50, offset=0)
        actions = [r.action for r in rows]
        assert actions == ["a3", "a2", "a1"]


def test_query_denies_non_member(session_factory):
    with _session(session_factory) as s:
        owner = _make_user(s, "owner@example.com")
        outsider = _make_user(s, "outsider@example.com")
        ws = _make_workspace(s, owner)
        _add_member(s, ws, owner, rbac.ROLE_OWNER)
        audit.record(s, actor_user_id=owner, action="a1", workspace_id=ws)

        with pytest.raises(PermissionError):
            audit.query(s, ws, outsider)


def test_query_denies_underprivileged_member(session_factory):
    """A viewer lacks audit.read and cannot read the trail."""
    with _session(session_factory) as s:
        owner = _make_user(s, "owner@example.com")
        viewer = _make_user(s, "viewer@example.com")
        ws = _make_workspace(s, owner)
        _add_member(s, ws, owner, rbac.ROLE_OWNER)
        _add_member(s, ws, viewer, rbac.ROLE_VIEWER)
        audit.record(s, actor_user_id=owner, action="a1", workspace_id=ws)

        with pytest.raises(PermissionError):
            audit.query(s, ws, viewer)


def test_query_allows_admin(session_factory):
    with _session(session_factory) as s:
        owner = _make_user(s, "owner@example.com")
        admin = _make_user(s, "admin@example.com")
        ws = _make_workspace(s, owner)
        _add_member(s, ws, owner, rbac.ROLE_OWNER)
        _add_member(s, ws, admin, rbac.ROLE_ADMIN)
        audit.record(s, actor_user_id=owner, action="a1", workspace_id=ws)

        rows = audit.query(s, ws, admin)
        assert [r.action for r in rows] == ["a1"]


def test_query_is_tenant_scoped_member_of_b_cannot_read_a(session_factory):
    """A member (even owner) of workspace B cannot read workspace A's trail."""
    with _session(session_factory) as s:
        owner_a = _make_user(s, "owner-a@example.com")
        owner_b = _make_user(s, "owner-b@example.com")
        ws_a = _make_workspace(s, owner_a, "A")
        ws_b = _make_workspace(s, owner_b, "B")
        _add_member(s, ws_a, owner_a, rbac.ROLE_OWNER)
        _add_member(s, ws_b, owner_b, rbac.ROLE_OWNER)

        audit.record(s, actor_user_id=owner_a, action="secret-a", workspace_id=ws_a)
        audit.record(s, actor_user_id=owner_b, action="b-event", workspace_id=ws_b)

        # owner_b is not a member of A -> denied outright (tenant isolation).
        with pytest.raises(PermissionError):
            audit.query(s, ws_a, owner_b)

        # owner_b reading their OWN workspace sees only B's rows, never A's.
        rows_b = audit.query(s, ws_b, owner_b)
        assert [r.action for r in rows_b] == ["b-event"]
        assert all(r.workspace_id == ws_b for r in rows_b)
