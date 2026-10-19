"""Unit tests for the platform-admin service (Enterprise Access & Governance).

Runs against an in-memory SQLite DB built from the live ORM metadata. Covered
behaviour:

* every function is HARD-GATED on ``User.is_staff`` — a non-staff caller is
  rejected with :class:`PermissionError` for listing AND for impersonation;
* a staff caller may list users / workspaces / jobs across every tenant;
* :func:`admin.mint_impersonation` writes an append-only audit row and returns a
  short-lived, time-boxed :class:`ImpersonationToken`;
* impersonating a non-existent target is rejected (:class:`ValueError`).
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.base import Base
from app.models.db.models import AuditLog, Job, User, Workspace
from app.services import admin


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


def _make_user(session, email: str, *, is_staff: bool = False) -> str:
    user = User(email=email, credits=0, is_staff=is_staff)
    session.add(user)
    session.flush()
    return user.id


def _make_workspace(session, owner_id: str, name: str) -> str:
    ws = Workspace(owner_id=owner_id, name=name)
    session.add(ws)
    session.flush()
    return ws.id


def _make_job(session, user_id: str) -> str:
    job = Job(user_id=user_id, kind="avatar_reel", params={})
    session.add(job)
    session.flush()
    return job.id


# --------------------------------------------------------------------------- #
# Staff gate — non-staff is rejected everywhere
# --------------------------------------------------------------------------- #
def test_non_staff_rejected_for_every_function(session_factory):
    with _session(session_factory) as s:
        civilian = _make_user(s, "user@example.com", is_staff=False)
        target = _make_user(s, "target@example.com")

        with pytest.raises(PermissionError):
            admin.list_users(s, civilian)
        with pytest.raises(PermissionError):
            admin.list_workspaces(s, civilian)
        with pytest.raises(PermissionError):
            admin.list_jobs(s, civilian)
        with pytest.raises(PermissionError):
            admin.mint_impersonation(s, civilian, target)


def test_unknown_actor_rejected(session_factory):
    with _session(session_factory) as s:
        with pytest.raises(PermissionError):
            admin.list_users(s, "no-such-user-id")


def test_workspace_owner_is_not_a_platform_admin(session_factory):
    """Platform-admin is separate from workspace roles: an owner is not staff."""
    with _session(session_factory) as s:
        owner = _make_user(s, "owner@example.com", is_staff=False)
        _make_workspace(s, owner, "Team")
        with pytest.raises(PermissionError):
            admin.list_users(s, owner)


# --------------------------------------------------------------------------- #
# Staff — cross-tenant listing
# --------------------------------------------------------------------------- #
def test_staff_can_list_users_workspaces_jobs(session_factory):
    with _session(session_factory) as s:
        staff = _make_user(s, "staff@example.com", is_staff=True)
        u1 = _make_user(s, "u1@example.com")
        u2 = _make_user(s, "u2@example.com")
        ws1 = _make_workspace(s, u1, "T1")
        ws2 = _make_workspace(s, u2, "T2")
        j1 = _make_job(s, u1)
        j2 = _make_job(s, u2)

        user_ids = {u.id for u in admin.list_users(s, staff, limit=100)}
        assert {staff, u1, u2} <= user_ids

        ws_ids = {w.id for w in admin.list_workspaces(s, staff, limit=100)}
        assert {ws1, ws2} <= ws_ids

        job_ids = {j.id for j in admin.list_jobs(s, staff, limit=100)}
        assert {j1, j2} <= job_ids


def test_list_pagination_clamps(session_factory):
    with _session(session_factory) as s:
        staff = _make_user(s, "staff@example.com", is_staff=True)
        for i in range(3):
            _make_user(s, f"u{i}@example.com")
        # non-positive limit is clamped to >=1 rather than producing bad SQL
        assert len(admin.list_users(s, staff, limit=0)) == 1


# --------------------------------------------------------------------------- #
# Impersonation — audited + time-boxed
# --------------------------------------------------------------------------- #
def test_mint_impersonation_writes_audit_and_is_time_boxed(session_factory):
    with _session(session_factory) as s:
        staff = _make_user(s, "staff@example.com", is_staff=True)
        target = _make_user(s, "target@example.com")

        before = datetime.now(timezone.utc)
        token = admin.mint_impersonation(s, staff, target)
        after = datetime.now(timezone.utc)

        # token identity + scope
        assert token.admin_user_id == staff
        assert token.target_user_id == target
        assert token.scope == f"impersonate:{target}"
        assert token.token  # a non-empty opaque secret

        # time-boxed: expires within the configured TTL window and is active now
        expected_max = after + timedelta(
            seconds=admin.IMPERSONATION_TTL_SECONDS
        )
        assert before < token.expires_at <= expected_max
        assert token.is_active(before) is True
        assert (
            token.is_active(
                token.expires_at + timedelta(seconds=1)
            )
            is False
        )

        # exactly one append-only audit row recording the impersonation. It is a
        # platform-level action (no workspace_id), so it is queried directly
        # rather than via the tenant-scoped list_for_workspace.
        audit_rows = s.execute(select(AuditLog)).scalars().all()
        assert len(audit_rows) == 1
        entry = audit_rows[0]
        assert entry.action == "admin.impersonated"
        assert entry.actor_user_id == staff
        assert entry.target_type == "user"
        assert entry.target_id == target
        assert entry.workspace_id is None
        assert entry.meta.get("scope") == f"impersonate:{target}"


def test_mint_impersonation_rejects_unknown_target(session_factory):
    with _session(session_factory) as s:
        staff = _make_user(s, "staff@example.com", is_staff=True)
        with pytest.raises(ValueError):
            admin.mint_impersonation(s, staff, "ghost-user-id")


def test_non_staff_impersonation_writes_no_audit_row(session_factory):
    """A rejected (non-staff) impersonation must not leave an audit row."""
    with _session(session_factory) as s:
        civilian = _make_user(s, "user@example.com", is_staff=False)
        target = _make_user(s, "target@example.com")
        with pytest.raises(PermissionError):
            admin.mint_impersonation(s, civilian, target)
        assert s.execute(select(AuditLog)).scalars().all() == []
