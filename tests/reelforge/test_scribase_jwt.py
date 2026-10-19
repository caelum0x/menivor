"""MN9: mobile sign-in on Scribase Auth.

A Scribase project runs upstream GoTrue (``supabase/gotrue:v2.196.0``, pinned in
scribase ``versions.lock.toml``) with the env Scribase's runtime writes
(``crates/supabase-runtime/src/docker_env.rs``): one HS256 secret per
environment, issuer ``<public url>/auth/v1``, audience ``authenticated``.

``REAL_SCRIBASE_TOKENS`` below were minted on 2026-09-28 by that exact GoTrue
image run with that env (throwaway container, test-only secret, a ten-year
``GOTRUE_JWT_EXP`` so the fixture stays valid). They prove wire compatibility
with ``core/supabase_auth.verify_supabase_jwt`` without a network.

Covered:
* a Scribase-issued token verifies; tokens from another issuer, another secret,
  a changed payload, the wrong audience or past expiry do not;
* the ES256 path works with a JWKS shaped like Scribase's own auth crate serves
  (``crates/auth/src/token/keys.rs``: public JWK plus ``kid``, ``use``, ``alg``);
* existing users re-link by verified email: no duplicate account and no second
  signup grant (MN3 rule), on the bearer path and on ``POST /auth/device``;
* an unverified email never links to someone else's account.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

# app.core.supabase_auth needs PyJWT at runtime. requirements.txt does not list it
# yet (MN9 hand-off: add "PyJWT[crypto]>=2.8,<3"); without it every mobile token is
# refused in the built image, so this module skips rather than pretending.
jwt = pytest.importorskip("jwt", reason="PyJWT is not installed; add PyJWT[crypto] to requirements.txt")
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.controllers.v1.device_auth as device_mod
from app.core import supabase_auth
from app.core.auth import principal
from app.models.db.base import Base
from app.models.db.models import CreditLedger, User
from app.models.db.repositories import CreditRepository
from app.models.exception import HttpException
from app.services import ratelimit
from app.services.billing import service
from app.services.billing.plans import SIGNUP_GRANT
from app.utils import utils

# The throwaway GoTrue's settings (test only; never a real project).
SCRIBASE_URL = "https://menivor-test.scribase.example"
SCRIBASE_ISSUER = f"{SCRIBASE_URL}/auth/v1"
SCRIBASE_TEST_SECRET = "scribase-test-secret-0123456789abcdef0123456789"
OLD_SUPABASE_URL = "https://psqkkdjzgptfcqpxuxki.supabase.co"

REAL_SCRIBASE_TOKENS = {
    # alice@example.com, sub bd78241e-3bd7-42b2-98ef-9404796266dd
    "alice": (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJpc3MiOiJodHRwczovL21lbml2b3ItdGVzdC5zY3JpYmFzZS5leGFtcGxlL2F1dGgvdjEiLCJzdWIiOiJiZDc4MjQxZS0zYmQ3"
        "LTQyYjItOThlZi05NDA0Nzk2MjY2ZGQiLCJhdWQiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjoyMTA1OTg1OTAwLCJpYXQiOjE3OTA2"
        "MjU5MDAsImVtYWlsIjoiYWxpY2VAZXhhbXBsZS5jb20iLCJwaG9uZSI6IiIsImFwcF9tZXRhZGF0YSI6eyJwcm92aWRlciI6ImVt"
        "YWlsIiwicHJvdmlkZXJzIjpbImVtYWlsIl19LCJ1c2VyX21ldGFkYXRhIjp7ImVtYWlsIjoiYWxpY2VAZXhhbXBsZS5jb20iLCJl"
        "bWFpbF92ZXJpZmllZCI6dHJ1ZSwicGhvbmVfdmVyaWZpZWQiOmZhbHNlLCJzdWIiOiJiZDc4MjQxZS0zYmQ3LTQyYjItOThlZi05"
        "NDA0Nzk2MjY2ZGQifSwicm9sZSI6ImF1dGhlbnRpY2F0ZWQiLCJhYWwiOiJhYWwxIiwiYW1yIjpbeyJtZXRob2QiOiJwYXNzd29y"
        "ZCIsInRpbWVzdGFtcCI6MTc5MDYyNTkwMH1dLCJzZXNzaW9uX2lkIjoiZmM1YWNhNGEtNzRlYi00M2YwLWJkZjctNDdkMGE3MjJl"
        "MTY1IiwiaXNfYW5vbnltb3VzIjpmYWxzZX0."
        "qO14dZDxIsq6xQvQ6gPDN-4YfalrfbmV62JSziv1A7Q"
    ),
    # bob@example.com, sub bb7a2aa7-2809-4a2c-9fa0-cf9e114faaa1
    "bob": (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJpc3MiOiJodHRwczovL21lbml2b3ItdGVzdC5zY3JpYmFzZS5leGFtcGxlL2F1dGgvdjEiLCJzdWIiOiJiYjdhMmFhNy0yODA5"
        "LTRhMmMtOWZhMC1jZjllMTE0ZmFhYTEiLCJhdWQiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjoyMTA1OTg1OTQwLCJpYXQiOjE3OTA2"
        "MjU5NDAsImVtYWlsIjoiYm9iQGV4YW1wbGUuY29tIiwicGhvbmUiOiIiLCJhcHBfbWV0YWRhdGEiOnsicHJvdmlkZXIiOiJlbWFp"
        "bCIsInByb3ZpZGVycyI6WyJlbWFpbCJdfSwidXNlcl9tZXRhZGF0YSI6eyJlbWFpbCI6ImJvYkBleGFtcGxlLmNvbSIsImVtYWls"
        "X3ZlcmlmaWVkIjp0cnVlLCJwaG9uZV92ZXJpZmllZCI6ZmFsc2UsInN1YiI6ImJiN2EyYWE3LTI4MDktNGEyYy05ZmEwLWNmOWUx"
        "MTRmYWFhMSJ9LCJyb2xlIjoiYXV0aGVudGljYXRlZCIsImFhbCI6ImFhbDEiLCJhbXIiOlt7Im1ldGhvZCI6InBhc3N3b3JkIiwi"
        "dGltZXN0YW1wIjoxNzkwNjI1OTQwfV0sInNlc3Npb25faWQiOiJmYTRkMjkxZC1hMzFmLTRiNGItYjQ1Mi1jOWZhMzJmMmYyY2Ui"
        "LCJpc19hbm9ueW1vdXMiOmZhbHNlfQ."
        "KBEBr6zyiM97W9bqsaImkXkcMTbAy5BVkpq1PEZw8Y0"
    ),
}
DEVICE_SECRET = "d" * 40


def _scribase_claims(sub: str, email: str, *, provider: str = "apple", verified: bool = True,
                     iss: str = SCRIBASE_ISSUER, exp_in: int = 3600) -> dict:
    """The GoTrue/Scribase access-token claim set (crates/auth/src/token/claims.rs)."""
    now = int(time.time())
    return {
        "iss": iss,
        "sub": sub,
        "aud": "authenticated",
        "exp": now + exp_in,
        "iat": now,
        "email": email,
        "phone": "",
        "app_metadata": {"provider": provider, "providers": [provider]},
        "user_metadata": {"email": email, "email_verified": verified, "sub": sub},
        "role": "authenticated",
        "aal": "aal1",
        "amr": [{"method": "oauth", "timestamp": now}],
        "session_id": "5a1d7c9e-0000-4000-8000-000000000001",
        "is_anonymous": False,
    }


def _hs256(claims: dict, secret: str = SCRIBASE_TEST_SECRET) -> str:
    return jwt.encode(claims, secret, algorithm="HS256")


@pytest.fixture()
def scribase_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", SCRIBASE_URL)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SCRIBASE_TEST_SECRET)
    monkeypatch.setattr(supabase_auth, "_jwks_client", None)
    monkeypatch.setattr(supabase_auth, "_jwks_client_url", "")


@pytest.fixture()
def maker():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    engine.dispose()


def _users(maker) -> int:
    with maker() as s:
        return int(s.execute(select(func.count()).select_from(User)).scalar())


def _signup_grants(maker, user_id: str) -> int:
    with maker() as s:
        return int(
            s.execute(
                select(func.count()).select_from(CreditLedger).where(
                    CreditLedger.user_id == user_id, CreditLedger.reason.like("%signup%")
                )
            ).scalar()
        )


def _existing_user(maker, email: str, *, granted: bool = True) -> str:
    with maker() as s:
        user = User(email=email, display_name="Existing", credits=0)
        s.add(user)
        s.flush()
        if granted:
            CreditRepository(s).grant(user.id, SIGNUP_GRANT, "web_signup")
        s.commit()
        return user.id


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #
def test_real_scribase_token_passes_verify_supabase_jwt(scribase_env):
    claims = supabase_auth.verify_supabase_jwt(REAL_SCRIBASE_TOKENS["alice"])
    assert claims["sub"] == "bd78241e-3bd7-42b2-98ef-9404796266dd"
    assert claims["iss"] == SCRIBASE_ISSUER
    assert supabase_auth.verified_email(claims) == "alice@example.com"


def test_real_scribase_token_is_routed_to_the_supabase_bridge(scribase_env):
    assert supabase_auth.looks_like_supabase_token(REAL_SCRIBASE_TOKENS["alice"])
    assert supabase_auth.is_configured()


def test_token_from_the_old_supabase_project_is_rejected_after_the_switch(scribase_env):
    old = _hs256(_scribase_claims("u-1", "a@example.com", iss=f"{OLD_SUPABASE_URL}/auth/v1"))
    with pytest.raises(supabase_auth.SupabaseAuthError):
        supabase_auth.verify_supabase_jwt(old)


def test_scribase_token_is_rejected_while_the_api_still_points_at_the_old_project(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", OLD_SUPABASE_URL)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SCRIBASE_TEST_SECRET)
    with pytest.raises(supabase_auth.SupabaseAuthError):
        supabase_auth.verify_supabase_jwt(REAL_SCRIBASE_TOKENS["alice"])


def test_wrong_secret_changed_payload_audience_and_expiry_are_rejected(scribase_env):
    good = _scribase_claims("u-2", "b@example.com")
    bad_tokens = [
        _hs256(good, secret="another-environment-secret-0123456789abcdef"),
        _hs256({**good, "aud": "anon"}),
        _hs256(_scribase_claims("u-2", "b@example.com", exp_in=-120)),
    ]
    header, payload, sig = REAL_SCRIBASE_TOKENS["alice"].split(".")
    data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    data["email"] = "mallory@example.com"
    forged = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    bad_tokens.append(f"{header}.{forged}.{sig}")
    for token in bad_tokens:
        with pytest.raises(supabase_auth.SupabaseAuthError):
            supabase_auth.verify_supabase_jwt(token)


def test_hs256_needs_the_environment_secret(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", SCRIBASE_URL)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    with pytest.raises(supabase_auth.SupabaseAuthError, match="SUPABASE_JWT_SECRET"):
        supabase_auth.verify_supabase_jwt(REAL_SCRIBASE_TOKENS["alice"])


class _JwksServer:
    """Serves <url>/auth/v1/.well-known/jwks.json the way Scribase auth does."""

    def __init__(self, jwks: dict):
        body = json.dumps(jwks).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - http.server API
                if self.path != "/auth/v1/.well-known/jwks.json":
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                return

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_exc):
        self.server.shutdown()
        self.server.server_close()


def _es256_jwk(key: ec.EllipticCurvePrivateKey, kid: str) -> dict:
    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    # keys.rs adds these three to the public JWK.
    jwk.update({"kid": kid, "use": "sig", "alg": "ES256"})
    return jwk


def test_es256_token_verifies_against_a_scribase_shaped_jwks(monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    other = ec.generate_private_key(ec.SECP256R1())
    with _JwksServer({"keys": [_es256_jwk(key, "k1")]}) as srv:
        monkeypatch.setenv("SUPABASE_URL", srv.url)
        monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
        monkeypatch.setattr(supabase_auth, "_jwks_client", None)
        claims = _scribase_claims("u-3", "c@example.com", iss=f"{srv.url}/auth/v1")
        good = jwt.encode(claims, key, algorithm="ES256", headers={"kid": "k1"})
        assert supabase_auth.verify_supabase_jwt(good)["sub"] == "u-3"
        forged = jwt.encode(claims, other, algorithm="ES256", headers={"kid": "k1"})
        with pytest.raises(supabase_auth.SupabaseAuthError):
            supabase_auth.verify_supabase_jwt(forged)


# --------------------------------------------------------------------------- #
# Re-link by verified email (bearer path)
# --------------------------------------------------------------------------- #
def test_existing_user_relinks_by_verified_email_without_a_duplicate_or_second_grant(scribase_env, maker):
    alice_id = _existing_user(maker, "alice@example.com")
    claims = supabase_auth.verify_supabase_jwt(REAL_SCRIBASE_TOKENS["alice"])
    with maker() as s:
        user = principal.get_or_create_supabase_user(s, claims, "req-1")
        s.commit()
        assert user.id == alice_id
    assert _users(maker) == 1
    assert _signup_grants(maker, alice_id) == 1


def test_mobile_user_from_the_old_project_relinks_with_a_new_scribase_subject(scribase_env, maker):
    # Created by the old Supabase project's Apple sign-in: the account carries the
    # provider-verified (relay) email. The Scribase project issues a new subject.
    relay = "x7k2m9@privaterelay.appleid.com"
    old_id = _existing_user(maker, relay)
    claims = supabase_auth.verify_supabase_jwt(_hs256(_scribase_claims("new-sub-1", relay, provider="apple")))
    with maker() as s:
        assert principal.get_or_create_supabase_user(s, claims, "req-2").id == old_id
        s.commit()
    assert _users(maker) == 1
    assert _signup_grants(maker, old_id) == 1


def test_unverified_email_never_takes_over_an_existing_account(scribase_env, maker):
    alice_id = _existing_user(maker, "alice@example.com")
    claims = supabase_auth.verify_supabase_jwt(
        _hs256(_scribase_claims("attacker-sub", "alice@example.com", provider="email", verified=False))
    )
    with maker() as s:
        user = principal.get_or_create_supabase_user(s, claims, "req-3")
        s.commit()
        assert user.id != alice_id
        assert user.email == "supabase_attacker-sub@users.reelforge"


def test_new_scribase_user_gets_one_grant_and_the_same_account_next_time(scribase_env, maker, monkeypatch):
    monkeypatch.setattr(principal, "_rally_signed_up", lambda *a, **k: None)
    claims = supabase_auth.verify_supabase_jwt(REAL_SCRIBASE_TOKENS["bob"])
    with maker() as s:
        first = principal.get_or_create_supabase_user(s, claims, "req-4")
        s.commit()
    with maker() as s:
        second = principal.get_or_create_supabase_user(s, claims, "req-5")
        s.commit()
    assert first.id == second.id
    assert _users(maker) == 1
    assert _signup_grants(maker, first.id) == 1


# --------------------------------------------------------------------------- #
# Re-link on POST /auth/device (what the app calls after sign-in)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def device_client(scribase_env, maker, monkeypatch):
    @contextmanager
    def _session():
        s = maker()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr(device_mod, "get_session", _session)
    monkeypatch.setattr(device_mod, "require_signup_enabled", lambda *a, **k: None)
    monkeypatch.setattr(device_mod, "_rally_signed_up", lambda *a, **k: None)
    monkeypatch.setattr(service, "_get_redis", lambda: None)
    monkeypatch.setattr(ratelimit, "_get_client", lambda: None)
    ratelimit.reset_local_buckets()
    monkeypatch.setenv("REELFORGE_DEVICE_AUTH_SECRET", DEVICE_SECRET)
    for name in ("APPLE_APP_ATTEST_APP_ID", "APPLE_APP_ATTEST_ROOT_CA", "PLAY_INTEGRITY_PACKAGE",
                 "PLAY_INTEGRITY_SERVICE_ACCOUNT", "MENIVOR_DEVICE_GRANT_GATE", "MENIVOR_TRUSTED_PROXIES"):
        monkeypatch.delenv(name, raising=False)

    app = FastAPI()
    app.include_router(device_mod.router)

    def _handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)
        )

    app.add_exception_handler(HttpException, _handler)
    return TestClient(app, client=("10.0.0.2", 50000))


def _device_sign_in(client, token: str, install: str):
    return client.post(
        "/api/v1/auth/device",
        json={"install_id": install, "platform": "ios", "supabase_access_token": token},
        headers={"CF-Connecting-IP": "203.0.113.9"},
    )


def test_device_sign_in_with_a_scribase_token_relinks_the_existing_account(device_client, maker):
    alice_id = _existing_user(maker, "alice@example.com")
    resp = _device_sign_in(device_client, REAL_SCRIBASE_TOKENS["alice"], "install-mn9-0001-0123456789abcdef")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["user_id"] == alice_id
    assert data["linked"] is True
    assert data["created"] is False
    assert _users(maker) == 1
    assert _signup_grants(maker, alice_id) == 1


def test_second_phone_lands_on_the_same_account_with_no_new_grant(device_client, maker):
    first = _device_sign_in(device_client, REAL_SCRIBASE_TOKENS["bob"], "install-mn9-0002-0123456789abcdef")
    assert first.status_code == 200, first.text
    bob_id = first.json()["data"]["user_id"]
    grants_after_first = _signup_grants(maker, bob_id)
    assert grants_after_first <= 1
    second = _device_sign_in(device_client, REAL_SCRIBASE_TOKENS["bob"], "install-mn9-0003-0123456789abcdef")
    assert second.status_code == 200, second.text
    assert second.json()["data"]["user_id"] == bob_id
    assert _users(maker) == 1
    assert _signup_grants(maker, bob_id) == grants_after_first


def test_device_sign_in_rejects_an_old_project_token(device_client, maker):
    old = _hs256(_scribase_claims("u-9", "z@example.com", iss=f"{OLD_SUPABASE_URL}/auth/v1"))
    resp = _device_sign_in(device_client, old, "install-mn9-0004-0123456789abcdef")
    assert resp.status_code == 401
    assert _users(maker) == 0
