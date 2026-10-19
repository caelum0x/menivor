"""Unit tests for the SCIM 2.0 provisioning service (Identity & SSO, Epic 2).

Runs against an in-memory SQLite DB built from the live ORM metadata. Covered
behaviour:

* TENANT ISOLATION — a SCIM token minted for workspace *B* can NEITHER
  authenticate against, NOR read/provision into, workspace *A*;
* :func:`scim.provision_user` creates an :class:`ExternalIdentity` (+ user +
  membership) scoped to the token's workspace;
* :func:`scim.deactivate_user` SOFT-disables the identity (``provisioned=False``,
  row retained) and removes membership;
* the raw bearer token is NEVER stored — only its SHA-256 digest is persisted.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.base import Base
from app.models.db.models import User, Workspace, WorkspaceMember
from app.models.db.repositories import (
    ExternalIdentityRepository,
    ScimTokenRepository,
    WorkspaceRepository,
)
from app.services import scim


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


def _make_workspace(session, name: str) -> str:
    owner = User(email=f"owner-{name}@corp.test")
    session.add(owner)
    session.flush()
    ws = Workspace(owner_id=owner.id, name=name)
    session.add(ws)
    session.flush()
    session.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role="owner"))
    session.flush()
    return ws.id


def _payload(external_id: str, email: str) -> dict:
    return {
        "schemas": [scim.SCIM_USER_SCHEMA],
        "externalId": external_id,
        "userName": email,
        "emails": [{"value": email, "primary": True}],
        "active": True,
    }


# --------------------------------------------------------------------------- #
# Tenant isolation — a token for B cannot touch A
# --------------------------------------------------------------------------- #
def test_scim_token_is_tenant_scoped_auth(session_factory):
    with _session(session_factory) as s:
        ws_a = _make_workspace(s, "A")
        ws_b = _make_workspace(s, "B")
        _row, raw_b = scim.create_token(s, ws_b)

        # The B token authenticates against B...
        assert scim.auth_token(s, ws_b, f"Bearer {raw_b}").workspace_id == ws_b
        # ...but is REJECTED against A (cross-tenant).
        with pytest.raises(scim.ScimAuthError):
            scim.auth_token(s, ws_a, f"Bearer {raw_b}")


def test_scim_token_for_b_cannot_read_a_resources(session_factory):
    with _session(session_factory) as s:
        ws_a = _make_workspace(s, "A")
        ws_b = _make_workspace(s, "B")

        # Provision a user into A.
        created_a = scim.provision_user(s, ws_a, _payload("idp|a-user", "a@corp.test"))

        # A B-token holder addressing B never sees A's resources.
        listing_b = scim.list_users(s, ws_b)
        assert listing_b["totalResults"] == 0

        # And resolving A's resource id under B is a 404 (tenant-scoped).
        with pytest.raises(scim.ScimNotFoundError):
            scim.get_user(s, ws_b, created_a["id"])

        # Under A it resolves fine.
        assert scim.get_user(s, ws_a, created_a["id"])["externalId"] == "idp|a-user"


def test_unknown_and_revoked_tokens_are_rejected(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s, "W")
        row, raw = scim.create_token(s, ws)

        with pytest.raises(scim.ScimAuthError):
            scim.auth_token(s, ws, "Bearer not-a-real-token")

        assert scim.revoke_token(s, ws, row.id) is True
        with pytest.raises(scim.ScimAuthError):
            scim.auth_token(s, ws, f"Bearer {raw}")


# --------------------------------------------------------------------------- #
# provision / deactivate
# --------------------------------------------------------------------------- #
def test_provision_creates_external_identity_and_membership(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s, "Prov")
        resource = scim.provision_user(
            s, ws, _payload("idp|erin", "erin@corp.test")
        )

        assert resource["active"] is True
        assert resource["externalId"] == "idp|erin"

        identity = ExternalIdentityRepository(s).get_by_subject(ws, "idp|erin")
        assert identity is not None
        assert identity.provisioned is True
        assert identity.email == "erin@corp.test"
        # Membership was ensured in THIS workspace.
        assert WorkspaceRepository(s).get_membership(ws, identity.user_id) is not None


def test_provision_is_idempotent(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s, "Idem")
        first = scim.provision_user(s, ws, _payload("idp|frank", "frank@corp.test"))
        second = scim.provision_user(s, ws, _payload("idp|frank", "frank@corp.test"))
        assert first["id"] == second["id"]
        rows = ExternalIdentityRepository(s).list_for_workspace(ws)
        assert len([r for r in rows if r.idp_subject == "idp|frank"]) == 1


def test_deactivate_soft_disables_identity(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s, "Deact")
        created = scim.provision_user(s, ws, _payload("idp|gina", "gina@corp.test"))
        identity_id = created["id"]

        result = scim.deactivate_user(s, ws, identity_id)
        assert result["active"] is False

        # The row is RETAINED (soft-disable), just flipped to not-provisioned.
        identity = ExternalIdentityRepository(s).get_owned(identity_id, ws)
        assert identity is not None
        assert identity.provisioned is False
        # Membership was removed on deprovision.
        assert WorkspaceRepository(s).get_membership(ws, identity.user_id) is None


def test_deactivate_across_tenant_is_not_found(session_factory):
    with _session(session_factory) as s:
        ws_a = _make_workspace(s, "A")
        ws_b = _make_workspace(s, "B")
        created_a = scim.provision_user(s, ws_a, _payload("idp|h", "h@corp.test"))

        # A B-scoped deactivate of an A identity must not touch it.
        with pytest.raises(scim.ScimNotFoundError):
            scim.deactivate_user(s, ws_b, created_a["id"])
        assert ExternalIdentityRepository(s).get_owned(
            created_a["id"], ws_a
        ).provisioned is True


def test_update_user_toggles_active(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s, "Upd")
        created = scim.provision_user(s, ws, _payload("idp|iris", "iris@corp.test"))
        patched = scim.update_user(
            s,
            ws,
            created["id"],
            {
                "schemas": [scim.SCIM_PATCH_SCHEMA],
                "Operations": [{"op": "replace", "path": "active", "value": False}],
            },
        )
        assert patched["active"] is False


# --------------------------------------------------------------------------- #
# Token hashing — raw token never stored
# --------------------------------------------------------------------------- #
def test_token_is_hashed_not_stored_plaintext(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s, "Hash")
        row, raw = scim.create_token(s, ws)

        assert row.token_hash != raw
        assert row.token_hash == scim.hash_token(raw)
        # The stored digest is a 64-char sha256 hex, and the prefix is non-secret.
        assert len(row.token_hash) == 64
        assert row.prefix and raw.startswith(row.prefix)

        # No persisted token row anywhere carries the raw secret.
        for stored in ScimTokenRepository(s).list_for_workspace(ws):
            assert stored.token_hash != raw
