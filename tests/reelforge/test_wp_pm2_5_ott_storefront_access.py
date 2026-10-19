"""Wave P PM2.5 (MV4 storefront, player, embed, feeds; MV5 access tier 1).

3. Tokens expire in 10 min or less; a copied manifest fails after expiry; a
   third concurrent stream on a two-stream plan is refused; a geo-blocked
   country gets a clear message.
2. RSS, MRSS and podcast RSS parse and carry the required elements; one custom
   domain resolves to its channel.
4. No key or token in page HTML (web test); keys only for a valid token.
Lighthouse (target 85+) and device playback are deploy-time measurements.
"""

from __future__ import annotations

import hashlib
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.models.db.base as db_base
from app.domains.ott import feeds
from app.domains.ott.models import OttChannel, OttCollection, OttSeries, OttTitle
from app.domains.ott_access import geo, limits, router as access_router, service as access, tokens
from app.models.db.base import Base
from app.models.db.models import Job, User
from app.models.exception import HttpException
from app.services.ott_transcode import keys as content_keys
from app.utils import utils

OWNER_KEY = "owner-key"
MASTER = b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000,RESOLUTION=720x1280\nv_720p.m3u8\n"
MEDIA = (b'#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="https://api.example/api/v1/ott/keys/T",IV=0x00\n'
         b'#EXT-X-MAP:URI="v_720p/init.mp4"\n#EXTINF:2.000,\nv_720p/1.m4s\n#EXT-X-ENDLIST\n')


@pytest.fixture()
def maker(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
                           future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    import app.controllers.v1.jobs as jobs_mod

    for module in (db_base, jobs_mod, feeds, access_router):
        monkeypatch.setattr(module, "get_session", _session)
    for name in ("OTT_ENABLED", "OTT_STOREFRONT_LIVE", "OTT_EMBED_LIVE", "OTT_FEEDS_LIVE", "OTT_ACCESS_LIVE"):
        monkeypatch.setenv(name, "1")
    monkeypatch.setenv(tokens.SECRET_ENV, "x" * 40)
    monkeypatch.setenv(content_keys.SECRET_ENV, "a-content-key-secret-long")
    monkeypatch.setenv(feeds.API_BASE_ENV, "https://api.example")
    monkeypatch.setenv(feeds.WEB_BASE_ENV, "https://web.example")
    monkeypatch.setattr(limits, "_STORE", limits.MemoryStore())
    monkeypatch.setattr("app.domains.ott.catalog_public._art", lambda key: f"https://art/{key}" if key else "")
    with factory() as s:
        s.add(User(email="owner@example.com", api_key_hash=hashlib.sha256(OWNER_KEY.encode()).hexdigest()))
        s.commit()
    return factory


class Store:
    def __init__(self):
        self.objects = {}

    def read(self, key):
        return self.objects[key]

    def presign_get(self, key, ttl):
        return f"https://r2.example/{key}?ttl={ttl}"


def _client(monkeypatch, store=None):
    store = store or Store()
    monkeypatch.setattr(access_router, "storage", lambda: store)
    app = FastAPI()
    app.include_router(feeds.router)
    app.include_router(access_router.router)
    app.add_exception_handler(HttpException, lambda _r, exc: JSONResponse(
        status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)))
    return TestClient(app), store


def _channel(maker, **title_overrides) -> tuple[str, list[str]]:
    with maker() as s:
        owner = s.query(User).one()
        channel = OttChannel(user_id=owner.id, handle="maya", title="Maya", tagline="Films", status="published",
                             brand_colors=[], custom_domain="watch.maya.example")
        s.add(channel)
        s.flush()
        series = OttSeries(channel_id=channel.id, title="Season one")
        s.add(series)
        s.flush()
        ids = []
        specs = [dict(kind="short", title="Short one"), dict(kind="episode", title="Ep 1", series_id=series.id,
                                                             season=1, episode=1),
                 dict(kind="audio", title="Pod 1"), dict(kind="movie", title="Paid film", access_tier="paid"),
                 dict(kind="short", title="Draft", status="draft")]
        for n, spec in enumerate(specs):
            fields = dict(channel_id=channel.id, genres=[], geo_countries=[], status="published",
                          package_status="ready", duration_s=120.0, position=n, source_key=f"ott:src/{n}.mp4",
                          manifest_key=f"ott/{channel.id}/t{n}/j/master.m3u8",
                          published_at=datetime.now(timezone.utc))
            fields.update(spec)
            fields.update(title_overrides if n == 0 else {})
            title = OttTitle(**fields)
            s.add(title)
            s.flush()
            ids.append(title.id)
        s.add(OttCollection(channel_id=channel.id, title="Start here", title_ids=[ids[1], ids[0]]))
        s.commit()
        return channel.id, ids


