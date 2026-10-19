"""Brand Agent web search through a self-hosted SearXNG configured by ``SEARXNG_URL``."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from app.domains.brand_agent.ports import search

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture()
def clean_env(monkeypatch):
    monkeypatch.delenv(search.ENV, raising=False)
    monkeypatch.delenv(search.SEARXNG_URL_ENV, raising=False)
    return monkeypatch


@pytest.fixture()
def searx_server():
    """A local stand-in for SearXNG's JSON API (127.0.0.1, like a private box address)."""
    seen: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server API
            parsed = urlparse(self.path)
            seen.append({"path": parsed.path, "query": parse_qs(parsed.query), "accept": self.headers["Accept"]})
            if parsed.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "http://example.com/")
                self.end_headers()
                return
            body = json.dumps({"results": [
                {"title": "Neon <b>Serverless</b> Postgres", "url": "https://neon.tech/", "content": "Scale to zero."},
                {"title": "Supabase", "url": "https://supabase.com/", "content": "Postgres platform"},
                {"title": "bad", "url": "javascript:alert(1)", "content": ""},
            ]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", seen
    server.shutdown()


def test_searxng_url_alone_turns_search_on(clean_env):
    clean_env.setenv(search.SEARXNG_URL_ENV, "http://searxng:8080/")
    port = search.get_port()
    assert isinstance(port, search.SearxngSearch) and port.base_url == "http://searxng:8080"


def test_explicit_choices_win(clean_env):
    clean_env.setenv(search.SEARXNG_URL_ENV, "http://searxng:8080")
    clean_env.setenv(search.ENV, "none")
    assert isinstance(search.get_port(), search.NoSearch)
    clean_env.setenv(search.ENV, "searxng")
    assert search.get_port().base_url == "http://searxng:8080"
    clean_env.setenv(search.ENV, "searxng:https://searx.other")
    assert search.get_port().base_url == "https://searx.other"
    clean_env.setenv(search.ENV, "duckduckgo")
    assert isinstance(search.get_port(), search.DuckDuckGoSearch)


def test_bad_searxng_url_keeps_search_off(clean_env):
    clean_env.setenv(search.SEARXNG_URL_ENV, "file:///etc/passwd")
    assert isinstance(search.get_port(), search.NoSearch)
    clean_env.setenv(search.ENV, "searxng")
    clean_env.delenv(search.SEARXNG_URL_ENV)
    assert isinstance(search.get_port(), search.NoSearch)


def test_searches_a_private_searxng_over_http(clean_env, searx_server):
    base, seen = searx_server
    clean_env.setenv(search.SEARXNG_URL_ENV, base)
    results = search.get_port().search("postgres backend competitors", limit=5)
    assert results == [
        {"title": "Neon Serverless Postgres", "url": "https://neon.tech/", "snippet": "Scale to zero."},
        {"title": "Supabase", "url": "https://supabase.com/", "snippet": "Postgres platform"},
    ]
    assert seen[0]["path"] == "/search" and seen[0]["query"]["format"] == ["json"]
    assert seen[0]["query"]["q"] == ["postgres backend competitors"] and seen[0]["accept"] == "application/json"


def test_redirects_and_oversize_bodies_are_refused(searx_server, monkeypatch):
    base, _ = searx_server
    with pytest.raises(Exception):
        search.operator_get(f"{base}/redirect")
    monkeypatch.setattr(search, "SEARXNG_MAX_BYTES", 10)
    with pytest.raises(ValueError):
        search.operator_get(f"{base}/search?q=x&format=json")


def test_unreachable_searxng_returns_no_results(clean_env):
    clean_env.setenv(search.SEARXNG_URL_ENV, "http://127.0.0.1:9")
    assert search.get_port().search("anything") == []


def test_compose_service_enables_the_json_api_and_stays_private():
    fragment = (REPO / "deploy" / "searxng" / "compose.fragment.yml").read_text()
    settings = (REPO / "deploy" / "searxng" / "settings.yml").read_text()
    assert "searxng/searxng" in fragment and "127.0.0.1:8888:8080" in fragment
    assert "SEARXNG_SECRET" in fragment and "mem_limit" in fragment
    assert "- json" in settings and "limiter: false" in settings and "public_instance: false" in settings
