"""URL → reel — pure extraction/draft + service (injected fetcher) + endpoint."""

from __future__ import annotations

import hashlib
import importlib
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.domains.ingest.draft import build_reel_draft
from app.domains.ingest.extract import extract_content
from app.domains.ingest.service import IngestError, IngestService
from app.models.db.base import Base
from app.models.db.models import User
from app.models.exception import HttpException
from app.utils import utils

ingest_mod = importlib.import_module("app.domains.ingest.router")

_HTML = """
<html><head>
  <title>Acme Focus — the calm to-do app</title>
  <meta name="description" content="Acme Focus helps you finish deep work without burnout.">
  <meta property="og:title" content="Acme Focus">
</head><body>
  <h1>Acme Focus</h1>
  <ul>
    <li>One task at a time</li>
    <li>Automatic focus timers</li>
    <li>Calm, distraction-free UI</li>
    <li>One task at a time</li>
  </ul>
</body></html>
"""


# --------------------------------------------------------------------------- #
# Pure extraction + draft
# --------------------------------------------------------------------------- #
def test_extract_content_from_html():
    c = extract_content(_HTML, "https://acme.example")
    # og:title wins for title.
    assert c["title"] == "Acme Focus"
    assert "deep work" in c["description"]
    # <li> features, deduped.
    assert "One task at a time" in c["features"]
    assert c["features"].count("One task at a time") == 1


def test_extract_plain_text():
    c = extract_content("My Product\nIt does a thing.\nAnd another.")
    assert c["title"] == "My Product"
    assert "does a thing" in c["description"]


def test_build_reel_draft_shape():
    c = extract_content(_HTML)
    draft = build_reel_draft(c)
    assert draft["video_subject"] == "Acme Focus"
    assert draft["hook"].startswith("POV:")
    assert "Check the link" in draft["video_script"]
    # b-roll prompts derived from title + features.
    assert any("hero shot" in p for p in draft["broll_prompts"])


# --------------------------------------------------------------------------- #
# Service (injected fetcher)
# --------------------------------------------------------------------------- #
def test_url_to_reel_with_fake_fetcher():
    result = IngestService().url_to_reel(
        "https://acme.example/product", fetcher=lambda _u: _HTML
    )
    assert result["reel_draft"]["video_subject"] == "Acme Focus"
    assert result["content"]["features"]


def test_url_to_reel_rejects_bad_url():
    with pytest.raises(IngestError) as ei:
        IngestService().url_to_reel("ftp://nope", fetcher=lambda _u: _HTML)
    assert ei.value.status_code == 400


def test_url_to_reel_empty_page_422():
    with pytest.raises(IngestError) as ei:
        IngestService().url_to_reel("https://x.example", fetcher=lambda _u: "<html></html>")
    assert ei.value.status_code == 422


def test_url_to_reel_rewriter_polish():
    def _rewriter(draft, content):
        return {"video_subject": "REWRITTEN"}

    result = IngestService().url_to_reel(
        "https://x.example", fetcher=lambda _u: _HTML, rewriter=_rewriter
    )
    assert result["reel_draft"]["video_subject"] == "REWRITTEN"
    assert result["reel_draft"]["video_script"]  # other fields preserved


# --------------------------------------------------------------------------- #
# Endpoint (fetcher patched to avoid network)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def client(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool, future=True,
    )
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with Factory() as s:
        s.add(User(email="a@example.com", api_key_hash=hashlib.sha256(b"k").hexdigest()))
        s.commit()

    @contextmanager
    def _gs():
        s = Factory()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr(ingest_mod, "get_session", _gs)
    monkeypatch.setattr(ingest_mod, "_DB_IMPORT_ERROR", None)
    # Patch the default network fetch to return canned HTML (no recursion).
    import app.domains.ingest.service as ingest_service

    monkeypatch.setattr(ingest_service, "_default_fetch", lambda _u: _HTML)

    app = FastAPI()
    app.include_router(ingest_mod.router)

    def _http_handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app)


def test_ingest_endpoint(client):
    resp = client.post(
        "/api/v1/ingest/url", json={"url": "https://acme.example"},
        headers={"x-api-key": "k"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["reel_draft"]["video_subject"] == "Acme Focus"


def test_ingest_endpoint_records_first_link_once(client):
    """Funnel: a pasted link is the "first link pasted" step, recorded once per user."""
    from sqlalchemy import select

    from app.models.db.funnel import FunnelEvent

    for _ in range(2):
        resp = client.post(
            "/api/v1/ingest/url", json={"url": "https://acme.example"},
            headers={"x-api-key": "k"},
        )
        assert resp.status_code == 200, resp.text
    with ingest_mod.get_session() as s:
        steps = [e.step for e in s.execute(select(FunnelEvent)).scalars()]
    assert steps == ["first_link"]


def test_ingest_endpoint_requires_auth(client):
    resp = client.post("/api/v1/ingest/url", json={"url": "https://acme.example"})
    assert resp.status_code == 401


_HEAD_SCRIPT_HTML = """
<html><head>
  <title>Scribase: hosted Postgres with Auth, Storage and branching</title>
  <link rel="icon" href="/favicon.ico">
  <script>(function(){try{var t=localStorage.getItem('scribase-theme');}catch(e){}})()</script>
  <style>li{color:red}</style>
</head><body>
  <nav><ul><li><a href="/pricing">Pricing</a></li><li>MCP server</li></ul></nav>
  <main><ul><li>Postgres, Auth and Storage in every project</li><li>Branch your database like Git</li></ul></main>
  <footer><ul><li>Privacy</li></ul></footer>
</body></html>
"""


def test_extract_ignores_link_tags_scripts_and_chrome():
    """`<link>` must not open a list item; scripts, nav and footer never become features."""
    out = extract_content(_HEAD_SCRIPT_HTML, "https://scribase.com")
    joined = " ".join(out["features"])
    assert "localStorage" not in joined and "function" not in joined
    assert out["features"] == ["Postgres, Auth and Storage in every project", "Branch your database like Git"]