# --------------------------------------------------------------------------- #
# Tokens, geo and limits
# --------------------------------------------------------------------------- #
def test_tokens_expire_within_ten_minutes_and_bind_one_title(monkeypatch):
    monkeypatch.setenv(tokens.SECRET_ENV, "y" * 40)
    now = time.time()
    token, grant = tokens.issue("t1", "device:a", "TR", ttl_s=3600, now=now)
    assert grant.exp - now <= 600
    assert tokens.verify(token, title_id="t1", now=now + 599).session_id == grant.session_id
    with pytest.raises(tokens.TokenError):
        tokens.verify(token, now=now + 601)
    with pytest.raises(tokens.TokenError):
        tokens.verify(token, title_id="t2", now=now)
    body, sig = token.split(".")
    with pytest.raises(tokens.TokenError):
        tokens.verify(body + "." + sig[:-2] + "AA", now=now)
    monkeypatch.setenv(tokens.SECRET_ENV, "short")
    with pytest.raises(tokens.TokenError):
        tokens.issue("t1", "v", "TR")


EDGE = "edge-secret-0123456789abcdef"


def test_geo_rules():
    # Wave Q QM1.2 (P-M8): the country header counts only with the edge marker.
    env = {geo.EDGE_SECRET_ENV: EDGE}
    edge = {geo.EDGE_HEADER: EDGE}
    assert geo.country({"cf-ipcountry": "de", **edge}, env) == "DE" and geo.country(edge, env) == "XX"
    assert geo.allowed("allow", ["TR"], "TR", env) and not geo.allowed("allow", ["TR"], "XX", env)
    assert not geo.allowed("deny", ["DE"], "DE", env) and geo.allowed("deny", ["DE"], "XX", env)


def test_a_third_stream_on_a_two_stream_plan_is_refused():
    store = limits.MemoryStore()
    now = 1000.0
    assert limits.admit("v", "s1", limit=2, now=now, backend=store)
    assert limits.admit("v", "s2", limit=2, now=now, backend=store)
    assert not limits.admit("v", "s3", limit=2, now=now, backend=store)
    assert limits.admit("v", "s1", limit=2, now=now, backend=store)  # the same stream again is fine
    assert limits.admit("v", "s3", limit=2, now=now + limits.SESSION_TTL_S + 1, backend=store)  # others went idle


# --------------------------------------------------------------------------- #
# Storefront and feeds
# --------------------------------------------------------------------------- #
def test_storefront_shows_only_watchable_titles_with_rails_series_and_shorts(maker, monkeypatch):
    _cid, ids = _channel(maker)
    client, _ = _client(monkeypatch)
    res = client.get("/api/v1/ott/c/maya", headers={"CF-IPCountry": "TR"})
    assert res.status_code == 200 and "s-maxage=30" in res.headers["cache-control"]
    data = res.json()["data"]
    assert [t["title"] for t in data["titles"]] == ["Short one", "Ep 1", "Pod 1", "Paid film"]
    assert data["rails"][0]["title"] == "Start here" and [i["id"] for i in data["rails"][0]["items"]] == [ids[1], ids[0]]
    assert data["rails"][-1]["title"] == "Shorts"
    assert data["series"][0]["episodes"][0]["episode"] == 1
    assert client.get("/api/v1/ott/c/nobody").status_code == 404


def test_titles_outside_their_window_or_unpackaged_are_hidden(maker, monkeypatch):
    _channel(maker, available_from=datetime.now(timezone.utc) + timedelta(days=1))
    client, _ = _client(monkeypatch)
    titles = [t["title"] for t in client.get("/api/v1/ott/c/maya").json()["data"]["titles"]]
    assert "Short one" not in titles


