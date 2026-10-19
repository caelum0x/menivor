"""MN3: the mobile free grant needs attestation or a verified identity; device
accounts are capped per IP and per /24; repeat cards and emails get no grant."""

from __future__ import annotations

import base64
import hashlib
import struct
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.x509.oid import NameOID
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.controllers.v1.device_auth as device_mod
from app.models.db.base import Base
from app.models.db.models import User
from app.models.db.repositories import CreditRepository
from app.models.exception import HttpException
from app.services import ratelimit
from app.services.abuse import device_attest, grant_markers
from app.services.billing import card_check, service
from app.services.billing.plans import SIGNUP_GRANT
from app.utils import utils

SECRET = "s" * 40
APP_ID = "TEAM123456.com.arhansuba.menivor"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def env(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

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

    from app.models.db import base as db_base

    monkeypatch.setattr(db_base, "get_session", _session)
    monkeypatch.setattr(device_mod, "get_session", _session)
    monkeypatch.setattr(device_mod, "require_signup_enabled", lambda *a, **k: None)
    monkeypatch.setattr(device_mod, "_rally_signed_up", lambda *a, **k: None)
    monkeypatch.setattr(service, "_get_redis", lambda: None)
    monkeypatch.setattr(ratelimit, "_get_client", lambda: None)  # in-process buckets only
    ratelimit.reset_local_buckets()
    monkeypatch.setenv("REELFORGE_DEVICE_AUTH_SECRET", SECRET)
    for name in ("APPLE_APP_ATTEST_APP_ID", "APPLE_APP_ATTEST_ROOT_CA", "PLAY_INTEGRITY_PACKAGE",
                 "PLAY_INTEGRITY_SERVICE_ACCOUNT", "MENIVOR_DEVICE_GRANT_GATE", "MENIVOR_TRUSTED_PROXIES"):
        monkeypatch.delenv(name, raising=False)

    app = FastAPI()
    app.include_router(device_mod.router)

    def _handler(_request, exc: HttpException):
        return JSONResponse(status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message))

    app.add_exception_handler(HttpException, _handler)
    # The peer is the reverse proxy (private address); the client IP is in CF-Connecting-IP.
    return TestClient(app, client=("10.0.0.2", 50000)), maker


def _device(client, install_id, *, ip="203.0.113.7", platform="ios", **extra):
    body = {"install_id": install_id, "platform": platform, **extra}
    return client.post("/api/v1/auth/device", json=body, headers={"CF-Connecting-IP": ip})


def _install(n: int) -> str:
    return f"install-{n:04d}-0123456789abcdef"


def _users(maker) -> int:
    with maker() as s:
        return int(s.execute(select(func.count()).select_from(User)).scalar())


def _total_credits(maker) -> int:
    with maker() as s:
        return sum(CreditRepository(s).balance(u) for u in s.execute(select(User.id)).scalars())


# --------------------------------------------------------------------------- #
# Device accounts: 0 credits, per-IP and per-/24 caps, request budget
# --------------------------------------------------------------------------- #
def test_new_device_account_has_no_credits_until_attested(env):
    client, _ = env
    resp = _device(client, _install(1))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["credits"] == 0
    assert data["free_credits"]["status"] == "pending"


def test_fifty_random_install_ids_from_one_ip_give_five_accounts_and_no_credits(env):
    client, maker = env
    statuses = [_device(client, _install(i)).status_code for i in range(50)]
    assert statuses.count(200) == 5
    assert set(statuses) <= {200, 429}
    assert _users(maker) == 5
    assert _total_credits(maker) == 0


def test_existing_device_account_still_signs_in_after_the_cap(env):
    client, _ = env
    for i in range(5):
        assert _device(client, _install(i)).status_code == 200
    assert _device(client, _install(99)).status_code == 429
    again = _device(client, _install(0))
    assert again.status_code == 200 and again.json()["data"]["created"] is False


def test_network_cap_counts_the_whole_slash_24(env, monkeypatch):
    client, maker = env
    monkeypatch.setenv("MENIVOR_DEVICE_ACCOUNTS_PER_NET_DAY", "3")
    codes = [_device(client, _install(i), ip=f"198.51.100.{i + 1}").status_code for i in range(6)]
    assert codes == [200, 200, 200, 429, 429, 429]
    assert _device(client, _install(50), ip="192.0.2.9").status_code == 200  # another network


