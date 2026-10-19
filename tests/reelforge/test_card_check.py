"""$1 card check that unlocks the free signup reels on the web (Creem).

Real SQLite ledger + real billing service; only Creem HTTP and Redis are faked.

* status: a fresh web account is locked with 0 credits; mobile/web signup
  grants and paid purchases count as unlocked.
* POST /billing/card-check opens a Creem checkout for the card-check product
  with the onboarding return URL (public web origin, safe ``next``), 409 once
  unlocked, 503 with a how-to-fix message when Creem is not configured.
* The signed success redirect credits 1 reel + SIGNUP_GRANT exactly once, and
  a later webhook for the same checkout grants nothing more.
* Unsigned / tampered redirects are rejected.
* Web browsers cannot mint new guest device accounts; native apps still can
  (with 0 credits until the install attests or links an identity: MN3).
* Clerk session tokens sent in ``x-api-key`` are recognised as bearer tokens,
  and the PyJWT-free RS256 verifier accepts/rejects correctly.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from contextlib import contextmanager
from urllib.parse import parse_qsl, urlencode, urlsplit

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.controllers.v1.billing as billing_mod
import app.models.db.base as db_base
from app.config import config
from app.models.db.base import Base
from app.models.db.models import User
from app.models.db.repositories import CreditRepository
from app.models.exception import HttpException
from app.services.billing import card_check, creem_client, service
from app.services.billing.plans import SIGNUP_GRANT
from app.utils import utils

API_KEY = "creem_test_key_for_signing"
CARD_PRODUCT = "prod_card_check_1"
STARTER_PRODUCT = "prod_starter_1"
WEBHOOK_SECRET = "whsec_card_test"


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        session = Factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(billing_mod, "get_session", _session)
    monkeypatch.setattr(billing_mod, "_DB_IMPORT_ERROR", None)
    monkeypatch.setattr(db_base, "get_session", _session)
    monkeypatch.setattr(service, "_get_redis", lambda: None)
    monkeypatch.setattr(
        config,
        "creem",
        {
            "api_key": API_KEY,
            "webhook_secret": WEBHOOK_SECRET,
            "card_check_product_id": CARD_PRODUCT,
            "starter_product_id": STARTER_PRODUCT,
            "web_base_url": "https://menivor.com",
            "success_url": "https://menivor.com/billing?checkout=return",
        },
        raising=False,
    )

    captured: dict = {}

    def _fake_checkout(user, plan, workspace_id=None, success_url=None):
        captured.update(user=dict(user), plan=dict(plan), success_url=success_url)
        return {"checkout_url": "https://checkout.creem.io/ch_1", "session_id": "ch_1"}

    monkeypatch.setattr(creem_client, "create_checkout_session", _fake_checkout)

    app = FastAPI()
    app.include_router(billing_mod.router)

    def _handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _handler)

    with _session() as s:
        user = User(email="web@example.com", display_name="Web", api_key_hash=_hash("rk_web"))
        s.add(user)
        s.flush()
        user_id = user.id
    return TestClient(app), Factory, user_id, captured


def _signed_query(pairs: list[tuple[str, str]]) -> str:
    sig = creem_client._redirect_digest(pairs, API_KEY)
    return urlencode([("checkout", "return"), *pairs, ("signature", sig)])


def _balance(Factory, user_id: str) -> int:
    with Factory() as s:
        return CreditRepository(s).balance(user_id)


def test_new_web_account_is_locked_with_no_credits(env):
    client, Factory, user_id, _ = env
    resp = client.get("/api/v1/billing/card-check", headers={"x-api-key": "rk_web"})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["unlocked"] is False
    assert data["available"] is True
    assert data["credits"] == 0
    assert data["price_usd"] == 1.0
    assert data["card_check_credits"] == 1
    assert data["free_credits"] == SIGNUP_GRANT


def test_start_card_check_opens_creem_checkout_with_onboarding_return(env):
    client, _, user_id, captured = env
    resp = client.post(
        "/api/v1/billing/card-check",
        headers={"x-api-key": "rk_web"},
        json={"next": "/create?q=https%3A%2F%2Fshop.example&auto=1"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["checkout_url"] == "https://checkout.creem.io/ch_1"
    assert captured["user"] == {"id": user_id}
    assert captured["plan"]["creem_product_id"] == CARD_PRODUCT
    assert captured["plan"]["key"] == "card_check"
    parts = urlsplit(captured["success_url"])
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == "https://menivor.com/onboarding"
    query = dict(parse_qsl(parts.query))
    assert query["checkout"] == "return"
    assert query["next"] == "/create?q=https%3A%2F%2Fshop.example&auto=1"


@pytest.mark.parametrize(
    "raw", ["https://evil.example/x", "//evil.example", "javascript:alert(1)", "", None, "/\\evil"]
)
def test_safe_next_never_leaves_the_site(raw):
    assert card_check.safe_next(raw) == "/create"


def test_start_card_check_requires_auth(env):
    client, *_ = env
    assert client.post("/api/v1/billing/card-check").status_code == 401


def test_start_card_check_503_when_creem_not_configured(env, monkeypatch):
    client, *_ = env
    monkeypatch.setattr(config, "creem", {"api_key": API_KEY}, raising=False)
    resp = client.post("/api/v1/billing/card-check", headers={"x-api-key": "rk_web"})
    assert resp.status_code == 503
    assert "support@menivor.com" in resp.json()["message"]


def test_signed_redirect_credits_card_check_and_free_reels_once(env):
    client, Factory, user_id, _ = env
    query = _signed_query(
        [
            ("checkout_id", "ch_1"),
            ("order_id", "ord_1"),
            ("product_id", CARD_PRODUCT),
            ("request_id", user_id),
        ]
    )
    first = client.post("/api/v1/billing/creem/confirm", json={"query": query})
    assert first.status_code == 200, first.text
    assert first.json()["data"]["unlocked"] is True
    expected = card_check.CARD_CHECK_CREDITS + SIGNUP_GRANT
    assert _balance(Factory, user_id) == expected

    # Refresh of the return page: no double grant.
    again = client.post("/api/v1/billing/creem/confirm", json={"query": query})
    assert again.status_code == 200
    assert _balance(Factory, user_id) == expected

    # A later webhook for the same checkout: still no double grant.
    body = json.dumps(
        {
            "id": "evt_1",
            "eventType": "checkout.completed",
            "object": {
                "id": "ch_1",
                "request_id": user_id,
                "metadata": {"user_id": user_id, "plan_key": "card_check", "credits": "1"},
            },
        }
    ).encode("utf-8")
    sig = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    service.handle_creem_webhook(body, sig)
    assert _balance(Factory, user_id) == expected

    status = client.get("/api/v1/billing/card-check", headers={"x-api-key": "rk_web"}).json()["data"]
    assert status["unlocked"] is True
    assert client.post("/api/v1/billing/card-check", headers={"x-api-key": "rk_web"}).status_code == 409


def test_webhook_alone_unlocks_card_check(env):
    _, Factory, user_id, _ = env
    body = json.dumps(
        {
            "id": "evt_2",
            "eventType": "checkout.completed",
            "object": {
                "id": "ch_2",
                "metadata": {"user_id": user_id, "plan_key": "card_check", "credits": "1"},
            },
        }
    ).encode("utf-8")
    sig = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    service.handle_creem_webhook(body, sig)
    assert _balance(Factory, user_id) == card_check.CARD_CHECK_CREDITS + SIGNUP_GRANT


def test_signed_redirect_for_a_pack_credits_the_pack(env):
    client, Factory, user_id, _ = env
    query = _signed_query(
        [("checkout_id", "ch_p"), ("product_id", STARTER_PRODUCT), ("request_id", user_id)]
    )
    # plans.py builds its catalog at import; point the starter plan at our id.
    from app.services.billing import plans

    starter = plans.get_plan("starter")
    patched = type(starter)(**{**starter.__dict__, "creem_product_id": STARTER_PRODUCT})
    original = plans._CATALOG
    plans._CATALOG = {**dict(original), "starter": patched}
    try:
        resp = client.post("/api/v1/billing/creem/confirm", json={"query": query})
    finally:
        plans._CATALOG = original
    assert resp.status_code == 200, resp.text
    assert _balance(Factory, user_id) == starter.credits


def test_tampered_redirect_is_rejected(env):
    client, Factory, user_id, _ = env
    query = _signed_query([("checkout_id", "ch_1"), ("product_id", CARD_PRODUCT), ("request_id", user_id)])
    tampered = query.replace(user_id, "someone-else")
    assert client.post("/api/v1/billing/creem/confirm", json={"query": tampered}).status_code == 400
    unsigned = urlencode([("checkout_id", "ch_1"), ("product_id", CARD_PRODUCT), ("request_id", user_id)])
    assert client.post("/api/v1/billing/creem/confirm", json={"query": unsigned}).status_code == 400
    assert _balance(Factory, user_id) == 0


def test_mobile_and_paid_accounts_count_as_unlocked(env):
    _, Factory, user_id, _ = env
    with Factory() as s:
        assert card_check.is_unlocked(s, user_id) is False
        CreditRepository(s).grant(user_id, SIGNUP_GRANT, "mobile_device_signup")
        s.commit()
        assert card_check.is_unlocked(s, user_id) is True


# --------------------------------------------------------------------------- #
# Web guest device accounts are refused; native apps keep working
# --------------------------------------------------------------------------- #
@pytest.fixture()
def device_env(env, monkeypatch):
    import app.controllers.v1.device_auth as device_mod

    _, Factory, _, _ = env
    monkeypatch.setattr(device_mod, "get_session", db_base.get_session)
    monkeypatch.setenv("REELFORGE_DEVICE_AUTH_SECRET", "x" * 40)
    monkeypatch.setattr(device_mod, "require_signup_enabled", lambda *a, **k: None)
    monkeypatch.setattr(device_mod, "_rally_signed_up", lambda *a, **k: None, raising=False)
    app = FastAPI()
    app.include_router(device_mod.router)

    def _handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _handler)
    return TestClient(app), Factory


def test_browser_cannot_create_guest_device_account(device_env):
    client, _ = device_env
    body = {"install_id": "web-install-id-0123456789abcdef", "platform": "android"}
    resp = client.post("/api/v1/auth/device", json=body, headers={"Origin": "https://menivor.com"})
    assert resp.status_code == 403
    assert resp.json()["data"]["code"] == "web_guest_disabled"


def test_native_app_still_gets_device_account_free_credits_pending(device_env):
    client, _ = device_env
    body = {"install_id": "ios-install-id-0123456789abcdef", "platform": "ios"}
    resp = client.post("/api/v1/auth/device", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["created"] is True
    assert data["credits"] == 0  # MN3: granted after App Attest or an identity link
    assert data["free_credits"] == {
        "status": "pending", "amount": SIGNUP_GRANT, "attestation_available": False,
    }


# --------------------------------------------------------------------------- #
# Clerk token transport + PyJWT-free RS256 verification
# --------------------------------------------------------------------------- #
class _Req:
    def __init__(self, headers):
        self.headers = {k.lower(): v for k, v in headers.items()}


def test_clerk_token_in_x_api_key_is_treated_as_bearer():
    from app.core import clerk

    jwt_like = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.c2ln"
    assert clerk.extract_bearer_token(_Req({"x-api-key": jwt_like})) == jwt_like
    assert clerk.extract_bearer_token(_Req({"x-api-key": "rf_device_abc"})) is None
    assert clerk.extract_bearer_token(_Req({"Authorization": "Bearer tok"})) == "tok"


def test_backend_jwks_used_when_secret_key_set(monkeypatch):
    from app.core import clerk

    cfg = {"secret_key": "sk_test_x", "issuer": "https://clerk.example.com"}
    assert clerk._jwks_url(cfg) == clerk.BACKEND_JWKS_URL
    assert clerk._jwks_headers(cfg, clerk.BACKEND_JWKS_URL) == {
        "Authorization": "Bearer sk_test_x",
        "User-Agent": clerk.JWKS_USER_AGENT,
    }
    # api.clerk.com (Cloudflare) answers 403 to the default "Python-urllib"
    # agent, so every JWKS fetch must send an explicit User-Agent.
    assert clerk._jwks_headers({}, "https://clerk.example.com/.well-known/jwks.json") == {
        "User-Agent": clerk.JWKS_USER_AGENT,
    }
    assert "python-urllib" not in clerk.JWKS_USER_AGENT.lower()
    assert clerk._jwks_url({"issuer": "https://clerk.example.com"}).endswith("/.well-known/jwks.json")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _rsa_token(private_key, claims: dict, kid: str = "k1") -> str:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    header = _b64(json.dumps({"alg": "RS256", "kid": kid, "typ": "JWT"}).encode())
    payload = _b64(json.dumps(claims).encode())
    sig = private_key.sign(f"{header}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{payload}.{_b64(sig)}"


def test_rs256_fallback_verifier(monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import rsa

    from app.core import clerk_rs256

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.public_key().public_numbers()
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "kid": "k1",
                "n": _b64(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")),
                "e": _b64(numbers.e.to_bytes(3, "big")),
            }
        ]
    }
    clerk_rs256.reset_cache()
    monkeypatch.setattr(clerk_rs256, "_fetch_jwks", lambda url, headers: jwks)
    iss = "https://clerk.example.com"
    good = _rsa_token(key, {"sub": "user_1", "iss": iss, "exp": time.time() + 60})
    claims = clerk_rs256.verify(good, jwks_url="u", issuer=iss)
    assert claims["sub"] == "user_1"

    expired = _rsa_token(key, {"sub": "u", "iss": iss, "exp": time.time() - 3600})
    with pytest.raises(clerk_rs256.TokenError):
        clerk_rs256.verify(expired, jwks_url="u", issuer=iss)
    with pytest.raises(clerk_rs256.TokenError):
        clerk_rs256.verify(good, jwks_url="u", issuer="https://other.example")
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = _rsa_token(other, {"sub": "u", "iss": iss, "exp": time.time() + 60})
    with pytest.raises(clerk_rs256.TokenError):
        clerk_rs256.verify(forged, jwks_url="u", issuer=iss)


def test_creem_products_tool_matches_catalog():
    import importlib.util
    from pathlib import Path

    from app.services.billing import plans

    path = Path(__file__).resolve().parents[2] / "apps/api/tools/ops/create_creem_products.py"
    spec = importlib.util.spec_from_file_location("create_creem_products", path)
    tool = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = tool
    spec.loader.exec_module(tool)
    by_env = {p.env: p for p in tool.PRODUCTS}
    assert by_env["CREEM_PRODUCT_ID_CARD_CHECK"].price_cents == int(card_check.CARD_CHECK_PRICE_USD * 100)
    for plan in plans.list_plans(purchasable_only=True):
        product = by_env[f"CREEM_PRODUCT_ID_{plan.key.upper()}"]
        assert product.price_cents == round(plan.price_usd * 100)
        assert str(plan.credits) in product.name
    body = tool.product_body(by_env["CREEM_PRODUCT_ID_STARTER"])
    assert body["billing_type"] == "onetime" and body["currency"] == "USD"
    assert body["tax_category"] == "saas"
    assert body["default_success_url"] == "https://menivor.com/billing?checkout=return"
    assert tool.main([]) == 0  # dry run never calls the network


def test_preflight_accepts_creem_signed_return_without_webhook_secret():
    from app.core.launch_preflight import collect_preflight_errors

    base = {
        "REELFORGE_LAUNCH_MODE": "public",
        "REELFORGE_PUBLIC_LAUNCH_APPROVED": "true",
        "REELFORGE_CHECKOUT_ENABLED": "true",
        "CREEM_API_KEY": "creem_x",
    }
    errors = collect_preflight_errors(production=False, env=base)
    assert any("payment rail" in e for e in errors)
    ok = collect_preflight_errors(
        production=False, env={**base, "CREEM_PRODUCT_ID_STARTER": "prod_1"}
    )
    assert not any("payment rail" in e for e in ok)
