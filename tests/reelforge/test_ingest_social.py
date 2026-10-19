"""Social resolvers (mocked HTTP per platform), SSRF guard, service wiring, /ingest/detect."""

from __future__ import annotations

import hashlib
import importlib
import json
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.domains.adstudio import fetch as adstudio_fetch
from app.domains.ingest import safe_fetch
from app.domains.ingest.service import IngestError, IngestService
from app.models.db.base import Base
from app.models.db.models import User
from app.models.exception import HttpException
from app.utils import utils

ingest_mod = importlib.import_module("app.domains.ingest.router")
ingest_service = importlib.import_module("app.domains.ingest.service")


class FakeHttp:
    """``http(url) -> (status, text)`` seam answering by URL prefix; records calls."""

    def __init__(self, routes: dict[str, tuple[int, str]]) -> None:
        self.routes = routes
        self.calls: list[str] = []

    def __call__(self, url: str) -> tuple[int, str]:
        self.calls.append(url)
        for prefix, answer in self.routes.items():
            if url.startswith(prefix):
                return answer
        return 404, ""


def _og(**tags: str) -> str:
    metas = "".join(f'<meta property="{k.replace("_", ":")}" content="{v}">' for k, v in tags.items())
    return f"<html><head>{metas}</head><body></body></html>"


def _run(url: str, routes: dict) -> tuple[dict, FakeHttp]:
    http = FakeHttp(routes)
    return IngestService().url_to_reel(url, http=http), http


def _assert_post(result: dict, platform: str) -> None:
    assert result["source"]["kind"] == "social_post"
    assert result["source"]["platform"] == platform
    assert set(result["inspiration"]) == {
        "caption", "hook", "topic", "format", "duration_s", "author_name", "thumbnail_url"}
    assert result["content"]["title"] and result["content"]["description"]
    assert result["reel_draft"]["video_script"].endswith("Check the link to try it.")
    author = result["inspiration"]["author_name"]
    if author:
        assert author not in result["reel_draft"]["video_script"]


# --------------------------------------------------------------------------- #
# Per-platform resolvers
# --------------------------------------------------------------------------- #
def test_tiktok_post_via_oembed():
    body = json.dumps({"title": "POV: you meal prep in 10 minutes #mealprep #fitness",
                       "author_name": "Chef Anna", "thumbnail_url": "https://p16.tiktokcdn.com/t.jpg"})
    result, http = _run("https://www.tiktok.com/@chef.anna/video/7301234567890123456",
                        {"https://www.tiktok.com/oembed?url=": (200, body)})
    _assert_post(result, "tiktok")
    insp = result["inspiration"]
    assert insp["hook"] == "POV: you meal prep in 10 minutes"
    assert insp["format"] == "short video" and insp["duration_s"] is None
    assert insp["topic"].startswith("mealprep")
    assert result["reel_draft"]["hook"].startswith("POV:")
    assert "Chef Anna" not in json.dumps(result["reel_draft"])
    assert result["source"]["label"] == "TikTok post detected"
    assert "https%3A%2F%2Fwww.tiktok.com%2F%40chef.anna" in http.calls[0]


def test_tiktok_private_post_message():
    with pytest.raises(IngestError) as ei:
        _run("https://www.tiktok.com/@a/video/1", {"https://www.tiktok.com/oembed": (400, "")})
    assert ei.value.status_code == 404
    assert ei.value.message == "That TikTok post is private or deleted"


