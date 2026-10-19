"""MV-SEO1 / LIVE-QA M-1: the API host root points at menivor.com, not the upstream page."""

from __future__ import annotations

import os

from starlette.applications import Starlette
from starlette.staticfiles import StaticFiles
from starlette.testclient import TestClient

PUBLIC = os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api", "assets", "resource", "public")


def _root_html() -> str:
    app = Starlette()
    app.mount("/", StaticFiles(directory=PUBLIC, html=True), name="")
    response = TestClient(app).get("/")
    assert response.status_code == 200
    return response.text


def test_root_redirects_to_menivor() -> None:
    html = _root_html()
    assert '<meta http-equiv="refresh" content="0; url=https://menivor.com/">' in html
    assert 'href="https://menivor.com/"' in html
    assert "<title>Menivor API</title>" in html
    assert 'content="noindex"' in html


def test_root_carries_no_upstream_branding() -> None:
    html = _root_html()
    assert "MoneyPrinterTurbo" not in html
    assert "github.com" not in html
    assert not any("一" <= ch <= "鿿" for ch in html), "no untranslated upstream copy"
