"""Mobile sign-in verification fails safe (2026-10-06).

The old shared Supabase project (psqkkdjzgptfcqpxuxki) is NXDOMAIN. Menivor's
API must keep working while SUPABASE_URL is unset, wrong or unreachable, never
accept an unverified token, and accept the new Scribase project's tokens (HS256
with the environment secret, ES256/RS256 through JWKS) once it is configured.

Covered here (the happy paths and claim checks live in test_scribase_jwt.py):
* SUPABASE_URL unset -> verification refused at once, /auth/device answers 503
  for a sign-in token, guest device sessions and other bearers still work;
  a secret without a URL is NOT enough (the issuer could not be checked);
* JWKS host that never answers -> fails closed within the configured timeout,
  the next calls fail fast (negative cache), callers get 503 not 401/500;
* alg=none / non-allowlisted algs rejected without touching the network;
* RS256 through JWKS accepted, kid mismatch rejected;
* user identity only ever comes from the verified token: forged user-id
  headers are ignored.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from types import SimpleNamespace

import pytest

jwt = pytest.importorskip("jwt", reason="PyJWT is not installed")
from app.core import supabase_auth
from app.core.auth import principal
from app.models.exception import HttpException
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from starlette.requests import Request

from tests.reelforge.test_scribase_jwt import (  # noqa: F401 - fixtures
    REAL_SCRIBASE_TOKENS,
    SCRIBASE_TEST_SECRET,
    SCRIBASE_URL,
    _device_sign_in,
    _es256_jwk,
    _hs256,
    _JwksServer,
    _scribase_claims,
    _users,
    device_client,
    maker,
    scribase_env,
)


@pytest.fixture(autouse=True)
def _fresh_jwks_state(monkeypatch):
    monkeypatch.setattr(supabase_auth, "_jwks_client", None)
    monkeypatch.setattr(supabase_auth, "_jwks_client_url", "")
    supabase_auth.reset_jwks_failure()
    yield
    supabase_auth.reset_jwks_failure()


def _request(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw, "query_string": b""})


class _BlackholeServer:
    """Accepts TCP connections and never answers (a JWKS host that hangs)."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.url = f"http://127.0.0.1:{self.sock.getsockname()[1]}"
        self.conns = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        self.sock.settimeout(0.2)
        while not self.stop.is_set():
            try:
                conn, _ = self.sock.accept()
                self.conns.append(conn)
            except OSError:
                continue

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_exc):
        self.stop.set()
        self.thread.join(timeout=2)
        for conn in self.conns:
            conn.close()
        self.sock.close()


def _es256_token(key, iss: str, kid: str = "k1", **extra) -> str:
    claims = {**_scribase_claims("u-es", "es@example.com", iss=iss), **extra}
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": kid})


# --------------------------------------------------------------------------- #
# SUPABASE_URL unset
# --------------------------------------------------------------------------- #
def test_unset_url_is_not_configured_even_with_a_secret(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SCRIBASE_TEST_SECRET)
    assert supabase_auth.is_configured() is False
    started = time.monotonic()
    with pytest.raises(supabase_auth.SupabaseAuthError):
        supabase_auth.verify_supabase_jwt(REAL_SCRIBASE_TOKENS["alice"])
    assert time.monotonic() - started < 0.5


def test_unset_url_device_sign_in_is_503_and_guest_sessions_still_work(device_client, maker, monkeypatch):  # noqa: F811 - pytest fixtures
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    started = time.monotonic()
    resp = _device_sign_in(device_client, REAL_SCRIBASE_TOKENS["alice"], "install-fs-0001-0123456789abcdef")
    assert resp.status_code == 503, resp.text
    assert time.monotonic() - started < 2
    assert _users(maker) == 0
    guest = device_client.post(
        "/api/v1/auth/device",
        json={"install_id": "install-fs-0002-0123456789abcdef", "platform": "ios"},
        headers={"CF-Connecting-IP": "203.0.113.9"},
    )
    assert guest.status_code == 200, guest.text


def test_unset_url_bearer_falls_through_instead_of_trusting_the_token(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SCRIBASE_TEST_SECRET)
    req = _request({"authorization": f"Bearer {REAL_SCRIBASE_TOKENS['alice']}"})
    assert principal.resolve_supabase_principal(req, SimpleNamespace(), "rid-1") is None


