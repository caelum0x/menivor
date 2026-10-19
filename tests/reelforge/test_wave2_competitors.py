"""Competitor ad tracker: official Meta / TikTok ad-library APIs (mocked HTTP), longevity, alerts, clone."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.domains.adclone import tracked_source
from app.domains.adclone.schemas import CloneBrief
from app.domains.brand_agent.models import AgentInspiration
from app.domains.competitors import longevity, service
from app.domains.competitors import router as competitors_router
from app.domains.competitors.sources import SourceNotConnected
from app.domains.competitors.sources import meta_ad_library as meta
from app.domains.competitors.sources import tiktok_commercial as tiktok
from tests.reelforge._integrations_fakes import FakeTransport, Resp
from tests.reelforge._wave2_support import H, OTHER, client_for, data, make_env

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
META_ENV = {meta.TOKEN_ENV: "meta-token"}
BOTH_ENV = {**META_ENV, tiktok.KEY_ENV: "ck", tiktok.SECRET_ENV: "cs"}
ADS_URL = "https://graph.facebook.com/v23.0/ads_archive"


def _meta_ad(ad_id, *, days_ago, stopped_days_ago=None, body="Stop overpaying for coffee. Try Brewly today.",
             title="Brewly beans"):
    item = {"id": ad_id, "page_id": "111", "page_name": "Brewly",
            "ad_delivery_start_time": (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%d"),
            "ad_creative_bodies": [body], "ad_creative_link_titles": [title],
            "ad_snapshot_url": f"https://www.facebook.com/ads/archive/render_ad/?id={ad_id}",
            "publisher_platforms": ["facebook", "instagram"], "languages": ["en"]}
    if stopped_days_ago is not None:
        item["ad_delivery_stop_time"] = (NOW - timedelta(days=stopped_days_ago)).strftime("%Y-%m-%d")
    return item


def _meta_transport(*pages):
    t = FakeTransport()
    t.add("GET", ADS_URL, *[Resp(200, p) for p in pages])
    return t


@pytest.fixture()
def env(monkeypatch):
    return make_env(monkeypatch)


def _brand(env, **kw):
    with env.db.scope() as s:
        return service.add_brand(s, env.uid, name=kw.pop("name", "Brewly"), **{"meta_page_ids": ["111"], **kw})


# --------------------------------------------------------------------------- sources
def test_meta_source_uses_the_official_ads_archive_with_eu_countries():
    t = _meta_transport({"data": [_meta_ad("901", days_ago=40)], "paging": {"cursors": {"after": "c1"},
                                                                            "next": "https://x"}},
                        {"data": [_meta_ad("902", days_ago=3)]})
    ads = meta.fetch(t, page_ids=["111", "abc"], search_terms="", countries=[], env=META_ENV)
    assert [a.external_id for a in ads] == ["901", "902"]
    call = t.calls[0]
    assert call["url"] == ADS_URL and call["params"]["ad_active_status"] == "ALL"
    assert json.loads(call["params"]["search_page_ids"]) == ["111"]
    assert "DE" in json.loads(call["params"]["ad_reached_countries"])
    assert t.calls[1]["params"]["after"] == "c1"
    assert ads[0].page_url == "https://www.facebook.com/ads/library/?id=901" and ads[0].media_url == ""
    assert ads[0].body.startswith("Stop overpaying")


def test_sources_without_keys_report_the_owner_step_and_never_call_out():
    t = FakeTransport()
    with pytest.raises(SourceNotConnected) as err:
        meta.fetch(t, page_ids=["111"], search_terms="", countries=[], env={})
    assert "META_AD_LIBRARY_TOKEN" in err.value.message
    with pytest.raises(SourceNotConnected):
        tiktok.fetch(t, advertiser_ids=["5"], search_terms="", countries=[], env={})
    assert t.calls == []


def test_tiktok_source_uses_client_credentials_and_the_adlib_query():
    t = FakeTransport()
    t.add("POST", tiktok.TOKEN_URL, Resp(200, {"access_token": "tok", "expires_in": 7200}))
    t.add("POST", tiktok.QUERY_URL, Resp(200, {"data": {"ads": [{
        "ad": {"id": "7001", "first_shown_date": "20260801", "last_shown_date": "20261005", "status": "active",
               "videos": [{"url": "https://v16.tiktokcdn.com/ad.mp4", "cover_image_url": "https://p16.ibyteimg.com/c.jpg"}]},
        "advertiser": {"business_id": "5", "business_name": "Brewly"}}], "has_more": False}, "error": {"code": "ok"}}))
    ads = tiktok.fetch(t, advertiser_ids=["5"], search_terms="", countries=["DE"], env=BOTH_ENV, today=NOW.date())
    assert ads[0].external_id == "7001" and ads[0].active and ads[0].media_url.endswith("ad.mp4")
    assert ads[0].started_at.date().isoformat() == "2026-08-01"
    query = t.find("POST", tiktok.QUERY_URL)[0]
    assert query["headers"]["Authorization"] == "Bearer tok"
    assert query["json"]["filters"]["advertiser_business_ids"] == [5]
    assert t.find("POST", tiktok.TOKEN_URL)[0]["data"]["grant_type"] == "client_credentials"


# --------------------------------------------------------------------------- longevity
def test_longevity_tiers_and_scaled_copy():
    class Row:
        def __init__(self, days, stopped=None, body="same copy"):
            self.started_at = NOW - timedelta(days=days)
            self.stopped_at = None if stopped is None else NOW - timedelta(days=stopped)
            self.active = stopped is None
            self.body, self.title = body, ""

    rows = [Row(45), Row(20), Row(3), Row(60, stopped=10, body="other")]
    marks = longevity.annotate(rows, NOW)
    assert [m["tier"] for m in marks] == ["winner", "proven", "testing", "proven"]
    assert marks[0]["scaled"] and not marks[3]["scaled"]
    assert marks[0]["score"] > marks[1]["score"] > marks[2]["score"]
    assert longevity.tier(None, True) == "unknown"


# --------------------------------------------------------------------------- service
def test_first_refresh_is_a_baseline_then_new_ads_alert(env):
    brand = _brand(env)
    first = _meta_transport({"data": [_meta_ad("901", days_ago=45), _meta_ad("902", days_ago=20, stopped_days_ago=2)]})
    with env.db.scope() as s:
        out = service.refresh(s, env.uid, brand["id"], transport=first, env=BOTH_ENV | {tiktok.KEY_ENV: ""}, now=NOW)
    assert out["added"] == 2 and out["new"] == 0
    assert out["sources"]["meta"] == "ok" and out["sources"]["tiktok"] == "skipped"
    second = _meta_transport({"data": [_meta_ad("901", days_ago=45), _meta_ad("903", days_ago=1)]})
    with env.db.scope() as s:
        out = service.refresh(s, env.uid, brand["id"], transport=second, env=META_ENV, now=NOW + timedelta(days=1))
        assert out["new"] == 1
        alerts = service.alerts(s, env.uid, now=NOW)
        assert [a["external_id"] for a in alerts["items"]] == ["903"]
        ads = service.list_ads(s, env.uid, now=NOW)
        assert ads[0]["external_id"] == "901" and ads[0]["tier"] == "winner"
        assert service.dismiss_alerts(s, env.uid) == 1
        assert service.alerts(s, env.uid)["count"] == 0


def test_refresh_reports_a_missing_source_and_keeps_the_other(env):
    brand = _brand(env, tiktok_advertiser_ids=["5"])
    t = _meta_transport({"data": [_meta_ad("901", days_ago=45)]})
    with env.db.scope() as s:
        out = service.refresh(s, env.uid, brand["id"], transport=t, env=META_ENV, now=NOW)
    assert out["sources"]["meta"] == "ok"
    assert out["sources"]["tiktok"].startswith("not_connected") and "Commercial Content API" in out["sources"]["tiktok"]


def test_brand_validation_and_ownership(env):
    with env.db.scope() as s:
        with pytest.raises(service.CompetitorError):
            service.add_brand(s, env.uid, name="Nothing to search")
        brand = service.add_brand(s, env.uid, name="Brewly", meta_page_ids=["fb.com/111", "x"], countries=["de", "zz9"])
        assert brand["meta_page_ids"] == ["111"] and brand["countries"] == ["DE"]
        with pytest.raises(service.CompetitorError) as err:
            service.refresh(s, env.other, brand["id"], transport=FakeTransport(), env=META_ENV)
        assert err.value.status_code == 404


def test_clone_this_builds_a_brief_from_copy_and_saves_an_inspiration(env):
    brand = _brand(env)
    with env.db.scope() as s:
        service.refresh(s, env.uid, brand["id"], transport=_meta_transport({"data": [_meta_ad("901", days_ago=45)]}),
                        env=META_ENV, now=NOW)
        ad = service.list_ads(s, env.uid, now=NOW)[0]
        out = service.clone_brief(s, env.uid, ad["id"])
        brief = CloneBrief.model_validate(out["brief"])
        assert brief.source.platform == "meta" and "Brewly" in brief.source.avoid_terms
        assert brief.hook.pattern == "bold_claim"  # "Stop ..." opener
        assert any(tracked_source.COPY_NOTE in n for n in brief.notes)
        assert out["ad_clone_path"].startswith("/ad-clone")
        insp = s.query(AgentInspiration).one()
        assert insp.source == "competitor" and insp.url == "https://www.facebook.com/ads/library/?id=901"
        assert insp.metrics["tier"] == "winner"


def test_clone_uses_media_only_from_official_cdn_hosts(env, monkeypatch):
    assert tracked_source.allowed_media("https://v16.tiktokcdn.com/a.mp4")
    assert not tracked_source.allowed_media("https://evil.example/a.mp4")
    assert not tracked_source.allowed_media("http://v16.tiktokcdn.com/a.mp4")
    seen = {}

    def fake_brief(media_url, **kw):
        seen["url"] = media_url
        return tracked_source.brief_from_copy(url=kw["page_url"], platform="tiktok", source_ref=kw["source_ref"],
                                              advertiser=kw["advertiser"], body="Hook line here. Then a payoff.")

    monkeypatch.setattr(tracked_source, "brief_from_media", fake_brief)
    brand = _brand(env, meta_page_ids=[], tiktok_advertiser_ids=["5"])
    t = FakeTransport()
    t.add("POST", tiktok.TOKEN_URL, Resp(200, {"access_token": "tok"}))
    t.add("POST", tiktok.QUERY_URL, Resp(200, {"data": {"ads": [{
        "ad": {"id": "7001", "first_shown_date": "20260801", "status": "active",
               "videos": [{"url": "https://v16.tiktokcdn.com/ad.mp4"}]},
        "advertiser": {"business_name": "Brewly"}}]}, "error": {"code": "ok"}}))
    with env.db.scope() as s:
        service.refresh(s, env.uid, brand["id"], transport=t, env=BOTH_ENV, now=NOW)
        ad = service.list_ads(s, env.uid, now=NOW)[0]
        service.clone_brief(s, env.uid, ad["id"])
    assert seen["url"] == "https://v16.tiktokcdn.com/ad.mp4"


def test_ad_without_copy_or_video_cannot_be_cloned(env):
    with pytest.raises(Exception) as err:
        tracked_source.brief_from_copy(url="https://x", platform="meta", source_ref="m:1", advertiser="", body="")
    assert getattr(err.value, "status_code", 0) == 422


def test_http_track_refresh_and_clone(env, monkeypatch):
    monkeypatch.setenv(meta.TOKEN_ENV, "meta-token")
    monkeypatch.setattr(competitors_router, "TRANSPORT", _meta_transport({"data": [_meta_ad("901", days_ago=45)]}))
    client = client_for(competitors_router, monkeypatch=monkeypatch, db=env.db)
    brand = data(client.post("/api/v1/competitors", headers=H, json={"name": "Brewly", "meta_page_ids": ["111"]}))
    brand_id = brand["brand"]["id"]
    overview = data(client.get("/api/v1/competitors", headers=H))
    assert overview["sources"][0]["connected"] is True and len(overview["brands"]) == 1
    out = data(client.post(f"/api/v1/competitors/{brand_id}/refresh", headers=H))
    assert out["added"] == 1
    ads = data(client.get("/api/v1/competitors/ads?tier=winner", headers=H))["ads"]
    assert ads[0]["days_running"] >= 30
    cloned = data(client.post(f"/api/v1/competitors/ads/{ads[0]['id']}/clone", headers=H, json={}))
    assert cloned["brief"]["source"]["platform"] == "meta"
    assert client.post(f"/api/v1/competitors/ads/{ads[0]['id']}/clone", headers=OTHER, json={}).status_code == 404
    assert data(client.get("/api/v1/competitors", headers=OTHER))["brands"] == []