def test_feeds_parse_and_list_free_titles_only(maker, monkeypatch):
    _cid, ids = _channel(maker)
    client, _ = _client(monkeypatch)
    rss = ET.fromstring(client.get("/api/v1/ott/c/maya/rss.xml").content)
    channel = rss.find("channel")
    assert rss.get("version") == "2.0" and channel.findtext("title") == "Maya"
    assert channel.findtext("link") == "https://web.example/c/maya"
    items = channel.findall("item")
    assert {i.findtext("title") for i in items} == {"Short one", "Ep 1", "Pod 1"}
    assert all(i.find("guid") is not None and i.findtext("pubDate") for i in items)
    mrss = ET.fromstring(client.get("/api/v1/ott/c/maya/mrss.xml").content)
    content = mrss.find(".//{http://search.yahoo.com/mrss/}content")
    assert content.get("url").startswith("https://api.example/api/v1/ott/feeds/play/")
    assert content.get("type") == "application/vnd.apple.mpegurl" and content.get("duration") == "120"
    pod = ET.fromstring(client.get("/api/v1/ott/c/maya/podcast.xml").content)
    pod_items = pod.findall("channel/item")
    assert [i.findtext("title") for i in pod_items] == ["Pod 1"]
    enclosure = pod_items[0].find("enclosure")
    assert enclosure.get("type") == "audio/mp4" and int(enclosure.get("length")) > 0
    assert pod.find("channel/{http://www.itunes.com/dtds/podcast-1.0.dtd}category").get("text")
    play = client.get(f"/api/v1/ott/feeds/play/{ids[0]}.m3u8", follow_redirects=False)
    assert play.status_code == 302 and "/api/v1/ott/stream/" in play.headers["location"]


def test_custom_domain_oembed_and_embed(maker, monkeypatch):
    _cid, ids = _channel(maker)
    client, _ = _client(monkeypatch)
    assert client.get("/api/v1/ott/domains/watch.maya.example").json()["data"]["handle"] == "maya"
    assert client.get("/api/v1/ott/domains/other.example").status_code == 404
    embed = client.get(f"/api/v1/ott/embed/{ids[0]}").json()["data"]
    assert embed["watch_url"] == f"https://web.example/c/maya/{ids[0]}"
    o = client.get("/api/v1/ott/oembed", params={"url": f"https://web.example/c/maya/{ids[0]}"}).json()
    assert o["type"] == "video" and f'src="https://web.example/embed/{ids[0]}"' in o["html"]


def test_surfaces_are_404_until_their_flags(maker, monkeypatch):
    _cid, ids = _channel(maker)
    client, _ = _client(monkeypatch)
    monkeypatch.setenv("OTT_FEEDS_LIVE", "0")
    assert client.get("/api/v1/ott/c/maya/rss.xml").status_code == 404
    monkeypatch.setenv("OTT_STOREFRONT_LIVE", "0")
    assert client.get("/api/v1/ott/c/maya").status_code == 404
    assert client.post(f"/api/v1/ott/play/{ids[0]}", json={}).status_code == 404


# --------------------------------------------------------------------------- #
# Playback
# --------------------------------------------------------------------------- #
def test_free_title_plays_with_a_short_token_and_segments_redirect(maker, monkeypatch):
    cid, ids = _channel(maker)
    client, store = _client(monkeypatch)
    prefix = f"ott/{cid}/t0/j"
    store.objects[f"{prefix}/master.m3u8"] = MASTER
    store.objects[f"{prefix}/v_720p.m3u8"] = MEDIA.replace(b"#EXT-X-KEY:METHOD=AES-128,URI=\"https://api.example/api/v1/ott/keys/T\",IV=0x00\n", b"")
    started = client.post(f"/api/v1/ott/play/{ids[0]}", json={"viewer_id": "dev1"})
    assert started.status_code == 200 and started.headers["cache-control"].startswith("no-store")
    data = started.json()["data"]
    assert data["protected"] is False and data["expires_at"] - time.time() <= 600
    assert data["dash_url"].endswith("/manifest.mpd")
    path = data["manifest_url"].replace("https://api.example", "")
    master = client.get(path)
    assert master.status_code == 200 and master.headers["content-type"].startswith("application/vnd.apple.mpegurl")
    variant = client.get(path.replace("master.m3u8", "v_720p.m3u8"))
    assert b"v_720p/1.m4s" in variant.content
    seg = client.get(path.replace("master.m3u8", "v_720p/1.m4s"), follow_redirects=False)
    assert seg.status_code == 302 and seg.headers["location"].startswith(f"https://r2.example/{prefix}/v_720p/1.m4s")
    assert int(seg.headers["location"].split("ttl=")[1]) <= 600
    assert client.get(path.replace("master.m3u8", "../../secret")).status_code in (400, 404)


