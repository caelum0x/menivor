"""Cover / Thumbnail Generator API tests.

Covers the two ReelForge cover surfaces with no external I/O (R2 + Pillow
rendering monkeypatched, Postgres replaced by in-memory SQLite):

* ``app.controllers.v1.covers`` — ``POST /jobs/{job_id}/cover`` happy path
  (renders, uploads, persists ``cover_key``, returns a presigned ``cover_url``),
  ownership (foreign job -> 404), unknown style (-> 400) and auth (-> 401).
* ``app.controllers.v1.catalog`` — ``GET /catalog/cover-styles`` lists the
  bundled style presets.

All exercised via a FastAPI ``TestClient`` over in-memory SQLite.
"""

from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.controllers.v1.covers as covers_mod
import app.services.cover as cover_svc
from app.models.db.base import Base
from app.models.db.models import Job, User
from app.models.db.repositories import JobRepository
from app.models.exception import HttpException
from app.utils import utils

_API_KEY = "cover-key"
_KEY_HASH = hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}


# =========================================================================== #
# Fakes
# =========================================================================== #
class _FakeR2:
    """Captures ``upload_file`` and returns deterministic presigned URLs."""

    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, str | None]] = []

    def upload_file(self, local_path: str, key: str, content_type=None) -> str:
        self.uploads.append((local_path, key, content_type))
        return f"https://cdn.example.com/{key}"

    def presign_get(self, key: str, *a, **k) -> str:
        return f"https://cdn.example.com/{key}?get=1"

    def presign_result_get(self, key: str, *a, **k) -> str:
        return f"https://cdn.example.com/{key}?signed=1"


