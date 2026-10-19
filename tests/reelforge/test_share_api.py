"""Public Watermarked Share Pages API tests.

Covers ``app.controllers.v1.share`` — the owner-scoped create/revoke endpoints and
the PUBLIC (no-auth) share-page read:

* ``POST   /jobs/{job_id}/share`` — owner-scoped create (401 without a key; 404 for
  a foreign/unknown job; idempotent — one live link per job).
* ``DELETE /me/shares/{token}``   — owner-scoped revoke (a foreign token is a
  harmless no-op, never a confirmation; a revoked link then 404s on the public
  read).
* ``GET    /public/r/{token}``    — PUBLIC: works with NO auth, returns ONLY the
  safe DTO (title + watermarked preview URL + created_at + sharer referral code),
  increments the view, and LEAKS NOTHING private (no clean ``result_key``, no
  ``user_id``, no credits/cost/revenue, not even ``view_count``). Unknown/revoked
  token → 404.

No external I/O: Postgres is replaced by an in-memory SQLite DB behind a
``TestClient`` and R2 presigning is monkeypatched, mirroring
``tests/reelforge/test_marketplace_api.py``.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.controllers.v1.share as share_mod
from app.models.db.base import Base
from app.models.db.models import Job, ShareLink, User
from app.models.exception import HttpException
from app.services import share as share_service
from app.utils import utils

_API_KEY = "share-key"
_KEY_HASH = hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}

_OTHER_KEY = "other-key"
_OTHER_HASH = hashlib.sha256(_OTHER_KEY.encode("utf-8")).hexdigest()
_OTHER_HEADERS = {"x-api-key": _OTHER_KEY}

_FAKE_PRESIGNED = "https://r2.example.com/PRESIGNED-watermarked-preview?sig=abc"
_CLEAN_RESULT_KEY = "jobs/SECRET/final-clean.mp4"


# =========================================================================== #
# Fixtures
# =========================================================================== #
@pytest.fixture()
def db_factory():
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


def _make_user(Factory, email="author@example.com", key_hash=_KEY_HASH) -> str:
    with Factory() as s:
        u = User(email=email, api_key_hash=key_hash, credits=7)
        s.add(u)
        s.flush()
        uid = u.id
        s.commit()
    return uid


def _make_job(
    Factory,
    user_id: str,
    *,
    preview_key="jobs/j1/preview.mp4",
    result_key=_CLEAN_RESULT_KEY,
    params=None,
) -> str:
    with Factory() as s:
        job = Job(
            user_id=user_id,
            result_key=result_key,
            preview_key=preview_key,
            params=params or {"title": "My great reel"},
        )
        s.add(job)
        s.flush()
        jid = job.id
        s.commit()
    return jid


@pytest.fixture()
def share_client(monkeypatch, db_factory):
    """FastAPI TestClient wired to the share router + in-memory SQLite.

    R2 presigning is monkeypatched to a fixed fake URL so the public read never
    touches boto3/network. Returns ``(client, Factory)``.
    """
    Factory = db_factory

    @contextmanager
    def _fake_get_session():
        session = Factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(share_mod, "get_session", _fake_get_session)
    # Paid-access checks (app.services.user_entitlements) read the ledger and
    # plan rows through the shared session factory: point it at this DB too.
    import app.models.db.base as db_base

    monkeypatch.setattr(db_base, "get_session", _fake_get_session)
    # share.py gates on ``pro_access.require_pro_action``, which resolves
    # ``revenuecat_client.require_pro_entitlement`` at call time. Patch that
    # single seam to grant Pro (the old ``share.revenuecat_service`` attribute
    # was removed when the gate moved to pro_access).
    from app.services.billing import revenuecat_client

    monkeypatch.setattr(
        revenuecat_client, "require_pro_entitlement", lambda *_a, **_k: None
    )
    # Never hit R2: presign a fixed fake URL for any safe preview key.
    monkeypatch.setattr(share_service, "_default_presign", lambda key: _FAKE_PRESIGNED)

    app = FastAPI()
    app.include_router(share_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


# =========================================================================== #
# POST /jobs/{job_id}/share  (owner-scoped create)
# =========================================================================== #
def test_create_requires_auth_401(share_client):
    client, Factory = share_client
    author = _make_user(Factory)
    jid = _make_job(Factory, author)
    resp = client.post(f"/api/v1/jobs/{jid}/share")  # no key
    assert resp.status_code == 401, resp.text


def test_create_share_happy_path(share_client):
    client, Factory = share_client
    author = _make_user(Factory)
    jid = _make_job(Factory, author)

    resp = client.post(f"/api/v1/jobs/{jid}/share", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["token"]
    assert data["url"].endswith(f"/r/{data['token']}")
    assert data["job_id"] == jid


def test_create_share_requires_active_pro(share_client, monkeypatch):
    client, Factory = share_client
    author = _make_user(Factory)
    jid = _make_job(Factory, author)

    from app.services.billing import revenuecat_client

    def _deny(*_a, **_k):
        raise revenuecat_client.RevenueCatAccessDenied("Pro required")

    monkeypatch.setattr(revenuecat_client, "require_pro_entitlement", _deny)
    resp = client.post(f"/api/v1/jobs/{jid}/share", headers=_HEADERS)
    assert resp.status_code == 402, resp.text
    with Factory() as s:
        assert s.query(ShareLink).count() == 0


def test_create_is_idempotent_one_live_link(share_client):
    client, Factory = share_client
    author = _make_user(Factory)
    jid = _make_job(Factory, author)

    first = client.post(f"/api/v1/jobs/{jid}/share", headers=_HEADERS)
    second = client.post(f"/api/v1/jobs/{jid}/share", headers=_HEADERS)
    assert first.json()["data"]["token"] == second.json()["data"]["token"]
    with Factory() as s:
        assert s.query(ShareLink).filter(ShareLink.job_id == jid).count() == 1


def test_create_foreign_job_404(share_client):
    client, Factory = share_client
    victim = _make_user(Factory, email="victim@x.com", key_hash=_OTHER_HASH)
    jid = _make_job(Factory, victim)
    _make_user(Factory)  # caller (default key)

    # A caller guessing another user's job id must get 404 (indistinguishable
    # from missing) and NO link is minted.
    resp = client.post(f"/api/v1/jobs/{jid}/share", headers=_HEADERS)
    assert resp.status_code == 404, resp.text
    with Factory() as s:
        assert s.query(ShareLink).count() == 0


def test_create_unknown_job_404(share_client):
    client, Factory = share_client
    _make_user(Factory)
    resp = client.post("/api/v1/jobs/does-not-exist/share", headers=_HEADERS)
    assert resp.status_code == 404, resp.text


# =========================================================================== #
# GET /public/r/{token}  (PUBLIC — no auth, leaks nothing private)
# =========================================================================== #
def _mint_token(client, jid) -> str:
    return client.post(f"/api/v1/jobs/{jid}/share", headers=_HEADERS).json()["data"][
        "token"
    ]


def test_public_view_works_without_auth(share_client):
    client, Factory = share_client
    author = _make_user(Factory)
    jid = _make_job(Factory, author, params={"title": "Reel of the year"})
    token = _mint_token(client, jid)

    # NO auth header at all.
    resp = client.get(f"/api/v1/public/r/{token}")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["title"] == "Reel of the year"
    assert data["watermarked_preview_url"] == _FAKE_PRESIGNED
    assert data["created_at"]
    assert data["sharer_referral_code"]  # safe public referral handle


def test_public_view_leaks_nothing_private(share_client):
    client, Factory = share_client
    author = _make_user(Factory)
    jid = _make_job(Factory, author, result_key=_CLEAN_RESULT_KEY)
    token = _mint_token(client, jid)

    resp = client.get(f"/api/v1/public/r/{token}")
    assert resp.status_code == 200, resp.text
    body = resp.text
    data = resp.json()["data"]

    # The safe DTO exposes EXACTLY the four safe keys — nothing else.
    assert set(data.keys()) == {
        "title",
        "watermarked_preview_url",
        "created_at",
        "sharer_referral_code",
    }
    # The clean result key must NEVER appear anywhere in the response.
    assert _CLEAN_RESULT_KEY not in body
    assert "result_key" not in body
    # No owning user id, no financials, not even the raw view counter.
    assert author not in body
    for leaked in ("user_id", "credits", "cost", "revenue", "view_count"):
        assert leaked not in body


def test_public_view_increments_view_count(share_client):
    client, Factory = share_client
    author = _make_user(Factory)
    jid = _make_job(Factory, author)
    token = _mint_token(client, jid)

    client.get(f"/api/v1/public/r/{token}")
    client.get(f"/api/v1/public/r/{token}")
    with Factory() as s:
        link = s.query(ShareLink).filter(ShareLink.token == token).one()
        assert link.view_count == 2


def test_public_view_unknown_token_404(share_client):
    client, Factory = share_client
    _make_user(Factory)
    resp = client.get("/api/v1/public/r/nope-nope-nope")
    assert resp.status_code == 404, resp.text


def test_public_view_no_preview_key_yields_empty_url(share_client):
    client, Factory = share_client
    author = _make_user(Factory)
    # A job with no derived preview/poster/cover keys never presigns anything and
    # never reaches for the clean result_key.
    jid = _make_job(Factory, author, preview_key="")
    token = _mint_token(client, jid)

    resp = client.get(f"/api/v1/public/r/{token}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["watermarked_preview_url"] == ""


# =========================================================================== #
# DELETE /me/shares/{token}  (owner-scoped revoke)
# =========================================================================== #
def test_revoke_then_public_404(share_client):
    client, Factory = share_client
    author = _make_user(Factory)
    jid = _make_job(Factory, author)
    token = _mint_token(client, jid)

    revoke = client.delete(f"/api/v1/me/shares/{token}", headers=_HEADERS)
    assert revoke.status_code == 200, revoke.text
    assert revoke.json()["data"]["revoked"] is True

    # A revoked link is invisible on the public read.
    assert client.get(f"/api/v1/public/r/{token}").status_code == 404


def test_revoke_foreign_token_is_noop_false(share_client):
    client, Factory = share_client
    author = _make_user(Factory)
    _make_user(Factory, email="stranger@x.com", key_hash=_OTHER_HASH)
    jid = _make_job(Factory, author)
    token = _mint_token(client, jid)

    # A stranger cannot revoke another creator's link — no-op False, and the link
    # still resolves publicly.
    resp = client.delete(f"/api/v1/me/shares/{token}", headers=_OTHER_HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["revoked"] is False
    assert client.get(f"/api/v1/public/r/{token}").status_code == 200


def test_revoke_requires_auth_401(share_client):
    client, Factory = share_client
    author = _make_user(Factory)
    jid = _make_job(Factory, author)
    token = _mint_token(client, jid)
    resp = client.delete(f"/api/v1/me/shares/{token}")
    assert resp.status_code == 401, resp.text