def test_startup_check_warns_once_when_unset(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    status = supabase_auth.startup_check()
    assert status["configured"] is False
    assert "SUPABASE_URL" in status["warning"]
    monkeypatch.setenv("SUPABASE_URL", SCRIBASE_URL + "/")
    status = supabase_auth.startup_check()
    assert status["configured"] is True
    assert status["issuer"] == f"{SCRIBASE_URL}/auth/v1"


# --------------------------------------------------------------------------- #
# JWKS unreachable / hanging
# --------------------------------------------------------------------------- #
def test_hanging_jwks_fails_closed_within_the_timeout_then_fast(monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    with _BlackholeServer() as srv:
        monkeypatch.setenv("SUPABASE_URL", srv.url)
        monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
        monkeypatch.setenv("SUPABASE_JWKS_TIMEOUT_SECONDS", "0.5")
        token = _es256_token(key, f"{srv.url}/auth/v1")
        started = time.monotonic()
        with pytest.raises(supabase_auth.SupabaseUnavailableError):
            supabase_auth.verify_supabase_jwt(token)
        assert time.monotonic() - started < 3
        started = time.monotonic()
        with pytest.raises(supabase_auth.SupabaseUnavailableError):
            supabase_auth.verify_supabase_jwt(token)
        assert time.monotonic() - started < 0.2


def test_unresolvable_jwks_host_is_503_on_the_bearer_path(monkeypatch):
    url = "https://psqkkdjzgptfcqpxuxki.invalid"
    monkeypatch.setenv("SUPABASE_URL", url)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.setenv("SUPABASE_JWKS_TIMEOUT_SECONDS", "1")
    token = _es256_token(ec.generate_private_key(ec.SECP256R1()), f"{url}/auth/v1")
    req = _request({"authorization": f"Bearer {token}"})
    with pytest.raises(HttpException) as info:
        principal.resolve_supabase_principal(req, SimpleNamespace(), "rid-2")
    assert info.value.status_code == 503


def test_unreachable_jwks_device_sign_in_is_503(device_client, maker, monkeypatch):  # noqa: F811 - pytest fixtures
    url = "https://psqkkdjzgptfcqpxuxki.invalid"
    monkeypatch.setenv("SUPABASE_URL", url)
    monkeypatch.setenv("SUPABASE_JWKS_TIMEOUT_SECONDS", "1")
    token = _es256_token(ec.generate_private_key(ec.SECP256R1()), f"{url}/auth/v1")
    resp = _device_sign_in(device_client, token, "install-fs-0003-0123456789abcdef")
    assert resp.status_code == 503, resp.text
    assert _users(maker) == 0


def test_jwks_recovers_after_the_failure_window(monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    with _JwksServer({"keys": [_es256_jwk(key, "k1")]}) as srv:
        monkeypatch.setenv("SUPABASE_URL", srv.url)
        monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
        supabase_auth._note_jwks_failure(f"{srv.url}/auth/v1/.well-known/jwks.json")
        token = _es256_token(key, f"{srv.url}/auth/v1")
        with pytest.raises(supabase_auth.SupabaseUnavailableError):
            supabase_auth.verify_supabase_jwt(token)
        monkeypatch.setenv("SUPABASE_JWKS_RETRY_SECONDS", "0")
        assert supabase_auth.verify_supabase_jwt(token)["sub"] == "u-es"


# --------------------------------------------------------------------------- #
# Algorithms and keys
# --------------------------------------------------------------------------- #
def test_alg_none_and_unlisted_algs_are_rejected_without_network(monkeypatch):
    with _BlackholeServer() as srv:
        monkeypatch.setenv("SUPABASE_URL", srv.url)
        monkeypatch.setenv("SUPABASE_JWT_SECRET", SCRIBASE_TEST_SECRET)
        claims = _scribase_claims("u-n", "n@example.com", iss=f"{srv.url}/auth/v1")
        none_token = jwt.encode(claims, None, algorithm="none")
        hs512 = jwt.encode(claims, SCRIBASE_TEST_SECRET, algorithm="HS512")
        for token in (none_token, hs512):
            started = time.monotonic()
            with pytest.raises(supabase_auth.SupabaseAuthError) as info:
                supabase_auth.verify_supabase_jwt(token)
            assert not isinstance(info.value, supabase_auth.SupabaseUnavailableError)
            assert time.monotonic() - started < 0.3
        assert srv.conns == []


def test_rs256_through_jwks_and_kid_mismatch(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": "r1", "use": "sig", "alg": "RS256"})
    with _JwksServer({"keys": [jwk]}) as srv:
        monkeypatch.setenv("SUPABASE_URL", srv.url)
        monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
        claims = _scribase_claims("u-rs", "rs@example.com", iss=f"{srv.url}/auth/v1")
        good = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "r1"})
        assert supabase_auth.verify_supabase_jwt(good)["sub"] == "u-rs"
        wrong_kid = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "other"})
        with pytest.raises(supabase_auth.SupabaseAuthError):
            supabase_auth.verify_supabase_jwt(wrong_kid)


def test_es256_wrong_issuer_audience_and_expiry_rejected(monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    with _JwksServer({"keys": [_es256_jwk(key, "k1")]}) as srv:
        monkeypatch.setenv("SUPABASE_URL", srv.url)
        monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
        iss = f"{srv.url}/auth/v1"
        for bad in (
            _es256_token(key, "https://other.example/auth/v1"),
            _es256_token(key, iss, aud="anon"),
            _es256_token(key, iss, exp=int(time.time()) - 120),
            _es256_token(key, iss, sub=""),
        ):
            with pytest.raises(supabase_auth.SupabaseAuthError):
                supabase_auth.verify_supabase_jwt(bad)


# --------------------------------------------------------------------------- #
# Identity only from the verified token
# --------------------------------------------------------------------------- #
FORGED_HEADERS = {
    "x-user-id": "victim-user",
    "x-menivor-user": "victim-user",
    "x-reelforge-user": "victim-user",
    "x-supabase-user": "victim-user",
}


def test_forged_user_headers_without_a_token_are_401(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", SCRIBASE_URL)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SCRIBASE_TEST_SECRET)
    req = _request(FORGED_HEADERS)
    assert principal.resolve_supabase_principal(req, SimpleNamespace(), "rid-3") is None
    with pytest.raises(HttpException) as info:
        principal.resolve_principal(req, SimpleNamespace(query=lambda *_a: None), "rid-3")
    assert info.value.status_code == 401


def test_forged_headers_do_not_change_the_linked_account(device_client, maker):  # noqa: F811 - pytest fixtures
    resp = device_client.post(
        "/api/v1/auth/device",
        json={
            "install_id": "install-fs-0004-0123456789abcdef",
            "platform": "ios",
            "supabase_access_token": REAL_SCRIBASE_TOKENS["alice"],
        },
        headers={"CF-Connecting-IP": "203.0.113.9", **FORGED_HEADERS},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["user_id"] != "victim-user"
    tampered = _hs256(_scribase_claims("victim-user", "v@example.com"), secret="not-the-secret-0123456789abcdef")
    bad = _device_sign_in(device_client, tampered, "install-fs-0005-0123456789abcdef")
    assert bad.status_code == 401
