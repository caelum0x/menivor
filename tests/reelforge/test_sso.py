"""Unit tests for the Enterprise SSO service (Identity & SSO, Epic 2).

Runs against an in-memory SQLite DB built from the live ORM metadata. Covered
behaviour:

* :func:`sso.process_acs` maps a MOCK-VALIDATED assertion (injected through the
  validator seam — no xmlsec needed) to a ReelForge user + workspace membership,
  and is idempotent on the same subject;
* it REJECTS an email whose domain is not in the workspace's allowlist;
* it REJECTS a REPLAY of the same assertion id (processed-id cache);
* the SAML validator seam degrades to :class:`SsoUnavailableError` (which the API
  maps to 503) when python3-saml/xmlsec is absent — as it is in CI;
* :func:`sso.configure_connection` encrypts the IdP cert (never plaintext);
* :func:`sso.build_login_redirect` builds an SP-initiated redirect without xmlsec.
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
    SecurityPolicyRepository,
    SSOConnectionRepository,
    WorkspaceRepository,
)
from app.services import crypto_tokens, sso


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


def _make_workspace(session, name: str = "Acme") -> str:
    owner = User(email=f"owner-{name}@acme.com")
    session.add(owner)
    session.flush()
    ws = Workspace(owner_id=owner.id, name=name)
    session.add(ws)
    session.flush()
    session.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role="owner"))
    session.flush()
    return ws.id


def _enable_connection(session, workspace_id: str) -> None:
    SSOConnectionRepository(session).upsert(
        workspace_id=workspace_id,
        protocol="saml",
        idp_entity_id="https://idp.example.com/entity",
        idp_sso_url="https://idp.example.com/sso",
        sp_acs_url="https://app.reelforge.test/api/v1/sso/acs",
        enabled=True,
    )


def _validator(subject: str, email: str, assertion_id: str):
    """Return a mock validator seam that yields a pre-validated assertion."""

    def _validate(connection, saml_response, relay_state=""):
        return sso.ValidatedAssertion(
            subject=subject,
            email=email,
            assertion_id=assertion_id,
            attributes={"email": [email]},
        )

    return _validate


# --------------------------------------------------------------------------- #
# process_acs — maps a validated assertion to a user
# --------------------------------------------------------------------------- #
def test_process_acs_maps_validated_assertion_to_user(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s)
        _enable_connection(s, ws)

        grant = sso.process_acs(
            s,
            ws,
            "<saml-response>",
            validator=_validator("idp|alice", "alice@acme.com", "aid-1"),
            replay_cache=sso.InMemoryReplayCache(),
        )

        assert grant.is_new_user is True
        assert grant.workspace_id == ws
        assert grant.email == "alice@acme.com"
        assert grant.user_id

        # An ExternalIdentity was created (tenant-scoped), and membership exists.
        identity = ExternalIdentityRepository(s).get_by_subject(ws, "idp|alice")
        assert identity is not None
        assert identity.provisioned is True
        assert identity.user_id == grant.user_id
        assert WorkspaceRepository(s).get_membership(ws, grant.user_id) is not None


def test_process_acs_is_idempotent_on_same_subject(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s)
        _enable_connection(s, ws)

        first = sso.process_acs(
            s, ws, "<r1>",
            validator=_validator("idp|bob", "bob@acme.com", "aid-a"),
            replay_cache=sso.InMemoryReplayCache(),
        )
        # A different assertion id (not a replay), same subject -> same user.
        second = sso.process_acs(
            s, ws, "<r2>",
            validator=_validator("idp|bob", "bob@acme.com", "aid-b"),
            replay_cache=sso.InMemoryReplayCache(),
        )

        assert first.user_id == second.user_id
        assert first.is_new_user is True
        assert second.is_new_user is False


# --------------------------------------------------------------------------- #
# Email-domain allowlist enforcement
# --------------------------------------------------------------------------- #
def test_process_acs_rejects_disallowed_email_domain(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s)
        _enable_connection(s, ws)
        SecurityPolicyRepository(s).upsert(ws, allowed_email_domains=["acme.com"])

        with pytest.raises(sso.SsoDomainError):
            sso.process_acs(
                s, ws, "<r>",
                validator=_validator("idp|mallory", "mallory@evil.com", "aid-x"),
                replay_cache=sso.InMemoryReplayCache(),
            )


def test_process_acs_allows_listed_email_domain(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s)
        _enable_connection(s, ws)
        SecurityPolicyRepository(s).upsert(ws, allowed_email_domains=["acme.com"])

        grant = sso.process_acs(
            s, ws, "<r>",
            validator=_validator("idp|carol", "carol@acme.com", "aid-y"),
            replay_cache=sso.InMemoryReplayCache(),
        )
        assert grant.email == "carol@acme.com"


def test_process_acs_rejects_missing_email(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s)
        _enable_connection(s, ws)
        with pytest.raises(sso.SsoDomainError):
            sso.process_acs(
                s, ws, "<r>",
                validator=_validator("idp|noemail", "", "aid-z"),
                replay_cache=sso.InMemoryReplayCache(),
            )


# --------------------------------------------------------------------------- #
# Replay protection
# --------------------------------------------------------------------------- #
def test_process_acs_rejects_replayed_assertion_id(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s)
        _enable_connection(s, ws)
        cache = sso.InMemoryReplayCache()

        sso.process_acs(
            s, ws, "<r>",
            validator=_validator("idp|dave", "dave@acme.com", "aid-dup"),
            replay_cache=cache,
        )
        # Same assertion id presented again -> replay rejected.
        with pytest.raises(sso.SsoReplayError):
            sso.process_acs(
                s, ws, "<r>",
                validator=_validator("idp|dave", "dave@acme.com", "aid-dup"),
                replay_cache=cache,
            )


# --------------------------------------------------------------------------- #
# Cross-tenant account takeover — never adopt a pre-existing FOREIGN account
# --------------------------------------------------------------------------- #
def test_process_acs_refuses_linking_foreign_existing_account(session_factory):
    """A validly-signed assertion for an EXISTING user who is a stranger to the
    workspace must NOT mint a session for that user (account takeover)."""
    with _session(session_factory) as s:
        ws = _make_workspace(s)
        _enable_connection(s, ws)
        # A pre-existing platform user in NO way related to this workspace.
        victim = User(email="victim@bigcorp.com", display_name="victim")
        s.add(victim)
        s.flush()
        victim_id = victim.id

        with pytest.raises(sso.SsoDomainError):
            sso.process_acs(
                s, ws, "<r>",
                validator=_validator("attacker|sub", "victim@bigcorp.com", "aid-tk"),
                replay_cache=sso.InMemoryReplayCache(),
            )

        # No identity was linked and the victim was NOT joined to the workspace.
        assert ExternalIdentityRepository(s).get_by_subject(ws, "attacker|sub") is None
        assert WorkspaceRepository(s).get_membership(ws, victim_id) is None


def test_process_acs_links_existing_workspace_member(session_factory):
    """An EXISTING user who is ALREADY a member of the workspace may legitimately
    attach their IdP identity (they consented / were invited in)."""
    with _session(session_factory) as s:
        ws = _make_workspace(s)
        _enable_connection(s, ws)
        owner_id = WorkspaceRepository(s).get(ws).owner_id
        owner_email = s.get(User, owner_id).email

        grant = sso.process_acs(
            s, ws, "<r>",
            validator=_validator("idp|owner-sub", owner_email, "aid-mem"),
            replay_cache=sso.InMemoryReplayCache(),
        )
        assert grant.user_id == owner_id
        assert grant.is_new_user is False


# --------------------------------------------------------------------------- #
# Replay: a missing assertion id is a hard validation failure (not a skip)
# --------------------------------------------------------------------------- #
def test_process_acs_rejects_assertion_without_id(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s)
        _enable_connection(s, ws)
        with pytest.raises(sso.SsoValidationError):
            sso.process_acs(
                s, ws, "<r>",
                validator=_validator("idp|noid", "noid@acme.com", ""),
                replay_cache=sso.InMemoryReplayCache(),
            )


# --------------------------------------------------------------------------- #
# Config gates (disabled / missing connection)
# --------------------------------------------------------------------------- #
def test_process_acs_requires_enabled_connection(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s)
        # No connection at all.
        with pytest.raises(sso.SsoConfigError):
            sso.process_acs(
                s, ws, "<r>",
                validator=_validator("idp|x", "x@acme.com", "aid"),
                replay_cache=sso.InMemoryReplayCache(),
            )
        # Present but disabled.
        SSOConnectionRepository(s).upsert(
            workspace_id=ws, protocol="saml", enabled=False
        )
        with pytest.raises(sso.SsoConfigError):
            sso.process_acs(
                s, ws, "<r>",
                validator=_validator("idp|x", "x@acme.com", "aid"),
                replay_cache=sso.InMemoryReplayCache(),
            )


# --------------------------------------------------------------------------- #
# SAML unavailable -> 503 seam (python3-saml/xmlsec absent in CI)
# --------------------------------------------------------------------------- #
def test_saml_toolkit_absent_degrades_to_unavailable(session_factory):
    # In CI the native toolkit is not installed.
    assert sso.saml_available() is False
    with _session(session_factory) as s:
        ws = _make_workspace(s)
        _enable_connection(s, ws)
        connection = SSOConnectionRepository(s).get_for_workspace(ws)
        # The validator seam raises SsoUnavailableError (API -> 503)...
        with pytest.raises(sso.SsoUnavailableError):
            sso._validate_saml_response(connection, "<r>", "")
        # ...and process_acs with the DEFAULT validator propagates it.
        with pytest.raises(sso.SsoUnavailableError):
            sso.process_acs(s, ws, "<r>", replay_cache=sso.InMemoryReplayCache())


# --------------------------------------------------------------------------- #
# Connection configuration — cert is encrypted, never plaintext
# --------------------------------------------------------------------------- #
def test_configure_connection_encrypts_certificate(session_factory):
    plaintext_cert = "-----BEGIN CERTIFICATE-----\nMIIB...\n-----END CERTIFICATE-----"
    with _session(session_factory) as s:
        ws = _make_workspace(s)
        owner = WorkspaceRepository(s).get(ws).owner_id

        connection = sso.configure_connection(
            s,
            ws,
            protocol="saml",
            idp_entity_id="https://idp/entity",
            idp_sso_url="https://idp/sso",
            idp_x509_cert=plaintext_cert,
            sp_acs_url="https://app/acs",
            enabled=True,
            actor_user_id=owner,
        )

        assert connection.idp_x509_cert_enc
        assert connection.idp_x509_cert_enc != plaintext_cert
        assert crypto_tokens.decrypt(connection.idp_x509_cert_enc) == plaintext_cert


def test_build_login_redirect_without_xmlsec(session_factory):
    with _session(session_factory) as s:
        ws = _make_workspace(s)
        _enable_connection(s, ws)
        connection = SSOConnectionRepository(s).get_for_workspace(ws)

        url = sso.build_login_redirect(connection, relay_state="return-here")
        assert url.startswith("https://idp.example.com/sso?")
        assert "SAMLRequest=" in url
        assert "RelayState=return-here" in url
