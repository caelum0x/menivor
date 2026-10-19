"""Unit tests for the workspace security-policy service (Identity & SSO, Epic 2).

Runs against an in-memory SQLite DB built from the live ORM metadata. Covered
behaviour:

* :func:`security_policy.set_policy` is ``workspace.settings`` RBAC-gated — a
  non-member and an under-privileged (viewer) member are denied; an owner/admin
  may set it;
* :func:`security_policy.enforce_login_policy` enforces, in order, require-SSO,
  email-domain allowlist, MFA-required, and IP-allowlist — raising
  :class:`PolicyViolation` (with a stable ``code``) on the first breach and
  passing an allowed attempt.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.base import Base
from app.models.db.models import User, Workspace, WorkspaceMember
from app.models.db.repositories import SecurityPolicyRepository
from app.services import rbac, security_policy
from app.services.security_policy import LoginContext, PolicyViolation


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


def _make_user(session, email: str) -> User:
    user = User(email=email)
    session.add(user)
    session.flush()
    return user


def _make_workspace(session, owner_id: str) -> str:
    ws = Workspace(owner_id=owner_id, name="Tenant")
    session.add(ws)
    session.flush()
    return ws.id


def _add_member(session, workspace_id: str, user_id: str, role: str) -> None:
    session.add(
        WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=role)
    )
    session.flush()


# --------------------------------------------------------------------------- #
# set_policy — RBAC (workspace.settings) gated
# --------------------------------------------------------------------------- #
def test_set_policy_denies_non_member(session_factory):
    with _session(session_factory) as s:
        owner = _make_user(s, "owner@acme.com")
        outsider = _make_user(s, "out@acme.com")
        ws = _make_workspace(s, owner.id)
        _add_member(s, ws, owner.id, rbac.ROLE_OWNER)

        with pytest.raises(PermissionError):
            security_policy.set_policy(s, ws, outsider.id, require_sso=True)


def test_set_policy_denies_underprivileged_viewer(session_factory):
    with _session(session_factory) as s:
        owner = _make_user(s, "owner@acme.com")
        viewer = _make_user(s, "viewer@acme.com")
        ws = _make_workspace(s, owner.id)
        _add_member(s, ws, owner.id, rbac.ROLE_OWNER)
        _add_member(s, ws, viewer.id, rbac.ROLE_VIEWER)

        with pytest.raises(PermissionError):
            security_policy.set_policy(s, ws, viewer.id, require_sso=True)


def test_set_policy_allows_admin_and_persists(session_factory):
    with _session(session_factory) as s:
        owner = _make_user(s, "owner@acme.com")
        admin = _make_user(s, "admin@acme.com")
        ws = _make_workspace(s, owner.id)
        _add_member(s, ws, owner.id, rbac.ROLE_OWNER)
        _add_member(s, ws, admin.id, rbac.ROLE_ADMIN)

        policy = security_policy.set_policy(
            s,
            ws,
            admin.id,
            require_sso=True,
            allowed_email_domains=["Acme.com", "  "],
            mfa_required=True,
            session_timeout_min=30,
            ip_allowlist=["1.2.3.4"],
        )
        assert policy.require_sso is True
        assert policy.mfa_required is True
        assert policy.session_timeout_min == 30
        # Domains are normalized (lower-cased, blanks dropped).
        assert policy.allowed_email_domains == ["acme.com"]
        # Re-read from the DB confirms persistence.
        stored = SecurityPolicyRepository(s).get(ws)
        assert stored.require_sso is True


# --------------------------------------------------------------------------- #
# enforce_login_policy
# --------------------------------------------------------------------------- #
def test_enforce_no_policy_is_a_pass(session_factory):
    with _session(session_factory) as s:
        user = _make_user(s, "a@acme.com")
        ws = _make_workspace(s, user.id)
        # No policy row -> nothing to enforce.
        security_policy.enforce_login_policy(
            s, user, ws, LoginContext(method="password")
        )


def test_enforce_require_sso(session_factory):
    with _session(session_factory) as s:
        user = _make_user(s, "a@acme.com")
        ws = _make_workspace(s, user.id)
        SecurityPolicyRepository(s).upsert(ws, require_sso=True)

        with pytest.raises(PolicyViolation) as exc:
            security_policy.enforce_login_policy(
                s, user, ws, LoginContext(method="password")
            )
        assert exc.value.code == "require_sso"

        # An SSO login satisfies it.
        security_policy.enforce_login_policy(
            s, user, ws, LoginContext(method="sso")
        )


def test_enforce_email_domain(session_factory):
    with _session(session_factory) as s:
        user = _make_user(s, "bob@evil.com")
        ws = _make_workspace(s, user.id)
        SecurityPolicyRepository(s).upsert(ws, allowed_email_domains=["acme.com"])

        with pytest.raises(PolicyViolation) as exc:
            security_policy.enforce_login_policy(
                s, user, ws, LoginContext(method="sso")
            )
        assert exc.value.code == "email_domain"

        # A ctx email in the allowed domain passes (overrides the user's email).
        security_policy.enforce_login_policy(
            s, user, ws, LoginContext(method="sso", email="carol@acme.com")
        )


def test_enforce_mfa_required(session_factory):
    with _session(session_factory) as s:
        user = _make_user(s, "a@acme.com")
        ws = _make_workspace(s, user.id)
        SecurityPolicyRepository(s).upsert(ws, mfa_required=True)

        with pytest.raises(PolicyViolation) as exc:
            security_policy.enforce_login_policy(
                s, user, ws, LoginContext(method="sso", mfa=False)
            )
        assert exc.value.code == "mfa_required"

        security_policy.enforce_login_policy(
            s, user, ws, LoginContext(method="sso", mfa=True)
        )


def test_enforce_ip_allowlist(session_factory):
    with _session(session_factory) as s:
        user = _make_user(s, "a@acme.com")
        ws = _make_workspace(s, user.id)
        SecurityPolicyRepository(s).upsert(ws, ip_allowlist=["1.2.3.4"])

        with pytest.raises(PolicyViolation) as exc:
            security_policy.enforce_login_policy(
                s, user, ws, LoginContext(method="sso", ip="9.9.9.9")
            )
        assert exc.value.code == "ip_not_allowed"

        security_policy.enforce_login_policy(
            s, user, ws, LoginContext(method="sso", ip="1.2.3.4")
        )