def test_request_budget_holds_when_redis_is_down(env, monkeypatch):
    client, _ = env
    monkeypatch.setattr(ratelimit, "_get_client", lambda: None)
    ok = sum(
        _device(client, _install(1)).status_code == 200
        for _ in range(device_attest.IP_REQUESTS_PER_WINDOW + 5)
    )
    assert ok == device_attest.IP_REQUESTS_PER_WINDOW
    assert _device(client, _install(1)).json()["data"]["code"] == "device_rate_limited"


def test_forwarded_headers_are_ignored_from_an_untrusted_peer():
    class _Req:
        def __init__(self, peer, headers):
            self.client = type("C", (), {"host": peer})()
            self.headers = headers

    assert device_attest.client_ip(_Req("203.0.113.5", {"cf-connecting-ip": "1.1.1.1"})) == "203.0.113.5"
    assert device_attest.client_ip(_Req("10.0.0.2", {"cf-connecting-ip": "1.1.1.1"})) == "1.1.1.1"
    assert device_attest.client_ip(_Req("10.0.0.2", {"x-forwarded-for": "9.9.9.9, 10.0.0.3"})) == "9.9.9.9"


# --------------------------------------------------------------------------- #
# App Attest (a synthetic Apple-shaped chain)
# --------------------------------------------------------------------------- #
def _cbor(value) -> bytes:
    def head(major, n):
        if n < 24:
            return bytes([(major << 5) | n])
        for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
            if n < 1 << (8 * size):
                return bytes([(major << 5) | info]) + n.to_bytes(size, "big")
        raise ValueError(n)

    if isinstance(value, bytes):
        return head(2, len(value)) + value
    if isinstance(value, str):
        raw = value.encode()
        return head(3, len(raw)) + raw
    if isinstance(value, int):
        return head(0, value)
    if isinstance(value, list):
        return head(4, len(value)) + b"".join(_cbor(v) for v in value)
    if isinstance(value, dict):
        return head(5, len(value)) + b"".join(_cbor(k) + _cbor(v) for k, v in value.items())
    raise TypeError(value)


def _cert(subject, issuer, pub, key, *, ca, extensions=()):
    now = datetime.now(timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer)]))
        .public_key(pub)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    )
    for ext in extensions:
        builder = builder.add_extension(ext, critical=False)
    return builder.sign(key, hashes.SHA256())


class _AppAttest:
    def __init__(self):
        self.root_key = ec.generate_private_key(ec.SECP384R1())
        self.root = _cert("Test App Attestation Root CA", "Test App Attestation Root CA",
                          self.root_key.public_key(), self.root_key, ca=True)
        self.inter_key = ec.generate_private_key(ec.SECP384R1())
        self.inter = _cert("Test App Attestation CA 1", "Test App Attestation Root CA",
                           self.inter_key.public_key(), self.root_key, ca=True)

    def root_pem(self) -> str:
        return self.root.public_bytes(serialization.Encoding.PEM).decode()

    def attest(self, challenge: str, *, app_id: str = APP_ID) -> dict:
        cred_key = ec.generate_private_key(ec.SECP256R1())
        point = cred_key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        key_raw = hashlib.sha256(point).digest()
        auth = (
            hashlib.sha256(app_id.encode()).digest() + b"\x41" + struct.pack(">I", 0)
            + b"appattest" + b"\x00" * 7 + struct.pack(">H", len(key_raw)) + key_raw + b"\xa0"
        )
        nonce = hashlib.sha256(auth + hashlib.sha256(challenge.encode()).digest()).digest()
        ext = x509.UnrecognizedExtension(
            x509.ObjectIdentifier("1.2.840.113635.100.8.2"),
            bytes([0x30, 0x24, 0xA1, 0x22, 0x04, 0x20]) + nonce,
        )
        cred = _cert("cred", "Test App Attestation CA 1", cred_key.public_key(), self.inter_key,
                     ca=False, extensions=[ext])
        obj = {
            "fmt": "apple-appattest",
            "attStmt": {"x5c": [cred.public_bytes(Encoding.DER), self.inter.public_bytes(Encoding.DER)], "receipt": b""},
            "authData": auth,
        }
        return {
            "challenge": challenge,
            "key_id": base64.b64encode(key_raw).decode(),
            "attestation": base64.b64encode(_cbor(obj)).decode(),
        }


@pytest.fixture()
def apple(env, monkeypatch):
    ca = _AppAttest()
    monkeypatch.setenv("APPLE_APP_ATTEST_APP_ID", APP_ID)
    monkeypatch.setenv("APPLE_APP_ATTEST_ROOT_CA", ca.root_pem())
    return ca


