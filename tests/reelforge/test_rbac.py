"""Unit tests for the Casbin-backed RBAC decision engine (Access & Governance).

Runs against an in-memory SQLite DB built from the live ORM metadata so the
tenant-isolation half of every decision exercises the real
:class:`WorkspaceMember` lookup — no fakes. Covered behaviour:

* the role -> permission matrix (viewer cannot members.manage, owner can, editor
  can jobs.create, billing can billing.manage, admin cannot billing.manage, ...);
* role inheritance (owner/admin inherit lower-role permissions);
* ``require_permission`` DENIES a non-member (tenant isolation) and an
  under-privileged member, and ALLOWS a privileged member;
* an unknown / legacy role (``member``) carries no policy -> denied everything
  (fail-closed);
* ``effective_permissions`` reflects the live policy + inheritance.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.base import Base
from app.models.db.models import User, Workspace, WorkspaceMember
from app.services import rbac


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
    """Insert a membership row with an arbitrary (enterprise) role directly."""
    session.add(
        WorkspaceMember(
            workspace_id=workspace_id, user_id=user_id, role=role
        )
    )
    session.flush()


# --------------------------------------------------------------------------- #
# Pure role -> permission matrix (no DB)
# --------------------------------------------------------------------------- #
def test_owner_has_every_permission():
    for perm in rbac.PERMISSIONS:
        assert rbac.enforce(rbac.ROLE_OWNER, perm) is True
    assert rbac.effective_permissions(rbac.ROLE_OWNER) == rbac.PERMISSIONS


def test_viewer_can_read_but_not_manage_members():
    assert rbac.enforce(rbac.ROLE_VIEWER, rbac.PERM_JOBS_READ) is True
    assert rbac.enforce(rbac.ROLE_VIEWER, rbac.PERM_MEMBERS_MANAGE) is False
    assert rbac.enforce(rbac.ROLE_VIEWER, rbac.PERM_JOBS_CREATE) is False
    assert rbac.effective_permissions(rbac.ROLE_VIEWER) == frozenset(
        {rbac.PERM_JOBS_READ}
    )


def test_editor_can_create_jobs_and_inherits_read():
    assert rbac.enforce(rbac.ROLE_EDITOR, rbac.PERM_JOBS_CREATE) is True
    assert rbac.enforce(rbac.ROLE_EDITOR, rbac.PERM_JOBS_READ) is True
    assert rbac.enforce(rbac.ROLE_EDITOR, rbac.PERM_MEMBERS_MANAGE) is False
    assert rbac.effective_permissions(rbac.ROLE_EDITOR) == frozenset(
        {rbac.PERM_JOBS_CREATE, rbac.PERM_JOBS_READ}
    )


def test_admin_manages_members_but_not_billing():
    assert rbac.enforce(rbac.ROLE_ADMIN, rbac.PERM_MEMBERS_MANAGE) is True
    assert rbac.enforce(rbac.ROLE_ADMIN, rbac.PERM_WORKSPACE_SETTINGS) is True
    assert rbac.enforce(rbac.ROLE_ADMIN, rbac.PERM_AUDIT_READ) is True
    # admin inherits editor/viewer job permissions
    assert rbac.enforce(rbac.ROLE_ADMIN, rbac.PERM_JOBS_CREATE) is True
    assert rbac.enforce(rbac.ROLE_ADMIN, rbac.PERM_JOBS_READ) is True
    # ...but NOT billing or platform admin access
    assert rbac.enforce(rbac.ROLE_ADMIN, rbac.PERM_BILLING_MANAGE) is False
    assert rbac.enforce(rbac.ROLE_ADMIN, rbac.PERM_ADMIN_ACCESS) is False


def test_billing_role_manages_billing_and_reads_only():
    assert rbac.enforce(rbac.ROLE_BILLING, rbac.PERM_BILLING_MANAGE) is True
    assert rbac.enforce(rbac.ROLE_BILLING, rbac.PERM_JOBS_READ) is True
    assert rbac.enforce(rbac.ROLE_BILLING, rbac.PERM_JOBS_CREATE) is False
    assert rbac.enforce(rbac.ROLE_BILLING, rbac.PERM_MEMBERS_MANAGE) is False
    assert rbac.effective_permissions(rbac.ROLE_BILLING) == frozenset(
        {rbac.PERM_BILLING_MANAGE, rbac.PERM_JOBS_READ}
    )


def test_unknown_or_legacy_role_is_denied_everything():
    # The additive-layer 'member' role carries no Casbin policy -> fail closed.
    for role in ("member", "superuser", "", None):
        assert rbac.effective_permissions(role) == frozenset()
        for perm in rbac.PERMISSIONS:
            assert rbac.enforce(role, perm) is False


# --------------------------------------------------------------------------- #
# require_permission — tenant isolation + role gate
# --------------------------------------------------------------------------- #
def test_require_permission_denies_non_member(session_factory):
    """Tenant isolation: a non-member is denied regardless of permission."""
    with _session(session_factory) as s:
        owner = _make_user(s, "owner@example.com")
        outsider = _make_user(s, "outsider@example.com")
        ws = _make_workspace(s, owner)
        _add_member(s, ws, owner, rbac.ROLE_OWNER)

        with pytest.raises(PermissionError):
            rbac.require_permission(s, outsider, ws, rbac.PERM_JOBS_READ)


def test_require_permission_denies_underprivileged_member(session_factory):
    with _session(session_factory) as s:
        owner = _make_user(s, "owner@example.com")
        viewer = _make_user(s, "viewer@example.com")
        ws = _make_workspace(s, owner)
        _add_member(s, ws, owner, rbac.ROLE_OWNER)
        _add_member(s, ws, viewer, rbac.ROLE_VIEWER)

        # viewer may read...
        assert (
            rbac.require_permission(s, viewer, ws, rbac.PERM_JOBS_READ)
            == rbac.ROLE_VIEWER
        )
        # ...but may not manage members.
        with pytest.raises(PermissionError):
            rbac.require_permission(s, viewer, ws, rbac.PERM_MEMBERS_MANAGE)


def test_require_permission_allows_privileged_member_and_returns_role(
    session_factory,
):
    with _session(session_factory) as s:
        owner = _make_user(s, "owner@example.com")
        admin = _make_user(s, "admin@example.com")
        editor = _make_user(s, "editor@example.com")
        ws = _make_workspace(s, owner)
        _add_member(s, ws, owner, rbac.ROLE_OWNER)
        _add_member(s, ws, admin, rbac.ROLE_ADMIN)
        _add_member(s, ws, editor, rbac.ROLE_EDITOR)

        assert (
            rbac.require_permission(s, admin, ws, rbac.PERM_MEMBERS_MANAGE)
            == rbac.ROLE_ADMIN
        )
        assert (
            rbac.require_permission(s, editor, ws, rbac.PERM_JOBS_CREATE)
            == rbac.ROLE_EDITOR
        )
        assert (
            rbac.require_permission(s, owner, ws, rbac.PERM_BILLING_MANAGE)
            == rbac.ROLE_OWNER
        )


def test_membership_is_tenant_scoped(session_factory):
    """A role in workspace A grants nothing in workspace B."""
    with _session(session_factory) as s:
        owner_a = _make_user(s, "owner-a@example.com")
        owner_b = _make_user(s, "owner-b@example.com")
        ws_a = _make_workspace(s, owner_a, "A")
        ws_b = _make_workspace(s, owner_b, "B")
        _add_member(s, ws_a, owner_a, rbac.ROLE_OWNER)
        _add_member(s, ws_b, owner_b, rbac.ROLE_OWNER)

        assert rbac.is_member(s, owner_a, ws_a) is True
        assert rbac.is_member(s, owner_a, ws_b) is False
        assert rbac.get_role(s, owner_a, ws_a) == rbac.ROLE_OWNER
        assert rbac.get_role(s, owner_a, ws_b) is None
        with pytest.raises(PermissionError):
            rbac.require_permission(s, owner_a, ws_b, rbac.PERM_JOBS_READ)