def test_youtube_video_with_duration():
    oembed = json.dumps({"title": "How to fix a leaky faucet", "author_name": "DIY Dan",
                         "thumbnail_url": "https://i.ytimg.com/vi/x/hq.jpg"})
    page = '<meta itemprop="duration" content="PT4M5S">'
    result, http = _run("https://youtu.be/dQw4w9WgXcQ", {
        "https://www.youtube.com/oembed": (200, oembed),
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ": (200, page)})
    _assert_post(result, "youtube")
    assert result["inspiration"]["duration_s"] == 245
    assert result["inspiration"]["format"] == "video"
    assert result["reel_draft"]["inspired_by"]["hook_style"] == "howto"
    assert "watch%3Fv%3DdQw4w9WgXcQ" in http.calls[0]


def test_youtube_short_duration_optional():
    oembed = json.dumps({"title": "5 gadgets under $20", "author_name": "Techie"})
    result, _ = _run("https://www.youtube.com/shorts/abcDEF12345", {
        "https://www.youtube.com/oembed": (200, oembed),
        "https://www.youtube.com/watch": (500, "")})
    assert result["inspiration"]["format"] == "short video"
    assert result["inspiration"]["duration_s"] is None
    assert result["source"]["label"] == "YouTube Short detected"


def test_youtube_private_video():
    with pytest.raises(IngestError) as ei:
        _run("https://www.youtube.com/watch?v=zzz", {"https://www.youtube.com/oembed": (401, "")})
    assert ei.value.message == "That YouTube video is private or deleted"


def test_youtube_channel_profile():
    page = _og(og_title="MrBeast - YouTube", og_description="I want to make the world a better place before I die. Fun challenges!!",
               og_image="https://yt3.ggpht.com/a.jpg")
    result, _ = _run("https://www.youtube.com/@MrBeast", {"https://www.youtube.com/@MrBeast": (200, page)})
    brand = result["brand"]
    assert result["source"] == {"kind": "social_profile", "platform": "youtube",
                                "label": "YouTube channel detected", "handle": "MrBeast", "note": None}
    assert brand["name"] == "MrBeast" and brand["handle"] == "MrBeast"
    assert brand["avatar_url"] == "https://yt3.ggpht.com/a.jpg"
    assert brand["voice"] == "playful"
    assert result["content"]["title"] == "MrBeast"
    assert result["reel_draft"]["video_subject"] == "MrBeast"


def test_x_post_strips_html():
    html = ('<blockquote class="twitter-tweet"><p lang="en">Stop writing docs nobody reads. '
            'Ship a video. <a href="https://t.co/x">pic.twitter.com/abc</a></p>&mdash; Jack (@jack)</blockquote>')
    result, http = _run("https://x.com/jack/status/20", {
        "https://publish.twitter.com/oembed": (200, json.dumps({"html": html, "author_name": "jack"}))})
    _assert_post(result, "x")
    assert result["inspiration"]["caption"].startswith("Stop writing docs nobody reads.")
    assert "<" not in result["inspiration"]["caption"]
    assert result["inspiration"]["format"] == "image post"
    assert result["reel_draft"]["inspired_by"]["hook_style"] == "warning"


def test_x_deleted_post():
    with pytest.raises(IngestError) as ei:
        _run("https://twitter.com/jack/status/99", {"https://publish.twitter.com/oembed": (404, "")})
    assert ei.value.message == "That X post is private or deleted"


def test_instagram_post_falls_back_to_og_with_note():
    page = _og(og_title="Nike on Instagram", og_type="video.other", og_image="https://cdn/ig.jpg",
               og_description='1,234 likes, 56 comments - nike on May 1, 2026: &quot;Just do it. #running&quot;')
    result, _ = _run("https://www.instagram.com/reel/Cabc987/", {"https://www.instagram.com/reel/": (200, page)})
    _assert_post(result, "instagram")
    assert result["inspiration"]["caption"] == "Just do it. #running"
    assert result["inspiration"]["format"] == "short video"
    assert result["inspiration"]["author_name"] == "Nike"
    assert result["source"]["note"] == (
        "Instagram hides post details without an app token, so we used the public preview")


def test_instagram_blocked_preview():
    with pytest.raises(IngestError) as ei:
        _run("https://www.instagram.com/p/Cxyz/", {"https://www.instagram.com/p/": (403, "")})
    assert ei.value.status_code == 424
    assert "Instagram would not share" in ei.value.message


def test_instagram_profile():
    page = _og(og_title="Nike (@nike) • Instagram photos and videos",
               og_description="Official account. Spotlighting athletes and running training.")
    result, _ = _run("https://www.instagram.com/nike/", {"https://www.instagram.com/nike/": (200, page)})
    assert result["brand"]["name"] == "Nike"
    assert result["brand"]["niche"] == "fitness"
    assert result["brand"]["voice"] == "professional"


def test_facebook_video_og_with_note():
    page = _og(og_title="NASA", og_description="Watch the launch live. #space", og_type="video.other",
               og_video_duration="95")
    result, _ = _run("https://www.facebook.com/nasa/videos/123456789/", {"https://www.facebook.com/": (200, page)})
    _assert_post(result, "facebook")
    assert result["inspiration"]["duration_s"] == 95
    assert result["inspiration"]["format"] == "video"
    assert result["source"]["note"].startswith("Facebook hides post details")


def test_threads_post_og():
    page = _og(og_title="Zuck (@zuck) on Threads", og_description="Why does everyone ship on Fridays?")
    result, _ = _run("https://www.threads.net/@zuck/post/C8abc", {"https://www.threads.net/": (200, page)})
    _assert_post(result, "threads")
    assert result["inspiration"]["format"] == "text post"
    assert result["inspiration"]["author_name"] == "zuck"
    assert result["reel_draft"]["inspired_by"]["hook_style"] == "question"
    assert result["source"]["note"] is None


def test_pinterest_pin_og():
    page = _og(og_title="Cozy reading nook ideas", og_description="Cozy reading nook ideas for small apartments #homedecor",
               og_image="https://i.pinimg.com/x.jpg")
    result, _ = _run("https://www.pinterest.com/pin/123456789012/", {"https://www.pinterest.com/pin/": (200, page)})
    _assert_post(result, "pinterest")
    assert result["inspiration"]["format"] == "image pin"
    assert result["inspiration"]["thumbnail_url"] == "https://i.pinimg.com/x.jpg"


def test_linkedin_post_og():
    page = _og(og_title="Satya Nadella on LinkedIn", og_description="3 lessons from shipping AI at scale. First, listen to customers.")
    result, _ = _run("https://www.linkedin.com/posts/satya_activity-7123-abcd",
                     {"https://www.linkedin.com/posts/": (200, page)})
    _assert_post(result, "linkedin")
    assert result["inspiration"]["hook"] == "3 lessons from shipping AI at scale."
    assert result["reel_draft"]["inspired_by"]["hook_style"] == "list"


def test_x_profile_degrades_to_handle_with_note():
    result, _ = _run("https://x.com/jack", {"https://x.com/jack": (200, "<html><body>JS app</body></html>")})
    assert result["brand"]["name"] == "jack" and result["brand"]["handle"] == "jack"
    assert result["source"]["note"] == "X hides profile details from previews, so we used the handle"


def test_missing_profile_message():
    with pytest.raises(IngestError) as ei:
        _run("https://www.tiktok.com/@ghost", {})
    assert ei.value.message == "That TikTok profile does not exist"


def test_platform_outage_is_502():
    with pytest.raises(IngestError) as ei:
        _run("https://www.tiktok.com/@a/video/1", {"https://www.tiktok.com/oembed": (503, "")})
    assert ei.value.status_code == 502


# --------------------------------------------------------------------------- #
# Website / store path stays backward compatible
# --------------------------------------------------------------------------- #
def test_website_and_store_paths_keep_extraction():
    html = "<title>Notion</title><meta name='description' content='All-in-one workspace'>"
    for url, kind in [("https://acme.example", "website"),
                      ("https://apps.apple.com/us/app/notion/id1232780281", "app_store")]:
        result = IngestService().url_to_reel(url, fetcher=lambda _u: html)
        assert result["source"]["kind"] == kind
        assert result["content"]["title"] == "Notion"
        assert result["reel_draft"]["hook"].startswith("POV:")
        assert "inspiration" not in result and "brand" not in result


# --------------------------------------------------------------------------- #
# SSRF guard
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, status: int, headers: dict | None = None, body: bytes = b"") -> None:
        self.status_code, self.headers, self._body = status, headers or {}, body

    def iter_content(self, chunk_size: int = 65536):
        yield self._body

    def close(self) -> None:
        pass


class _Session:
    def __init__(self, script: dict[str, _Resp], log: list[str]) -> None:
        self.script, self.log, self.trust_env = script, log, True

    def mount(self, *_a) -> None:
        pass

    def get(self, url: str, **_kw) -> _Resp:
        self.log.append(url)
        return self.script[url]

    def close(self) -> None:
        pass


@pytest.fixture()
def public_dns(monkeypatch):
    monkeypatch.setattr(adstudio_fetch, "_pinned_ip", lambda _u: "93.184.216.34")


@pytest.mark.parametrize("url", ["http://127.0.0.1/x", "http://localhost/", "http://10.0.0.5/",
                                 "http://169.254.169.254/latest/meta-data", "https://evil.example/"])
def test_social_get_rejects_private_and_non_allowlisted(url):
    with pytest.raises(IngestError) as ei:
        safe_fetch.social_http_get(url)
    assert ei.value.status_code == 422


@pytest.mark.parametrize("url", ["http://localhost:8080/", "http://127.0.0.1/", "http://[::1]/", "http://192.168.1.1/"])
def test_website_fetch_rejects_private(url):
    with pytest.raises(IngestError) as ei:
        IngestService().url_to_reel(url)
    assert ei.value.status_code == 422


def test_social_redirect_to_other_host_is_refused(public_dns):
    log: list[str] = []
    script = {"https://pin.it/abc": _Resp(302, {"Location": "https://evil.example/steal"})}
    with pytest.raises(IngestError) as ei:
        safe_fetch.social_http_get("https://pin.it/abc", session_factory=lambda: _Session(script, log))
    assert ei.value.status_code == 422
    assert log == ["https://pin.it/abc"]


def test_social_redirect_to_private_ip_is_refused(public_dns):
    log: list[str] = []
    script = {"https://pin.it/abc": _Resp(302, {"Location": "http://169.254.169.254/latest"})}
    with pytest.raises(IngestError) as ei:
        safe_fetch.social_http_get("https://pin.it/abc", session_factory=lambda: _Session(script, log))
    assert ei.value.status_code == 422


def test_social_redirect_within_allowlist_succeeds(public_dns):
    log: list[str] = []
    script = {
        "https://pin.it/abc": _Resp(301, {"Location": "https://www.pinterest.com/pin/1/"}),
        "https://www.pinterest.com/pin/1/": _Resp(200, {"Content-Type": "text/html"}, b"<title>ok</title>"),
    }
    status, text = safe_fetch.social_http_get("https://pin.it/abc", session_factory=lambda: _Session(script, log))
    assert (status, text) == (200, "<title>ok</title>")
    assert log == ["https://pin.it/abc", "https://www.pinterest.com/pin/1/"]


def test_social_blocked_and_missing_map_to_status(public_dns):
    for upstream, expected in [(404, 404), (403, 403), (429, 403)]:
        script = {"https://x.com/jack": _Resp(upstream)}
        status, _ = safe_fetch.social_http_get("https://x.com/jack", session_factory=lambda: _Session(script, []))
        assert status == expected


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with factory() as s:
        s.add(User(email="a@example.com", api_key_hash=hashlib.sha256(b"k").hexdigest()))
        s.commit()

    @contextmanager
    def _gs():
        s = factory()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr(ingest_mod, "get_session", _gs)
    monkeypatch.setattr(ingest_mod, "_DB_IMPORT_ERROR", None)
    oembed = json.dumps({"title": "POV: tiny desk setup #desksetup", "author_name": "Desk Guy"})
    monkeypatch.setattr(ingest_service, "_default_http", FakeHttp({"https://www.tiktok.com/oembed": (200, oembed)}))
    app = FastAPI()
    app.include_router(ingest_mod.router)
    app.add_exception_handler(HttpException, lambda _r, exc: JSONResponse(
        status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)))
    return TestClient(app)


def test_detect_endpoint(client):
    resp = client.post("/api/v1/ingest/detect", json={"url": "youtube.com/@MrBeast"}, headers={"x-api-key": "k"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == {"kind": "social_profile", "platform": "youtube",
                                   "label": "YouTube channel detected",
                                   "url": "https://youtube.com/@MrBeast", "handle": "MrBeast"}


def test_detect_endpoint_rejects_junk_and_requires_auth(client):
    bad = client.post("/api/v1/ingest/detect", json={"url": "ftp://x"}, headers={"x-api-key": "k"})
    assert bad.status_code == 400
    assert client.post("/api/v1/ingest/detect", json={"url": "https://x.com/jack"}).status_code == 401


def test_ingest_url_endpoint_social_post(client):
    resp = client.post("/api/v1/ingest/url", json={"url": "https://www.tiktok.com/@d/video/1"},
                       headers={"x-api-key": "k"})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["source"]["label"] == "TikTok post detected"
    assert data["inspiration"]["hook"] == "POV: tiny desk setup"
    assert {"url", "content", "reel_draft"} <= set(data)