def _challenge(client, install_id, platform="ios") -> str:
    resp = client.post("/api/v1/auth/device/challenge", json={"install_id": install_id, "platform": platform},
                       headers={"CF-Connecting-IP": "203.0.113.7"})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["challenge"]


def test_app_attest_unlocks_the_free_credits_once(env, apple):
    client, _ = env
    install = _install(1)
    attestation = apple.attest(_challenge(client, install))
    resp = _device(client, install, attestation=attestation)
    data = resp.json()["data"]
    assert data["credits"] == SIGNUP_GRANT and data["free_credits"]["status"] == "granted"
    again = _device(client, install, attestation=apple.attest(_challenge(client, install)))
    assert again.json()["data"]["credits"] == SIGNUP_GRANT


def test_app_attest_key_reused_on_another_install_is_withheld(env, apple):
    client, _ = env
    first = apple.attest(_challenge(client, _install(1)))
    assert _device(client, _install(1), attestation=first).json()["data"]["credits"] == SIGNUP_GRANT
    # Same key id, fresh valid challenge for a second install: the grant is refused.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(device_attest, "verify", lambda *a, **k: device_attest.AttestResult(
            True, "app_attest", device_key=base64.b64decode(first["key_id"]).hex()))
        second = _device(client, _install(2), attestation=first)
    assert second.json()["data"]["free_credits"]["status"] == "withheld"
    assert second.json()["data"]["credits"] == 0


@pytest.mark.parametrize("tamper", ["wrong_app", "wrong_install", "expired", "other_root"])
def test_invalid_app_attest_grants_nothing(env, apple, monkeypatch, tamper):
    client, _ = env
    install = _install(1)
    challenge = _challenge(client, install)
    if tamper == "wrong_app":
        attestation = apple.attest(challenge, app_id="TEAM123456.com.other.app")
    elif tamper == "wrong_install":
        attestation = apple.attest(_challenge(client, _install(2)))
    elif tamper == "expired":
        old = device_attest.issue_challenge(SECRET.encode(), "ios", install, now=time.time() - 3600)
        attestation = apple.attest(old)
    else:
        attestation = _AppAttest().attest(challenge)
    resp = _device(client, install, attestation=attestation)
    assert resp.status_code == 200
    assert resp.json()["data"]["credits"] == 0
    assert resp.json()["data"]["free_credits"]["status"] == "pending"


# --------------------------------------------------------------------------- #
# Play Integrity
# --------------------------------------------------------------------------- #
def test_play_integrity_verdict_rules():
    challenge = "c" * 32
    good = {
        "requestDetails": {"requestPackageName": "com.menivor", "nonce": challenge,
                           "timestampMillis": int(time.time() * 1000)},
        "appIntegrity": {"appRecognitionVerdict": "PLAY_RECOGNIZED"},
        "deviceIntegrity": {"deviceRecognitionVerdict": ["MEETS_DEVICE_INTEGRITY"]},
    }
    device_attest.check_play_verdict(good, package="com.menivor", challenge=challenge)
    bad_cases = [
        {**good, "appIntegrity": {"appRecognitionVerdict": "UNRECOGNIZED_VERSION"}},
        {**good, "deviceIntegrity": {"deviceRecognitionVerdict": []}},
        {**good, "requestDetails": {**good["requestDetails"], "nonce": "other"}},
        {**good, "requestDetails": {**good["requestDetails"], "requestPackageName": "x"}},
        {**good, "requestDetails": {**good["requestDetails"], "timestampMillis": 1}},
    ]
    for case in bad_cases:
        with pytest.raises(device_attest.AttestationError):
            device_attest.check_play_verdict(case, package="com.menivor", challenge=challenge)


