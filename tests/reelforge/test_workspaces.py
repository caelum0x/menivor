"""Unit tests for the Team Workspaces membership + role-enforcement layer.

Runs against an in-memory SQLite DB built from the live ORM metadata, so the
tests exercise the real :class:`WorkspaceRepository` INSERT / UPDATE / DELETE
paths and the real ``(workspace_id, user_id)`` UNIQUE membership constraint —
no fakes. Covered behaviour:

* an owner can create, invite, set roles and remove members;
* a plain member cannot invite / remove / change roles (``PermissionError``);
* inviting an email with no account is rejected (``ValueError``);
* the owner can never be demoted, removed, or leave;
* a non-owner can leave;
* a duplicate membership is rejected (unique guard);
* an admin cannot grant / elevate above their own role.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.base import Base
from app.models.db.models import User, WorkspaceMember
from app.services import workspaces


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def session_factory():
    """In-memory SQLite session factory sharing one connection (StaticPool)."""
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
    """Seed a user and return its id."""
    user = User(email=email, credits=0)
    session.add(user)
    session.flush()
    return user.id


def _seed(session) -> dict[str, str]:
    """Seed a handful of users; return {label: user_id}."""
    return {
        "owner": _make_user(session, "owner@example.com"),
        "admin": _make_user(session, "admin@example.com"),
        "member": _make_user(session, "member@example.com"),
        "outsider": _make_user(session, "outsider@example.com"),
    }


def _role(session, workspace_id: str, user_id: str) -> str | None:
    m = workspaces.WorkspaceRepository(session).get_membership(
        workspace_id, user_id
    )
    return m.role if m is not None else None


# --------------------------------------------------------------------------- #
# create_workspace
# --------------------------------------------------------------------------- #
def test_create_workspace_makes_creator_the_owner(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")

        assert ws.owner_id == users["owner"]
        assert ws.name == "Team A"
        assert _role(s, ws.id, users["owner"]) == workspaces.ROLE_OWNER
        # exactly one member so far
        assert len(workspaces.list_members(s, ws.id, users["owner"])) == 1


def test_create_workspace_rejects_blank_name(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        with pytest.raises(ValueError):
            workspaces.create_workspace(s, users["owner"], "   ")


def test_create_workspace_rejects_unknown_owner(session_factory):
    with _session(session_factory) as s:
        with pytest.raises(ValueError):
            workspaces.create_workspace(s, "nonexistent-id", "Team A")


# --------------------------------------------------------------------------- #
# invite_member — happy path + role rules
# --------------------------------------------------------------------------- #
def test_owner_can_invite_member(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")

        member = workspaces.invite_member(
            s, ws.id, users["owner"], "member@example.com"
        )

        assert member.user_id == users["member"]
        assert member.role == workspaces.ROLE_MEMBER
        assert _role(s, ws.id, users["member"]) == workspaces.ROLE_MEMBER


def test_owner_can_invite_admin_then_admin_can_invite_member(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")

        workspaces.invite_member(
            s, ws.id, users["owner"], "admin@example.com",
            role=workspaces.ROLE_ADMIN,
        )
        assert _role(s, ws.id, users["admin"]) == workspaces.ROLE_ADMIN

        # the admin can now invite a plain member
        workspaces.invite_member(
            s, ws.id, users["admin"], "member@example.com"
        )
        assert _role(s, ws.id, users["member"]) == workspaces.ROLE_MEMBER


def test_invite_is_case_insensitive_on_email(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")

        member = workspaces.invite_member(
            s, ws.id, users["owner"], "MEMBER@EXAMPLE.COM"
        )
        assert member.user_id == users["member"]


def test_invite_unknown_email_raises_value_error(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")

        with pytest.raises(ValueError, match="account"):
            workspaces.invite_member(
                s, ws.id, users["owner"], "ghost@example.com"
            )


def test_invite_duplicate_member_raises_value_error(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")
        workspaces.invite_member(s, ws.id, users["owner"], "member@example.com")

        with pytest.raises(ValueError, match="already a member"):
            workspaces.invite_member(
                s, ws.id, users["owner"], "member@example.com"
            )


def test_invite_invalid_role_raises_value_error(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")
        with pytest.raises(ValueError, match="invalid role"):
            workspaces.invite_member(
                s, ws.id, users["owner"], "member@example.com", role="superuser"
            )


def test_admin_cannot_invite_owner(session_factory):
    """An admin may not grant a role higher than their own (owner)."""
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")
        workspaces.invite_member(
            s, ws.id, users["owner"], "admin@example.com",
            role=workspaces.ROLE_ADMIN,
        )

        with pytest.raises(PermissionError):
            workspaces.invite_member(
                s, ws.id, users["admin"], "member@example.com",
                role=workspaces.ROLE_OWNER,
            )


def test_owner_cannot_invite_second_owner(session_factory):
    """The single-owner invariant: an owner may not grant the owner role."""
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")

        with pytest.raises(PermissionError):
            workspaces.invite_member(
                s, ws.id, users["owner"], "admin@example.com",
                role=workspaces.ROLE_OWNER,
            )
        # no second owner was created
        assert _role(s, ws.id, users["admin"]) is None


# --------------------------------------------------------------------------- #
# Members cannot mutate
# --------------------------------------------------------------------------- #
def test_member_cannot_invite(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")
        workspaces.invite_member(s, ws.id, users["owner"], "member@example.com")

        with pytest.raises(PermissionError):
            workspaces.invite_member(
                s, ws.id, users["member"], "outsider@example.com"
            )


def test_member_cannot_remove_others(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")
        workspaces.invite_member(s, ws.id, users["owner"], "member@example.com")
        workspaces.invite_member(
            s, ws.id, users["owner"], "admin@example.com",
            role=workspaces.ROLE_ADMIN,
        )

        with pytest.raises(PermissionError):
            workspaces.remove_member(
                s, ws.id, users["member"], users["admin"]
            )


def test_member_cannot_set_role(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")
        workspaces.invite_member(s, ws.id, users["owner"], "member@example.com")
        workspaces.invite_member(
            s, ws.id, users["owner"], "admin@example.com",
            role=workspaces.ROLE_ADMIN,
        )

        with pytest.raises(PermissionError):
            workspaces.set_role(
                s, ws.id, users["member"], users["admin"],
                workspaces.ROLE_MEMBER,
            )


def test_non_member_actor_is_rejected(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")
        with pytest.raises(PermissionError):
            workspaces.list_members(s, ws.id, users["outsider"])


# --------------------------------------------------------------------------- #
# set_role
# --------------------------------------------------------------------------- #
def test_owner_can_promote_and_demote_member(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")
        workspaces.invite_member(s, ws.id, users["owner"], "member@example.com")

        workspaces.set_role(
            s, ws.id, users["owner"], users["member"], workspaces.ROLE_ADMIN
        )
        assert _role(s, ws.id, users["member"]) == workspaces.ROLE_ADMIN

        workspaces.set_role(
            s, ws.id, users["owner"], users["member"], workspaces.ROLE_MEMBER
        )
        assert _role(s, ws.id, users["member"]) == workspaces.ROLE_MEMBER


def test_cannot_demote_owner(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")
        workspaces.invite_member(
            s, ws.id, users["owner"], "admin@example.com",
            role=workspaces.ROLE_ADMIN,
        )

        with pytest.raises(PermissionError):
            workspaces.set_role(
                s, ws.id, users["admin"], users["owner"],
                workspaces.ROLE_MEMBER,
            )
        # owner role unchanged
        assert _role(s, ws.id, users["owner"]) == workspaces.ROLE_OWNER


def test_admin_cannot_elevate_above_own_role(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")
        workspaces.invite_member(
            s, ws.id, users["owner"], "admin@example.com",
            role=workspaces.ROLE_ADMIN,
        )
        workspaces.invite_member(s, ws.id, users["owner"], "member@example.com")

        with pytest.raises(PermissionError):
            workspaces.set_role(
                s, ws.id, users["admin"], users["member"],
                workspaces.ROLE_OWNER,
            )


def test_owner_cannot_promote_member_to_second_owner(session_factory):
    """set_role must also honour the single-owner invariant."""
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")
        workspaces.invite_member(s, ws.id, users["owner"], "member@example.com")

        with pytest.raises(PermissionError):
            workspaces.set_role(
                s, ws.id, users["owner"], users["member"],
                workspaces.ROLE_OWNER,
            )
        # membership stays at its original role, no second owner minted
        assert _role(s, ws.id, users["member"]) == workspaces.ROLE_MEMBER


def test_set_role_on_non_member_raises_value_error(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")
        with pytest.raises(ValueError):
            workspaces.set_role(
                s, ws.id, users["owner"], users["outsider"],
                workspaces.ROLE_MEMBER,
            )


# --------------------------------------------------------------------------- #
# remove_member / leave
# --------------------------------------------------------------------------- #
def test_owner_can_remove_member(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")
        workspaces.invite_member(s, ws.id, users["owner"], "member@example.com")

        assert workspaces.remove_member(
            s, ws.id, users["owner"], users["member"]
        ) is True
        assert _role(s, ws.id, users["member"]) is None


def test_cannot_remove_owner(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")
        workspaces.invite_member(
            s, ws.id, users["owner"], "admin@example.com",
            role=workspaces.ROLE_ADMIN,
        )

        with pytest.raises(PermissionError):
            workspaces.remove_member(
                s, ws.id, users["admin"], users["owner"]
            )
        assert _role(s, ws.id, users["owner"]) == workspaces.ROLE_OWNER


def test_non_owner_can_leave(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")
        workspaces.invite_member(s, ws.id, users["owner"], "member@example.com")

        assert workspaces.leave_workspace(s, ws.id, users["member"]) is True
        assert _role(s, ws.id, users["member"]) is None


def test_member_can_remove_self_via_remove_member(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")
        workspaces.invite_member(s, ws.id, users["owner"], "member@example.com")

        # self-removal == leave, allowed for a plain member
        assert workspaces.remove_member(
            s, ws.id, users["member"], users["member"]
        ) is True
        assert _role(s, ws.id, users["member"]) is None


def test_owner_cannot_leave(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")

        with pytest.raises(PermissionError):
            workspaces.leave_workspace(s, ws.id, users["owner"])
        assert _role(s, ws.id, users["owner"]) == workspaces.ROLE_OWNER


# --------------------------------------------------------------------------- #
# listing
# --------------------------------------------------------------------------- #
def test_list_workspaces_returns_only_membered(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        ws_a = workspaces.create_workspace(s, users["owner"], "Team A")
        ws_b = workspaces.create_workspace(s, users["admin"], "Team B")
        workspaces.invite_member(s, ws_a.id, users["owner"], "member@example.com")

        owner_ws = {w.id for w in workspaces.list_workspaces(s, users["owner"])}
        member_ws = {w.id for w in workspaces.list_workspaces(s, users["member"])}
        outsider_ws = workspaces.list_workspaces(s, users["outsider"])

        assert owner_ws == {ws_a.id}
        assert member_ws == {ws_a.id}
        assert ws_b.id not in owner_ws
        assert outsider_ws == []


# --------------------------------------------------------------------------- #
# require_role
# --------------------------------------------------------------------------- #
def test_require_role_returns_membership_for_privileged_actor(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")

        membership = workspaces.require_role(
            s, ws.id, users["owner"], workspaces.ROLE_ADMIN
        )
        assert membership.role == workspaces.ROLE_OWNER


def test_require_role_rejects_unknown_min_role(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")
        with pytest.raises(ValueError):
            workspaces.require_role(s, ws.id, users["owner"], "god")


# --------------------------------------------------------------------------- #
# unique-membership DB guard (defense in depth beneath the service check)
# --------------------------------------------------------------------------- #
def test_unique_membership_constraint_enforced(session_factory):
    with _session(session_factory) as s:
        users = _seed(s)
        ws = workspaces.create_workspace(s, users["owner"], "Team A")
        # bypass the service-level duplicate check to prove the DB constraint
        s.add(
            WorkspaceMember(
                workspace_id=ws.id,
                user_id=users["owner"],  # already the owner member
                role=workspaces.ROLE_MEMBER,
            )
        )
        with pytest.raises(IntegrityError):
            s.flush()
        # The failed flush poisons the transaction; roll back so the enclosing
        # context manager can close the session cleanly.
        s.rollback()
