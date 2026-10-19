"""Clerk web sign-in resolves the real primary email when the token has none."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import clerk
from app.core.auth import principal
from app.models.db.base import Base
from app.models.db.models import User


@pytest.fixture()
def session(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)()
    monkeypatch.setattr("app.core.launch.policy.require_signup_enabled", lambda *a, **k: None)
    monkeypatch.setattr(principal, "_rally_signed_up", lambda *a, **k: None)
    clerk._email_cache.clear()
    yield s
    s.close()


def _payload(status: str = "verified") -> dict:
    return {
        "primary_email_address_id": "idn_1",
        "email_addresses": [
            {"id": "idn_0", "email_address": "old@example.com", "verification": {"status": "verified"}},
            {"id": "idn_1", "email_address": "Real@Example.com", "verification": {"status": status}},
        ],
    }


def test_primary_verified_email_only():
    assert clerk._primary_verified_email(_payload()) == "real@example.com"
    assert clerk._primary_verified_email(_payload("unverified")) == ""
    assert clerk._primary_verified_email({}) == ""


def test_fetch_requires_secret_and_sends_agent(monkeypatch):
    calls = []

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return _payload()

    def fake_get(url, headers, timeout):
        calls.append((url, headers))
        return _Resp()

    import requests

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(clerk, "_clerk_config", lambda: {})
    clerk._email_cache.clear()
    assert clerk.fetch_primary_email("user_1") == ""
    assert calls == []
    monkeypatch.setattr(clerk, "_clerk_config", lambda: {"secret_key": "sk_x"})
    assert clerk.fetch_primary_email("user_1") == "real@example.com"
    assert calls[0][0].endswith("/v1/users/user_1")
    assert calls[0][1]["User-Agent"] == clerk.JWKS_USER_AGENT
    assert clerk.fetch_primary_email("user_1") == "real@example.com"
    assert len(calls) == 1  # cached
    assert clerk.fetch_primary_email("../x/y") == ""


def test_new_user_gets_real_email(session, monkeypatch):
    monkeypatch.setattr(clerk, "fetch_primary_email", lambda sub: "real@example.com")
    user = principal.get_or_create_clerk_user(session, {"sub": "user_1"}, "rid")
    assert user.email == "real@example.com"


def test_lookup_failure_keeps_synthetic(session, monkeypatch):
    monkeypatch.setattr(clerk, "fetch_primary_email", lambda sub: "")
    user = principal.get_or_create_clerk_user(session, {"sub": "user_2"}, "rid")
    assert user.email == "clerk_user_2@users.reelforge"


def test_legacy_synthetic_account_is_upgraded_not_duplicated(session, monkeypatch):
    session.add(User(id="legacy1", email="clerk_user_3@users.reelforge"))
    session.flush()
    monkeypatch.setattr(clerk, "fetch_primary_email", lambda sub: "real3@example.com")
    user = principal.get_or_create_clerk_user(session, {"sub": "user_3"}, "rid")
    assert user.id == "legacy1"
    assert user.email == "real3@example.com"
    assert session.query(User).count() == 1


def test_email_claim_skips_lookup(session, monkeypatch):
    def boom(sub):
        raise AssertionError("lookup should not run")

    monkeypatch.setattr(clerk, "fetch_primary_email", boom)
    user = principal.get_or_create_clerk_user(session, {"sub": "u4", "email": "Claim@Example.com"}, "rid")
    assert user.email == "claim@example.com"