def test_play_integrity_unlocks_android_install(env, monkeypatch):
    client, _ = env
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    import json as _json

    monkeypatch.setenv("PLAY_INTEGRITY_PACKAGE", "com.menivor")
    monkeypatch.setenv("PLAY_INTEGRITY_SERVICE_ACCOUNT", _json.dumps(
        {"client_email": "svc@x.iam.gserviceaccount.com", "private_key": pem}))
    monkeypatch.setattr(device_attest, "_token_cache", {})
    install = _install(7)
    challenge = _challenge(client, install, "android")
    calls = []

    def _post(url, *, data=None, json_body=None, token=""):
        calls.append(url)
        if "oauth2" in url:
            return {"access_token": "tok", "expires_in": 3600}
        assert token == "tok" and json_body == {"integrity_token": "itok"}
        return {"tokenPayloadExternal": {
            "requestDetails": {"requestPackageName": "com.menivor", "nonce": challenge,
                               "timestampMillis": int(time.time() * 1000)},
            "appIntegrity": {"appRecognitionVerdict": "PLAY_RECOGNIZED"},
            "deviceIntegrity": {"deviceRecognitionVerdict": ["MEETS_DEVICE_INTEGRITY"]},
        }}

    monkeypatch.setattr(device_attest, "_http_post", _post)
    resp = _device(client, install, platform="android",
                   attestation={"challenge": challenge, "integrity_token": "itok"})
    assert resp.json()["data"]["credits"] == SIGNUP_GRANT
    assert any("decodeIntegrityToken" in u for u in calls)


# --------------------------------------------------------------------------- #
# Identity link and repeat emails / cards
# --------------------------------------------------------------------------- #
def _claims(email: str, sub: str, verified: bool = True) -> dict:
    return {"sub": sub, "email": email, "user_metadata": {"email_verified": verified}}


def test_identity_link_unlocks_once_and_repeat_gmail_alias_gets_nothing(env, monkeypatch):
    client, maker = env
    claims = {"value": _claims("jane.doe@gmail.com", "sub-1")}
    monkeypatch.setattr(device_mod, "_identity_claims", lambda *a: claims["value"])
    first = _device(client, _install(1))
    assert first.json()["data"]["credits"] == SIGNUP_GRANT and first.json()["data"]["linked"] is True
    claims["value"] = _claims("JaneDoe+farm@googlemail.com", "sub-2")
    second = _device(client, _install(2))
    assert second.status_code == 200
    assert second.json()["data"]["credits"] == 0


def test_unverified_identity_email_does_not_unlock(env, monkeypatch):
    client, _ = env
    monkeypatch.setattr(device_mod, "_identity_claims", lambda *a: _claims("x@example.com", "sub-9", False))
    resp = _device(client, _install(1))
    assert resp.status_code == 200 and resp.json()["data"]["credits"] == 0


def test_normalize_email_folds_aliases():
    assert grant_markers.normalize_email("J.a.n.e+x@GoogleMail.com") == "jane@gmail.com"
    assert grant_markers.normalize_email("bob+tag@example.com") == "bob@example.com"
    assert grant_markers.normalize_email("device+abc@accounts.reelforge.app") == ""


def test_repeat_card_fingerprint_gets_the_paid_credit_but_no_free_reels(env, monkeypatch):
    _, maker = env
    with maker() as s:
        a = User(email="a@example.com", api_key_hash="ha")
        b = User(email="b@example.com", api_key_hash="hb")
        s.add_all([a, b])
        s.commit()
        a_id, b_id = a.id, b.id
    card_check.fulfill(user_id=a_id, checkout_id="ch_a", external_event_id="evt_a", card_fingerprint="fp_1")
    card_check.fulfill(user_id=b_id, checkout_id="ch_b", external_event_id="evt_b", card_fingerprint="fp_1")
    with maker() as s:
        credits = CreditRepository(s)
        assert credits.balance(a_id) == card_check.CARD_CHECK_CREDITS + SIGNUP_GRANT
        assert credits.balance(b_id) == card_check.CARD_CHECK_CREDITS
        assert card_check.status(s, b_id)["free_credits"] == 0
        assert card_check.status(s, a_id)["free_credits"] == SIGNUP_GRANT


def test_repeat_normalized_email_gets_no_free_reels_on_card_check(env):
    _, maker = env
    with maker() as s:
        a = User(email="sam.smith@gmail.com", api_key_hash="ha")
        b = User(email="samsmith+2@gmail.com", api_key_hash="hb")
        s.add_all([a, b])
        s.commit()
        a_id, b_id = a.id, b.id
    card_check.fulfill(user_id=a_id, checkout_id="ch_a", external_event_id="evt_a")
    card_check.fulfill(user_id=b_id, checkout_id="ch_b", external_event_id="evt_b")
    with maker() as s:
        assert CreditRepository(s).balance(b_id) == card_check.CARD_CHECK_CREDITS


def test_gate_off_restores_the_immediate_grant(env, monkeypatch):
    client, _ = env
    monkeypatch.setenv("MENIVOR_DEVICE_GRANT_GATE", "off")
    assert _device(client, _install(1)).json()["data"]["credits"] == SIGNUP_GRANT
