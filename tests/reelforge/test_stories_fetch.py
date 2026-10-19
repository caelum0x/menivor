"""Unit: stories.fetch — URL normalization + guarded default_fetch (no network)."""

from __future__ import annotations

import httpx
import pytest

from app.domains.stories.fetch import (
    RedditFetchError,
    default_fetch,
    normalize_thread_url,
)


# --------------------------------------------------------------------------- #
# normalize_thread_url
# --------------------------------------------------------------------------- #
def test_normalize_appends_json():
    out = normalize_thread_url("https://www.reddit.com/r/AITA/comments/abc/title/")
    assert out == "https://www.reddit.com/r/AITA/comments/abc/title.json"


def test_normalize_keeps_existing_json_and_drops_query():
    out = normalize_thread_url("https://reddit.com/r/x/comments/abc/t.json?utm=1")
    assert out == "https://reddit.com/r/x/comments/abc/t.json"


def test_normalize_rejects_non_http_scheme():
    with pytest.raises(RedditFetchError) as ei:
        normalize_thread_url("ftp://reddit.com/r/x/comments/abc")
    assert ei.value.status_code == 400


def test_normalize_rejects_non_reddit_host():
    with pytest.raises(RedditFetchError) as ei:
        normalize_thread_url("https://evil.example/r/x/comments/abc")
    assert ei.value.status_code == 400


# --------------------------------------------------------------------------- #
# default_fetch (httpx monkeypatched — never hits the network)
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


def test_default_fetch_returns_body(monkeypatch):
    captured: dict = {}

    def _get(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})
        return _Resp(200, '{"ok": true}')

    monkeypatch.setattr(httpx, "get", _get)
    body = default_fetch("https://reddit.com/x.json")
    assert body == '{"ok": true}'
    assert captured["headers"]["User-Agent"] == "ReelForgeBot/1.0 (+stories)"


def test_default_fetch_maps_4xx_to_502(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, **kw: _Resp(404, "nope"))
    with pytest.raises(RedditFetchError) as ei:
        default_fetch("https://reddit.com/x.json")
    assert ei.value.status_code == 502


def test_default_fetch_maps_timeout_to_502(monkeypatch):
    def _boom(url, **kwargs):
        raise RuntimeError("timeout")

    monkeypatch.setattr(httpx, "get", _boom)
    with pytest.raises(RedditFetchError) as ei:
        default_fetch("https://reddit.com/x.json")
    assert ei.value.status_code == 502
