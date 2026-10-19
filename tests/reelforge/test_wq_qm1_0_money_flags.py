"""Wave Q QM1.0: the Menivor money-flag defects (P-M12, P-M14, P-M15, the P-M13 check).

1. P-M12: the ad tracking signature covers ad id, event, play id and expiry
   (15 min or less). A replayed, tampered or expired URL records nothing, and
   each (play, ad, event) counts once (unique key, also on Postgres).
2. P-M14: an SVOD grant without ``expires_at_ms`` is refused (422, logged) and
   never stored open-ended; a corrected redelivery still applies.
3. The TV-code approve route is limited to 10 a minute per viewer; team-member
   add answers the same whether or not the account exists (P-M15); the staff
   house-ad route is behind the ads flag.
4. ``ott_meter_check`` compares each Dodo meter's free threshold with the plan
   caps and exits non-zero on a mismatch (P-M13 check).
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree as ET

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.domains.ott.models import OttTitle
from app.domains.ott_ads import router as ads_router, service as ads
from app.domains.ott_commerce import entitlements, tasks
from app.domains.ott_commerce.models import OttAd, OttAdEvent, OttEntitlement, OttMintEvent
from app.domains.ott_viewers import router as viewers_router, tv_codes
from app.services.billing import ott_meter_check, ott_plans

from tests.reelforge import _wp_p3_ott as h
from tests.reelforge.test_wp_pm3_2_commerce_ads import OWNER, _deliver, _event, _offer, env  # noqa: F401


# --------------------------------------------------------------------------- #
# 1. P-M12 ad tracking
# --------------------------------------------------------------------------- #
def _spot(env) -> str:
    with env["factory"]() as s:
        title = OttTitle(channel_id=env["cid"], title="Sponsor spot", kind="short", genres=[], geo_countries=[],
                         status="published", package_status="ready", duration_s=15.0, source_key="ott:src/spot.mp4",
                         access_tier="free", manifest_key="ott/x/master.m3u8", published_at=datetime.now(timezone.utc))
        s.add(title)
        s.commit()
        return title.id


def _vast_urls(env) -> dict[str, str]:
    doc = ET.fromstring(env["client"].get(f"/api/v1/ott/ads/vast/{env['ids'][2]}").content)
    urls = {"impression": doc.find(".//Impression").text, "click": None}
    urls.update({t.get("event"): t.text for t in doc.iter("Tracking")})
    return {k: v.split("/api/v1", 1)[1] for k, v in urls.items() if v}


@pytest.fixture()
def ad_env(env, monkeypatch):
    monkeypatch.setattr(ads_router, "media_url", lambda title: "https://r2.example/a.mp4")
    ad_id = env["client"].post("/api/v1/ott/studio/ads", headers=OWNER,
                               json={"title_id": _spot(env), "name": "Spot"}).json()["data"]["id"]
    return {**env, "ad_id": ad_id}


def _stats(env) -> dict:
    return env["client"].get("/api/v1/ott/studio/ads", headers=OWNER).json()["data"]["ads"][0]["stats"]


def test_tracking_url_binds_play_and_expires_within_15_minutes(ad_env):
    urls = _vast_urls(ad_env)
    query = parse_qs(urlsplit(urls["impression"]).query)
    assert set(query) == {"t", "p", "x"}
    assert 0 < int(query["x"][0]) - time.time() <= 15 * 60
    assert ads.TRACK_TTL_S <= 15 * 60
    skip = parse_qs(urlsplit(urls["skip"]).query)
    assert skip["p"] == query["p"] and skip["t"] != query["t"]  # one play, one signature per event


def test_a_replayed_tracking_url_counts_once(ad_env):
    urls = _vast_urls(ad_env)
    for _ in range(3):
        assert ad_env["client"].get(f"/api/v1{urls['impression']}").status_code == 204
    ad_env["client"].get(f"/api/v1{urls['complete']}")
    ad_env["client"].get(f"/api/v1{urls['complete']}")
    assert _stats(ad_env) == {"impressions": 1, "completes": 1, "skips": 0, "clicks": 0}
    again = _vast_urls(ad_env)  # a new play is a new impression
    ad_env["client"].get(f"/api/v1{again['impression']}")
    assert _stats(ad_env)["impressions"] == 2


def test_tampered_or_expired_tracking_records_nothing(ad_env):
    ad_id = ad_env["ad_id"]
    urls = _vast_urls(ad_env)
    parts = urlsplit(urls["impression"])
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    other_play = f"{parts.path}?t={query['t']}&p={'f' * 16}&x={query['x']}"
    later = f"{parts.path}?t={query['t']}&p={query['p']}&x={int(query['x']) + 600}"
    old_style = f"{parts.path}?t={query['t']}"
    for url in (other_play, later, old_style):
        assert ad_env["client"].get(f"/api/v1{url}").status_code == 204
    past = int(time.time()) - 1
    expired_sig = ads.track_sig(ad_id, "impression", "a" * 16, past)
    ad_env["client"].get(f"/api/v1/ott/ads/track/{ad_id}/impression?t={expired_sig}&p={'a' * 16}&x={past}")
    far = int(time.time()) + 3600  # signed, but longer than the TTL allows
    ad_env["client"].get(f"/api/v1/ott/ads/track/{ad_id}/impression?t={ads.track_sig(ad_id, 'impression', 'b' * 16, far)}"
                         f"&p={'b' * 16}&x={far}")
    assert _stats(ad_env)["impressions"] == 0


def test_ad_event_rows_are_swept_after_they_can_no_longer_verify(ad_env):
    urls = _vast_urls(ad_env)
    ad_env["client"].get(f"/api/v1{urls['impression']}")
    with ad_env["factory"]() as s:
        assert s.scalar(select(func.count()).select_from(OttAdEvent)) == 1
        assert ads.sweep_events(s, now=datetime.fromtimestamp(time.time() + 3 * 3600, tz=timezone.utc)) == 1
        s.commit()
        assert s.scalar(select(func.count()).select_from(OttAdEvent)) == 0


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("MENIVOR_PG_TEST_URL"), reason="set MENIVOR_PG_TEST_URL to a scratch Postgres")
def test_dedupe_holds_on_postgres(monkeypatch):
    from app.domains.ott_access import tokens

    monkeypatch.setenv(tokens.SECRET_ENV, "x" * 40)
    engine = create_engine(os.environ["MENIVOR_PG_TEST_URL"], future=True)
    OttAd.__table__.create(engine, checkfirst=True)
    OttAdEvent.__table__.create(engine, checkfirst=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with factory() as s:
        ad = OttAd(channel_id=None, kind="house", name="pg", title_id="t" * 32)
        s.add(ad)
        s.commit()
        ad_id = ad.id
    play, exp = os.urandom(8).hex(), int(time.time()) + 600
    sig = ads.track_sig(ad_id, "impression", play, exp)
    results = []
    for _ in range(3):
        with factory() as s:
            results.append(ads.record(s, ad_id, "impression", sig, play, exp))
            s.commit()
    try:
        assert results == [True, False, False]
        with factory() as s:
            assert s.get(OttAd, ad_id).impressions == 1
    finally:
        with factory() as s:
            s.query(OttAdEvent).filter(OttAdEvent.ad_id == ad_id).delete()
            s.query(OttAd).filter(OttAd.id == ad_id).delete()
            s.commit()


# --------------------------------------------------------------------------- #
# 2. P-M14 SVOD grants without a period end
# --------------------------------------------------------------------------- #
def test_svod_grant_without_expiry_is_refused_and_not_stored(env):
    svod = _offer(env, kind="svod", name="Members", price_cents=500, interval="month")
    refused = _deliver(env, "entitlement.granted", _event(env, "ent_open", svod["sku"]))
    assert refused.status_code == 422
    with env["factory"]() as s:
        assert s.scalar(select(func.count()).select_from(OttEntitlement)) == 0
        assert s.get(OttMintEvent, "ent_open") is None  # not burned: a corrected redelivery can still apply
    period_end = int(time.time() * 1000) + 30 * 86400 * 1000
    fixed = _deliver(env, "entitlement.granted", _event(env, "ent_open", svod["sku"], expires=period_end))
    assert fixed.json()["data"]["outcome"] == "granted"
    with env["factory"]() as s:
        assert all(e.expires_at is not None for e in s.execute(select(OttEntitlement)).scalars())


def test_svod_renewal_without_expiry_keeps_the_running_period(env):
    svod = _offer(env, kind="svod", name="Members", price_cents=500, interval="month")
    period_end = int(time.time() * 1000) + 30 * 86400 * 1000
    _deliver(env, "entitlement.granted", _event(env, "ent_a", svod["sku"], expires=period_end))
    assert _deliver(env, "entitlement.granted", _event(env, "ent_b", svod["sku"])).status_code == 422
    with env["factory"]() as s:
        rows = s.execute(select(OttEntitlement)).scalars().all()
        assert len(rows) == 1 and rows[0].expires_at is not None


def test_reconcile_does_not_count_or_burn_a_refused_grant(env):
    svod = _offer(env, kind="svod", name="Members", price_cents=500, interval="month")

    class Mint:
        def entitlements(self, seller):
            return [_event(env, "ent_r", svod["sku"])]

    with env["factory"]() as s:
        assert tasks.reconcile(s, Mint())["applied"] == 0
        assert s.get(OttMintEvent, "ent_r") is None
    assert entitlements.REFUSED_NO_EXPIRY.startswith("refused:")


# --------------------------------------------------------------------------- #
# 3. Rate limit, enumeration, admin flag
# --------------------------------------------------------------------------- #
def test_tv_approve_is_limited_to_ten_a_minute_per_viewer(env, monkeypatch):
    from app.services import ratelimit

    h.enable(monkeypatch, "viewers", "storefront", "access", "commerce", "ads", "tv")
    monkeypatch.setattr(ratelimit, "_get_client", lambda: None)
    ratelimit.reset_local_buckets()
    tv_codes.set_store(tv_codes.MemoryStore())
    try:
        phone = {"x-ott-viewer": env["viewer"]["session"]}
        codes = [r.status_code for r in (env["client"].post("/api/v1/ott/viewers/maya/tv-codes/approve", headers=phone,
                                                              json={"user_code": "AAAAAA"}) for _ in range(11))]
        assert codes[:10] == [404] * 10 and codes[10] == 429
        other = env["client"].post("/api/v1/ott/viewers/maya/session",
                                   json={"access_token": h.auth_token("sub-w", "w@example.com")}).json()["data"]
        assert env["client"].post("/api/v1/ott/viewers/maya/tv-codes/approve", json={"user_code": "AAAAAA"},
                                  headers={"x-ott-viewer": other["session"]}).status_code == 404
    finally:
        tv_codes.set_store(None)
        ratelimit.reset_local_buckets()
    assert viewers_router.TV_APPROVE_LIMIT == 10


@pytest.fixture()
def team_env(monkeypatch):
    from app.domains.ott_analytics import router as analytics_router

    factory = h.make_factory()
    h.patch_sessions(monkeypatch, factory, (analytics_router,))
    h.enable(monkeypatch, "analytics")
    owner = h.owner(factory)
    h.channel(factory, owner, "maya", titles=1)
    h.owner(factory, "ed@example.com", "ed-key")
    return {"factory": factory, "client": h.app_client(analytics_router.router)}


def test_team_add_answers_the_same_whether_or_not_the_account_exists(team_env):
    client = team_env["client"]
    known = client.post("/api/v1/ott/studio/team", headers=OWNER, json={"email": "ed@example.com", "role": "editor"})
    unknown = client.post("/api/v1/ott/studio/team", headers=OWNER,
                          json={"email": "nobody@example.com", "role": "editor"})
    assert known.status_code == unknown.status_code == 200
    k, u = known.json()["data"], unknown.json()["data"]
    assert k["added"] == {"email": "ed@example.com", "role": "editor"}
    assert u["added"] == {"email": "nobody@example.com", "role": "editor"}
    assert set(k) == set(u) and set(known.json()) == set(unknown.json())
    listed = {m["email"]: set(m) for m in u["members"]}
    assert listed["ed@example.com"] == listed["nobody@example.com"]  # no field tells the two apart


def test_an_invite_gives_access_once_that_email_has_an_account(team_env):
    client = team_env["client"]
    client.post("/api/v1/ott/studio/team", headers=OWNER, json={"email": "Later@Example.com", "role": "analyst"})
    h.owner(team_env["factory"], "later@example.com", "later-key")
    seen = client.get("/api/v1/ott/studio/analytics?channel=maya", headers={"x-api-key": "later-key"})
    assert seen.status_code == 200 and seen.json()["data"]["channel"] == "maya"
    members = client.get("/api/v1/ott/studio/team", headers=OWNER).json()["data"]["members"]
    member_id = next(m["id"] for m in members if m["email"] == "later@example.com")
    client.delete(f"/api/v1/ott/studio/team/{member_id}", headers=OWNER)
    assert client.get("/api/v1/ott/studio/analytics?channel=maya",
                      headers={"x-api-key": "later-key"}).status_code == 403


def test_admin_house_ad_route_is_behind_the_ads_flag(env, monkeypatch):
    monkeypatch.delenv("OTT_ADS_LIVE")
    res = env["client"].post("/api/v1/admin/ott/ads/house", headers=OWNER, json={"title_id": "x", "name": "y"})
    assert res.status_code == 404


# --------------------------------------------------------------------------- #
# 4. P-M13 meter check
# --------------------------------------------------------------------------- #
class FakeDodo:
    def __init__(self, thresholds: dict[str, dict[str, float]]) -> None:
        self.meters = [{"id": f"mtr_{m}", "event_name": f"ott.{m}"} for m in ott_plans.METERS]
        self.thresholds = thresholds

    def list_all(self, path, query=None):
        if path == "/meters":
            return self.meters
        assert path == "/products"
        return [{"product_id": f"pdt_{k}", "metadata": {"menivor_key": k}} for k in self.thresholds]

    def call(self, method, path, body=None, query=None):
        key = path.rsplit("pdt_", 1)[1]
        meters = [{"meter_id": f"mtr_{m}", "free_threshold": v} for m, v in self.thresholds[key].items()]
        return {"product_id": f"pdt_{key}", "metadata": {"menivor_key": key}, "price": {"meters": meters}}


def _aligned() -> dict[str, dict[str, float]]:
    out = {}
    for plan in ("creator", "pro", "agency"):
        for interval in ("month", "year"):
            out[f"plan_{plan}_{interval}"] = {
                m: ott_meter_check.expected_threshold(plan, m, interval) for m in ott_plans.METERS}
    return out


def test_meter_check_passes_when_thresholds_equal_the_caps():
    report = ott_meter_check.check(FakeDodo(_aligned()))
    assert report["ok"] is True and report["checked"] == 24 and report["mismatches"] == []


def test_meter_check_fails_on_a_mismatch_or_a_missing_meter(capsys):
    bad = _aligned()
    bad["plan_pro_month"]["encode_minutes"] = 10
    del bad["plan_agency_year"]["ai_minutes"]
    report = ott_meter_check.check(FakeDodo(bad))
    assert report["ok"] is False
    found = {(m["product"], m["meter"]) for m in report["mismatches"]}
    assert found == {("plan_pro_month", "encode_minutes"), ("plan_agency_year", "ai_minutes")}
    assert ott_meter_check.main(["--dodo"], api=FakeDodo(bad)) == 1
    assert ott_meter_check.main(["--dodo"], api=FakeDodo(_aligned())) == 0
    assert "encode_minutes" in capsys.readouterr().out


def test_meter_check_expected_values_follow_the_plan_caps():
    caps = ott_plans.PLAN_CAPS["pro"]
    assert ott_meter_check.expected_threshold("pro", "encode_minutes", "month") == caps.encode_minutes
    assert ott_meter_check.expected_threshold("pro", "encode_minutes", "year") == caps.encode_minutes * 12
    assert ott_meter_check.expected_threshold("pro", "gb_stored", "month") == caps.gb_stored * 24 * 31


def test_meter_check_without_a_key_exits_2(monkeypatch):
    monkeypatch.delenv("DODO_PAYMENTS_API_KEY", raising=False)
    monkeypatch.setattr(ott_meter_check, "_setting", lambda name: "")
    assert ott_meter_check.main(["--dodo"]) == 2


def test_role_change_reaches_a_pre_wave_q_member_row(team_env):
    """QM verify: a direct member row wins over the invite, so a role change must update it."""
    from app.domains.ott import roles
    from app.domains.ott.models import OttChannel
    from app.models.db.models import User

    factory = team_env["factory"]
    with factory() as s:
        channel = s.execute(select(OttChannel).where(OttChannel.handle == "maya")).scalar_one()
        ed = s.execute(select(User).where(User.email == "ed@example.com")).scalar_one()
        s.add(roles.OttChannelMember(channel_id=channel.id, user_id=ed.id, role="editor"))
        s.commit()
    client = team_env["client"]
    res = client.post("/api/v1/ott/studio/team", headers=OWNER, json={"email": "ed@example.com", "role": "analyst"})
    assert res.status_code == 200
    with factory() as s:
        channel = s.execute(select(OttChannel).where(OttChannel.handle == "maya")).scalar_one()
        ed = s.execute(select(User).where(User.email == "ed@example.com")).scalar_one()
        assert roles.role_of(s, ed.id, channel) == "analyst"
        assert {m["email"]: m["role"] for m in roles.team(s, channel)}["ed@example.com"] == "analyst"


def test_vast_is_rate_limited_so_impressions_cannot_be_looped(ad_env, monkeypatch):
    """QM verify: every VAST answer mints a fresh play id, so the route itself is throttled."""
    from app.services import ratelimit

    monkeypatch.setattr(ratelimit, "_get_client", lambda: None)
    ratelimit.reset_local_buckets()
    try:
        codes = [ad_env["client"].get(f"/api/v1/ott/ads/vast/{ad_env['ids'][2]}").status_code
                 for _ in range(ads_router.VAST_LIMIT + 1)]
    finally:
        ratelimit.reset_local_buckets()
    assert codes[:-1] == [200] * ads_router.VAST_LIMIT and codes[-1] == 429
