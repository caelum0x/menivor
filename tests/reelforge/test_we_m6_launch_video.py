"""Wave E M-6 (MR8): partner launch video (Menivor side of contract 5.1).

Local Ed25519 JWKS and an introspection stub; no network.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from jwt.algorithms import OKPAlgorithm
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.models.db.base as db_base
from app.domains.funnel_readout import service as readout
from app.domains.funnel_readout.models import FunnelAttribution
from app.domains.partners import launch_video as lv
from app.domains.partners import scribase_tokens as st
from app.models.db.base import Base
from app.models.db.models import AuditLog, User
from app.models.exception import HttpException
from app.utils import utils

ISS = "https://api.scribase.com"
NOW = 1_790_000_000.0
API_KEY = "partner-user-key"


class _Keys:
    def __init__(self):
        self.active = Ed25519PrivateKey.generate()
        self.kid = "k1"

    def jwks(self):
        jwk = json.loads(OKPAlgorithm.to_jwk(self.active.public_key()))
        return {"keys": [{**jwk, "kid": self.kid, "use": "sig", "alg": "EdDSA"}]}

    def token(self, **over):
        claims = {
            "iss": ISS, "aud": "menivor", "sub": "proj_1", "org": "org_1", "cap": "launch-video",
            "jti": "jti_1", "iat": int(NOW) - 60, "exp": int(NOW) + 3600,
        }
        claims.update(over)
        headers = {"kid": over.pop("_kid", self.kid)} if "_kid" not in claims else {"kid": claims.pop("_kid")}
        return jwt.encode(claims, self.active, algorithm="EdDSA", headers=headers)


class _Scribase:
    """Stub JWKS and introspection endpoints with call counters."""

    def __init__(self, keys: _Keys):
        self.keys = keys
        self.revoked: set[str] = set()
        self.jwks_calls = 0
        self.introspect_calls = 0

    def fetch(self, url):
        assert url == f"{ISS}/.well-known/partner-jwks.json"
        self.jwks_calls += 1
        return self.keys.jwks()

    def post(self, url, body, headers):
        assert url == f"{ISS}/v1/partner-tokens/introspect"
        self.introspect_calls += 1
        claims = jwt.decode(body["token"], options={"verify_signature": False})
        return {"active": claims["jti"] not in self.revoked, "sub": claims["sub"], "cap": claims["cap"],
                "aud": claims["aud"], "exp": claims["exp"]}


@pytest.fixture()
def world(monkeypatch):
    monkeypatch.delenv("SCRIBASE_PARTNER_ISSUER", raising=False)
    monkeypatch.delenv("SCRIBASE_PARTNER_JWKS_URL", raising=False)
    monkeypatch.delenv("SCRIBASE_PARTNER_INTROSPECT_URL", raising=False)
    keys = _Keys()
    scribase = _Scribase(keys)
    clock = {"t": NOW}
    verifier = st.ScribaseTokenVerifier(fetch_json=scribase.fetch, post_json=scribase.post, clock=lambda: clock["t"])
    return keys, scribase, verifier, clock


def _verify(verifier, token):
    return verifier.verify(token, audience="menivor", capability="launch-video")


def test_valid_token_verifies(world):
    keys, _s, verifier, _c = world
    claims = _verify(verifier, keys.token())
    assert (claims.audience, claims.capability, claims.project_id, claims.org_id) == (
        "menivor", "launch-video", "proj_1", "org_1")


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"aud": "rally"}, "wrong_audience"),
        ({"cap": "mail"}, "wrong_capability"),
        ({"exp": int(NOW) - 3600, "iat": int(NOW) - 7200}, "expired"),
        ({"iss": "https://evil.example"}, "wrong_issuer"),
        ({"exp": int(NOW) + 91 * 86400}, "lifetime_too_long"),
        ({"_kid": "unknown"}, "unknown_key"),
    ],
)
def test_bad_tokens_are_refused(world, over, code):
    keys, _s, verifier, _c = world
    with pytest.raises(st.PartnerTokenError) as exc:
        _verify(verifier, keys.token(**over))
    assert exc.value.code == code


def test_wrong_signing_key_and_algorithm_are_refused(world):
    keys, _s, verifier, _c = world
    other = Ed25519PrivateKey.generate()
    forged = jwt.encode({"iss": ISS, "aud": "menivor", "sub": "p", "cap": "launch-video", "jti": "j",
                         "iat": int(NOW), "exp": int(NOW) + 60}, other, algorithm="EdDSA",
                        headers={"kid": keys.kid})
    with pytest.raises(st.PartnerTokenError) as exc:
        _verify(verifier, forged)
    assert exc.value.code == "invalid"
    hs = jwt.encode({"iss": ISS}, "secret-secret-secret-secret-secret", algorithm="HS256", headers={"kid": "k1"})
    with pytest.raises(st.PartnerTokenError) as exc:
        _verify(verifier, hs)
    assert exc.value.code == "bad_algorithm"


def test_revoked_token_is_refused_within_60_seconds(world):
    keys, scribase, verifier, clock = world
    token = keys.token()
    _verify(verifier, token)
    scribase.revoked.add("jti_1")
    clock["t"] = NOW + 30
    _verify(verifier, token)  # cached "active" answer, still inside 60 s
    assert scribase.introspect_calls == 1
    clock["t"] = NOW + 61
    with pytest.raises(st.PartnerTokenError) as exc:
        _verify(verifier, token)
    assert exc.value.code == "revoked"
    assert scribase.introspect_calls == 2


def test_jwks_is_cached_for_ten_minutes_and_refetched_on_rotation(world):
    keys, scribase, verifier, clock = world
    _verify(verifier, keys.token())
    _verify(verifier, keys.token(jti="jti_2"))
    assert scribase.jwks_calls == 1
    keys.active, keys.kid = Ed25519PrivateKey.generate(), "k2"  # rotation
    _verify(verifier, keys.token(jti="jti_3"))
    assert scribase.jwks_calls == 2
    clock["t"] = NOW + 601
    _verify(verifier, keys.token(jti="jti_4", iat=int(NOW) + 500, exp=int(NOW) + 5000))
    assert scribase.jwks_calls == 3


def test_introspection_outage_fails_closed(world):
    keys, _s, _v, clock = world

    def down(*_a):
        raise OSError("down")

    verifier = st.ScribaseTokenVerifier(fetch_json=_s.fetch, post_json=down, clock=lambda: clock["t"])
    with pytest.raises(st.PartnerTokenError) as exc:
        _verify(verifier, keys.token())
    assert exc.value.status_code == 503


# --------------------------------------------------------------------------- #
# Draft brief + source=scribase in the funnel read-out (M-4)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def factory(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
                           future=True)
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

    monkeypatch.setattr(db_base, "get_session", _session)
    monkeypatch.setattr(lv, "get_session", _session)
    import app.controllers.v1.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "get_session", _session)
    with maker() as s:
        u = User(email="typed@example.com", api_key_hash=hashlib.sha256(API_KEY.encode()).hexdigest())
        s.add(u)
        s.commit()
    return maker


def _client(monkeypatch, verifier) -> TestClient:
    import app.services.ratelimit as ratelimit

    monkeypatch.setattr(st, "default_verifier", lambda: verifier)
    # Hermetic: the real limiter counts in the local Redis across test runs.
    limited: list[str] = []
    monkeypatch.setattr(ratelimit, "enforce_rate_limit", lambda request, bucket, limit, window: limited.append(bucket))
    app = FastAPI()
    app.include_router(lv.router)

    def handler(_request, exc: HttpException):
        return JSONResponse(status_code=exc.status_code,
                            content=utils.get_response(exc.status_code, exc.data, exc.message))

    app.add_exception_handler(HttpException, handler)
    return TestClient(app)


def test_valid_token_prefills_a_draft_and_records_scribase(world, factory, monkeypatch):
    keys, _s, verifier, _c = world
    client = _client(monkeypatch, verifier)
    res = client.post(
        "/api/v1/partners/launch-video",
        json={"token": keys.token(), "app_url": "https://myapp.example/", "app_name": "My App"},
        headers={"x-api-key": API_KEY},
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["create_url"] == "/create?q=https%3A%2F%2Fmyapp.example%2F"
    assert data["topic"] == "Launch video for My App" and data["source"] == "scribase"
    with factory() as s:
        rows = readout.readout(s, since=readout.DEFAULT_SINCE.replace(year=2000))
        assert [r.source for r in rows] == ["scribase"]
        assert rows[0].utm_campaign == "launch-video"
        # Only what the user typed crosses products: no project or org id is stored.
        audit_rows = list(s.execute(select(AuditLog).where(AuditLog.action == "partner.launch_video_draft")).scalars())
        assert len(audit_rows) == 1
        stored = json.dumps([[r.meta, r.target_id] for r in audit_rows])
        assert "proj_1" not in stored and "org_1" not in stored
        assert audit_rows[0].meta["app_url"] == "https://myapp.example/"
        attr = s.get(FunnelAttribution, rows[0].user_id)
        assert "proj_1" not in json.dumps({c: getattr(attr, c) for c in ("source", "utm_source", "referrer")})


@pytest.mark.parametrize(
    ("over", "status"),
    [({"aud": "railyard"}, 403), ({"cap": "deploy"}, 403), ({"exp": int(NOW) - 100, "iat": int(NOW) - 1000}, 401)],
)
def test_refused_tokens_create_no_draft_and_no_source(world, factory, monkeypatch, over, status):
    keys, _s, verifier, _c = world
    client = _client(monkeypatch, verifier)
    res = client.post("/api/v1/partners/launch-video",
                      json={"token": keys.token(**over), "app_url": "https://myapp.example/"},
                      headers={"x-api-key": API_KEY})
    assert res.status_code == status
    with factory() as s:
        assert s.execute(select(FunnelAttribution)).first() is None


def test_bad_app_url_is_422(world, factory, monkeypatch):
    keys, _s, verifier, _c = world
    client = _client(monkeypatch, verifier)
    res = client.post("/api/v1/partners/launch-video",
                      json={"token": keys.token(), "app_url": "javascript:alert(1)"},
                      headers={"x-api-key": API_KEY})
    assert res.status_code == 422


def test_route_is_mounted_and_public_in_allowlist():
    from fastapi.routing import APIRoute

    from app.core import api_surface as surf
    from app.router import build_full_router

    paths = {r.path for r in build_full_router().routes if isinstance(r, APIRoute)}
    assert "/api/v1/partners/launch-video" in paths
    assert "POST /api/v1/partners/launch-video" in surf.load_allowlist()


def test_unknown_kids_cannot_force_a_jwks_fetch_per_request(world):
    """Wave E verifier: forged tokens with random kids refetch at most every 30 s."""
    keys, scribase, verifier, clock = world
    _verify(verifier, keys.token())
    assert scribase.jwks_calls == 1
    for i in range(5):
        with pytest.raises(st.PartnerTokenError):
            _verify(verifier, keys.token(_kid=f"random-{i}"))
    assert scribase.jwks_calls == 2
    clock["t"] = NOW + st.KID_MISS_REFETCH_S
    with pytest.raises(st.PartnerTokenError):
        _verify(verifier, keys.token(_kid="random-late"))
    assert scribase.jwks_calls == 3