# =========================================================================== #
# Fixtures
# =========================================================================== #
@pytest.fixture()
def db_factory():
    """In-memory SQLite engine + session factory with the schema created."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )
    return Factory


def _make_user(Factory, email="cover@example.com") -> str:
    with Factory() as s:
        u = User(email=email, api_key_hash=_KEY_HASH, credits=0)
        s.add(u)
        s.flush()
        uid = u.id
        s.commit()
    return uid


def _make_job(
    Factory,
    user_id: str,
    *,
    script: str = "",
    poster_key: str = "",
    video_subject: str = "cats",
) -> str:
    with Factory() as s:
        job = JobRepository(s).create(
            user_id=user_id,
            kind="avatar_reel",
            params={"video_subject": video_subject},
        )
        job.script = script
        job.poster_key = poster_key
        jid = job.id
        s.commit()
    return jid


@pytest.fixture()
def cover_client(monkeypatch, db_factory):
    """FastAPI TestClient wired to the covers + catalog routers over SQLite."""
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

    # The covers module imported get_session into its own namespace.
    monkeypatch.setattr(covers_mod, "get_session", _fake_get_session)

    # Fake R2 (no boto3 / network). covers.py imports get_r2_client lazily.
    fake_r2 = _FakeR2()
    monkeypatch.setattr(
        "app.services.storage.r2.get_r2_client", lambda: fake_r2
    )

    # Deterministic render: write a tiny stand-in file instead of a real JPG so
    # the test does not depend on Pillow (which the renderer would otherwise use).
    def _fake_generate_cover(headline, out_path, *, base_image_path=None, style="classic"):
        captured["headline"] = headline
        captured["base_image_path"] = base_image_path
        captured["style"] = style
        with open(out_path, "wb") as fh:
            fh.write(b"fake-jpeg-bytes")
        return out_path

    captured: dict = {}
    monkeypatch.setattr(cover_svc, "generate_cover", _fake_generate_cover)

    app = FastAPI()
    import app.controllers.v1.catalog as catalog_mod

    app.include_router(covers_mod.router)
    app.include_router(catalog_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory, fake_r2, captured


# =========================================================================== #
# POST /jobs/{job_id}/cover
# =========================================================================== #
def test_generate_cover_owned_job_persists_and_returns_url(cover_client):
    client, Factory, fake_r2, captured = cover_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid, script="This one weird trick\nSegment.\nCTA.")

    resp = client.post(
        f"/api/v1/jobs/{jid}/cover",
        json={"style": "sunset"},
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    expected_key = f"jobs/{jid}/cover.jpg"
    assert data["cover_key"] == expected_key
    assert data["style"] == "sunset"
    assert data["cover_url"] == f"https://cdn.example.com/{expected_key}?signed=1"

    # Rendered with the derived hook (first script line) and chosen style; no
    # poster -> gradient background (base_image_path is None).
    assert captured["headline"] == "This one weird trick"
    assert captured["style"] == "sunset"
    assert captured["base_image_path"] is None

    # Uploaded exactly once as image/jpeg under the job cover key.
    assert len(fake_r2.uploads) == 1
    assert fake_r2.uploads[0][1] == expected_key
    assert fake_r2.uploads[0][2] == "image/jpeg"

    # cover_key persisted on the job.
    with Factory() as s:
        job = s.get(Job, jid)
        assert job.cover_key == expected_key


def test_generate_cover_explicit_headline_overrides_hook(cover_client):
    client, Factory, fake_r2, captured = cover_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid, script="ignored hook line", video_subject="cats")

    resp = client.post(
        f"/api/v1/jobs/{jid}/cover",
        json={"headline": "Custom Headline"},
        headers=_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert captured["headline"] == "Custom Headline"
    # Omitted style falls back to the default preset.
    assert resp.json()["data"]["style"] == cover_svc.DEFAULT_STYLE_ID


def test_generate_cover_auto_selects_winner_and_surfaces_ranking(
    monkeypatch, cover_client
):
    """With no explicit style, the cover ranker's winner is rendered and the full
    ranked list is surfaced in the response (the LIVE auto-pick path)."""
    client, Factory, fake_r2, captured = cover_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid, script="A great hook line", video_subject="coffee")

    recommendation = cover_svc.CoverRecommendation(
        recommended_style="sunset",
        degraded=False,
        note="",
        ranked=[
            cover_svc.RankedCover(
                id="sunset",
                name="Sunset",
                composite=1.5,
                stop_power=1.0,
                legibility=1.0,
                is_generic=0.0,
                primary_mood="warm_emotional",
                scored=True,
            ),
            cover_svc.RankedCover(
                id="classic",
                name="Classic",
                composite=0.8,
                stop_power=0.6,
                legibility=0.7,
                is_generic=0.2,
                primary_mood="premium_minimal",
                scored=True,
            ),
        ],
    )

    seen: dict = {}

    def _fake_recommend(headline, *, has_poster=False, topic="", **_kw):
        seen["headline"] = headline
        seen["has_poster"] = has_poster
        seen["topic"] = topic
        return recommendation

    monkeypatch.setattr(cover_svc, "recommend_cover", _fake_recommend)

    resp = client.post(f"/api/v1/jobs/{jid}/cover", json={}, headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    # Auto-picked the ranker's winner and rendered exactly that style.
    assert data["style"] == "sunset"
    assert captured["style"] == "sunset"
    assert data["auto_selected"] is True

    # Ranked on the derived hook line, no poster on this job, topic = subject.
    assert seen["headline"] == "A great hook line"
    assert seen["has_poster"] is False
    assert seen["topic"] == "coffee"

    # The whole ranked list is surfaced, winner first, with its composite.
    rec = data["recommendation"]
    assert rec["recommended_style"] == "sunset"
    assert rec["degraded"] is False
    assert [entry["id"] for entry in rec["ranked"]] == ["sunset", "classic"]
    assert rec["ranked"][0]["composite"] == 1.5
    assert rec["ranked"][0]["scored"] is True


def test_generate_cover_degraded_ranker_uses_default_and_flags_it(
    monkeypatch, cover_client
):
    """No TYPESAFE_API_KEY: the ranker degrades, so the default style is rendered,
    ``auto_selected`` is False and the recommendation is flagged ``degraded``."""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("typesafe_api_key", raising=False)
    client, Factory, fake_r2, captured = cover_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid, script="Some hook", video_subject="coffee")

    resp = client.post(f"/api/v1/jobs/{jid}/cover", json={}, headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    # Deterministic default, not auto-picked.
    assert data["style"] == cover_svc.DEFAULT_STYLE_ID
    assert captured["style"] == cover_svc.DEFAULT_STYLE_ID
    assert data["auto_selected"] is False

    # Recommendation is present but flagged degraded (pass-through, unscored).
    rec = data["recommendation"]
    assert rec["degraded"] is True
    assert rec["recommended_style"] == cover_svc.DEFAULT_STYLE_ID
    assert all(entry["scored"] is False for entry in rec["ranked"])


def test_generate_cover_explicit_style_still_surfaces_ranking(
    monkeypatch, cover_client
):
    """An explicit style is honored verbatim (not auto-selected) but the ranked
    recommendation is still surfaced so the UI can show a better option."""
    client, Factory, fake_r2, captured = cover_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid, script="A great hook line")

    recommendation = cover_svc.CoverRecommendation(
        recommended_style="sunset",
        degraded=False,
        note="",
        ranked=[
            cover_svc.RankedCover(
                id="sunset",
                name="Sunset",
                composite=1.5,
                stop_power=1.0,
                legibility=1.0,
                is_generic=0.0,
                primary_mood="warm_emotional",
                scored=True,
            ),
        ],
    )
    monkeypatch.setattr(
        cover_svc, "recommend_cover", lambda *a, **k: recommendation
    )

    resp = client.post(
        f"/api/v1/jobs/{jid}/cover", json={"style": "classic"}, headers=_HEADERS
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    # Explicit style wins the render; it was not auto-selected.
    assert data["style"] == "classic"
    assert captured["style"] == "classic"
    assert data["auto_selected"] is False
    # But the ranker's recommendation is still exposed.
    assert data["recommendation"]["recommended_style"] == "sunset"


def test_generate_cover_derives_headline_from_video_subject(cover_client):
    client, Factory, fake_r2, captured = cover_client
    uid = _make_user(Factory)
    # No script -> fall back to the video_subject param.
    jid = _make_job(Factory, uid, script="", video_subject="Best coffee in town")

    resp = client.post(
        f"/api/v1/jobs/{jid}/cover", json={}, headers=_HEADERS
    )
    assert resp.status_code == 200, resp.text
    assert captured["headline"] == "Best coffee in town"


def test_generate_cover_with_poster_downloads_base(monkeypatch, cover_client):
    client, Factory, fake_r2, captured = cover_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid, script="Hook!", poster_key="jobs/x/poster.jpg")

    # Stub the poster download so no network is hit; it writes a stand-in file.
    def _fake_download(poster_key, dest_path, request_id):
        with open(dest_path, "wb") as fh:
            fh.write(b"poster-bytes")

    monkeypatch.setattr(covers_mod, "_download_poster", _fake_download)

    resp = client.post(
        f"/api/v1/jobs/{jid}/cover", json={"style": "classic"}, headers=_HEADERS
    )
    assert resp.status_code == 200, resp.text
    # The downloaded poster path was passed to the renderer as the base image.
    assert captured["base_image_path"] is not None
    assert os.path.basename(captured["base_image_path"]) == "poster"


def test_generate_cover_poster_download_failure_degrades_to_gradient(
    monkeypatch, cover_client
):
    client, Factory, fake_r2, captured = cover_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid, script="Hook!", poster_key="jobs/x/poster.jpg")

    def _boom(poster_key, dest_path, request_id):
        raise RuntimeError("r2 down")

    monkeypatch.setattr(covers_mod, "_download_poster", _boom)

    resp = client.post(
        f"/api/v1/jobs/{jid}/cover", json={}, headers=_HEADERS
    )
    # Download failure is non-fatal: renders the gradient instead.
    assert resp.status_code == 200, resp.text
    assert captured["base_image_path"] is None


def test_generate_cover_unknown_style_400(cover_client):
    client, Factory, fake_r2, captured = cover_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid)

    resp = client.post(
        f"/api/v1/jobs/{jid}/cover",
        json={"style": "does-not-exist"},
        headers=_HEADERS,
    )
    assert resp.status_code == 400, resp.text
    # Nothing was rendered or uploaded for a rejected style.
    assert fake_r2.uploads == []


def test_generate_cover_foreign_job_404(cover_client):
    client, Factory, fake_r2, captured = cover_client
    # Job owned by a DIFFERENT user.
    other_hash = hashlib.sha256(b"otherkey").hexdigest()
    with Factory() as s:
        owner = User(email="owner@x.com", api_key_hash=other_hash)
        s.add(owner)
        s.flush()
        job = JobRepository(s).create(user_id=owner.id, kind="avatar_reel", params={})
        jid = job.id
        s.commit()
    _make_user(Factory, email="caller@x.com")  # the x-api-key caller

    resp = client.post(
        f"/api/v1/jobs/{jid}/cover", json={}, headers=_HEADERS
    )
    assert resp.status_code == 404, resp.text  # ownership enforced, no leak
    assert fake_r2.uploads == []


def test_generate_cover_requires_auth(cover_client):
    client, Factory, fake_r2, captured = cover_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid)

    resp = client.post(f"/api/v1/jobs/{jid}/cover", json={})  # no x-api-key
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# _download_poster
# =========================================================================== #
def test_download_poster_uses_read_timeout(monkeypatch, tmp_path):
    """The poster download must pass a read timeout so a stalled R2 transfer
    cannot hold the worker thread open forever."""

    class _FakeResponse:
        def __init__(self) -> None:
            self._served = False

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, _size):
            if self._served:
                return b""
            self._served = True
            return b"poster-bytes"

    captured: dict = {}

    def _fake_urlopen(url, *args, **kwargs):
        captured["url"] = url
        captured["timeout"] = kwargs.get("timeout")
        return _FakeResponse()

    monkeypatch.setattr(
        "app.services.storage.r2.get_r2_client", lambda: _FakeR2()
    )
    monkeypatch.setattr(covers_mod.urllib.request, "urlopen", _fake_urlopen)

    dest = tmp_path / "poster"
    covers_mod._download_poster("jobs/x/poster.jpg", str(dest), "req-1")

    # A finite timeout was supplied (default is None == infinite).
    assert captured["timeout"] == 30
    assert dest.read_bytes() == b"poster-bytes"


# =========================================================================== #
# GET /catalog/cover-styles
# =========================================================================== #
def test_cover_styles_catalog_lists_styles(cover_client):
    client, Factory, fake_r2, captured = cover_client

    resp = client.get("/api/v1/catalog/cover-styles")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    ids = {entry["id"] for entry in data}
    # The bundled presets are exposed with id + name.
    assert {"classic", "sunset", "bold_yellow", "minimal"} <= ids
    assert all("name" in entry for entry in data)