def test_a_copied_manifest_fails_after_expiry(maker, monkeypatch):
    cid, ids = _channel(maker)
    client, store = _client(monkeypatch)
    store.objects[f"ott/{cid}/t0/j/master.m3u8"] = MASTER
    with maker() as s:
        title = s.get(OttTitle, ids[0])
        old = access.start(s, title, viewer="device:x", country="TR", now=time.time() - 700)
    path = old["manifest_url"].replace("https://api.example", "")
    res = client.get(path)
    assert res.status_code == 403 and "expired" in res.json()["message"]


def test_geo_blocked_viewers_get_a_clear_message(maker, monkeypatch):
    monkeypatch.setenv(geo.EDGE_SECRET_ENV, EDGE)
    _cid, ids = _channel(maker, geo_mode="deny", geo_countries=["DE"])
    client, _ = _client(monkeypatch)
    res = client.post(f"/api/v1/ott/play/{ids[0]}", json={}, headers={"CF-IPCountry": "DE", geo.EDGE_HEADER: EDGE})
    assert res.status_code == 451 and res.json()["message"] == geo.MESSAGE
    assert client.post(f"/api/v1/ott/play/{ids[0]}", json={},
                       headers={"CF-IPCountry": "TR", geo.EDGE_HEADER: EDGE}).status_code == 200


def test_third_screen_is_refused_through_the_route(maker, monkeypatch):
    monkeypatch.setenv("OTT_MAX_STREAMS", "2")
    _cid, ids = _channel(maker)
    client, _ = _client(monkeypatch)
    for _ in range(2):
        assert client.post(f"/api/v1/ott/play/{ids[0]}", json={"viewer_id": "same-device"}).status_code == 200
    third = client.post(f"/api/v1/ott/play/{ids[0]}", json={"viewer_id": "same-device"})
    assert third.status_code == 429 and "2 screens" in third.json()["message"]


def test_paid_title_needs_access_and_its_key_needs_a_token(maker, monkeypatch):
    cid, ids = _channel(maker)
    paid = ids[3]
    client, store = _client(monkeypatch)
    prefix = f"ott/{cid}/t3/j"
    store.objects[f"{prefix}/master.m3u8"] = MASTER
    store.objects[f"{prefix}/v_720p.m3u8"] = MEDIA
    with maker() as s:
        content_keys.ensure_key(s, paid)
        s.commit()
    assert client.post(f"/api/v1/ott/play/{paid}", json={}).status_code == 402
    owner = {"x-api-key": OWNER_KEY}
    data = client.post(f"/api/v1/ott/play/{paid}", json={}, headers=owner).json()["data"]
    assert data["protected"] is True and "dash_url" not in data
    token = data["manifest_url"].split("/stream/")[1].split("/")[0]
    variant = client.get(f"/api/v1/ott/stream/{token}/v_720p.m3u8").content.decode()
    assert f'URI="https://api.example/api/v1/ott/keys/{paid}?t={token}"' in variant
    assert client.get(f"/api/v1/ott/stream/{token}/manifest.mpd").status_code == 404
    key = client.get(f"/api/v1/ott/keys/{paid}", params={"t": token})
    assert key.status_code == 200 and len(key.content) == 16 and key.headers["cache-control"].startswith("no-store")
    other_token, _ = tokens.issue(ids[0], "device:x", "TR")
    assert client.get(f"/api/v1/ott/keys/{paid}", params={"t": other_token}).status_code == 403
    monkeypatch.setenv("OTT_ACCESS_LIVE", "0")
    assert client.post(f"/api/v1/ott/play/{paid}", json={}, headers=owner).status_code == 402


def test_takedown_hides_a_title_from_playback(maker, monkeypatch):
    from app.domains.compliance import takedown

    uid = None
    with maker() as s:
        uid = s.query(User).one().id
        reel = Job(user_id=uid, kind="avatar_reel", state=1, result_key="k", params={})
        s.add(reel)
        s.commit()
        reel_id = reel.id
    _cid, ids = _channel(maker, source_job_id=reel_id)
    client, _ = _client(monkeypatch)
    assert client.post(f"/api/v1/ott/play/{ids[0]}", json={}).status_code == 200
    with maker() as s:
        s.add(takedown.TakedownReport(job_id=reel_id, content_ref=reel_id, reason="copyright",
                                      reporter_email="r@example.com", status=takedown.STATUS_BLOCKED))
        s.commit()
    assert client.post(f"/api/v1/ott/play/{ids[0]}", json={}).status_code == 404
    assert uid
