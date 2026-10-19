"""Paid ads: env gate, Thompson allocation, connections, launch/sync/optimize, clients."""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.ads import bandit, config, connections, optimizer, reporting, service, store
from app.domains.ads.meta_client import MetaAdsClient
from app.domains.ads.platforms import AccountRef, AdsApiError, AdStats, Audience, TokenGrant, VideoState
from app.domains.ads.tiktok_client import TikTokAdsClient, age_groups, location_ids
from app.domains.adstudio.models import AdStudioProject, AdVariant
from app.models.db import marketplace, models  # noqa: F401 - register tables
from app.models.db.base import Base
from app.models.db.models import User

USER = "u1"
PROJECT = "p" * 32


# --------------------------------------------------------------------------- #
# Gate
# --------------------------------------------------------------------------- #
def _clear_env(monkeypatch) -> None:
    for name in ("META", "TIKTOK"):
        monkeypatch.delenv(f"MENIVOR_{name}_APP_ID", raising=False)
        monkeypatch.delenv(f"MENIVOR_{name}_APP_SECRET", raising=False)


def _enable(monkeypatch, platform: str = "meta") -> None:
    monkeypatch.setenv(f"MENIVOR_{platform.upper()}_APP_ID", "app123")
    monkeypatch.setenv(f"MENIVOR_{platform.upper()}_APP_SECRET", "secret456")


def test_status_disabled_without_keys(monkeypatch) -> None:
    _clear_env(monkeypatch)
    doc = config.status()
    assert doc["enabled"] is False
    assert doc["reason"] == config.NOT_ENABLED_REASON
    assert all(not p["enabled"] for p in doc["platforms"])
    with pytest.raises(service.AdsError) as err:
        service.client_for("meta")
    assert err.value.status_code == 503 and "Ads not enabled" in err.value.message


def test_status_enables_one_platform(monkeypatch) -> None:
    _clear_env(monkeypatch)
    _enable(monkeypatch, "tiktok")
    doc = config.status()
    by = {p["platform"]: p for p in doc["platforms"]}
    assert doc["enabled"] and by["tiktok"]["enabled"] and not by["meta"]["enabled"]
    assert by["tiktok"]["min_daily_budget_minor"] == 2000
    assert doc["menivor_fee"] == 0


# --------------------------------------------------------------------------- #
# Bandit
# --------------------------------------------------------------------------- #
def test_even_split_without_data() -> None:
    alloc = bandit.allocate([bandit.Arm("a"), bandit.Arm("b"), bandit.Arm("c")], 3000, 100, seed=1)
    budgets = {a.arm_id: a.budget_minor for a in alloc.arms}
    assert sum(budgets.values()) == 3000
    assert all(700 <= b <= 1300 for b in budgets.values())
    assert not alloc.conclusive and "exploring" in alloc.reason


def test_budget_shifts_to_better_ctr_and_declares_winner() -> None:
    arms = [bandit.Arm("good", 20000, 600), bandit.Arm("bad", 20000, 200)]
    alloc = bandit.allocate(arms, 5000, 100, seed=7)
    by = {a.arm_id: a for a in alloc.arms}
    assert alloc.conclusive and alloc.winner_id == "good"
    assert not by["bad"].active and by["bad"].budget_minor == 0
    assert by["good"].budget_minor == 5000


def test_underfunded_keeps_best_arms_only() -> None:
    arms = [bandit.Arm("a", 5000, 250), bandit.Arm("b", 5000, 50), bandit.Arm("c", 5000, 100)]
    alloc = bandit.allocate(arms, 2500, 2000, seed=3, min_trials=10**9)
    active = [a.arm_id for a in alloc.arms if a.active]
    assert active == ["a"]
    assert alloc.total_minor == 2500


def test_allocation_is_reproducible_for_a_seed() -> None:
    arms = [bandit.Arm("a", 900, 30), bandit.Arm("b", 900, 25)]
    assert bandit.allocate(arms, 1000, 100, seed=42).to_record() == bandit.allocate(arms, 1000, 100, seed=42).to_record()


def test_win_probabilities_sum_to_one() -> None:
    probs = bandit.win_probabilities([bandit.Arm("a", 100, 5), bandit.Arm("b", 100, 9)], random.Random(0), 2000)
    assert abs(sum(probs) - 1.0) < 1e-9 and probs[1] > probs[0]


def test_seed_matches_fnv1a() -> None:
    assert bandit.seed_from_string("") == 0x811C9DC5
    assert bandit.seed_from_string("a") == 0xE40C292C


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def test_metrics_never_invent_values() -> None:
    m = reporting.metrics({"spend_minor": 1234, "impressions": 1000, "clicks": 20, "leads": None}, "USD")
    assert m["spend"] == 12.34 and m["ctr"] == 0.02 and m["cpc"] == 0.62
    assert m["cpl"] is None and m["lead_rate"] is None
    empty = reporting.metrics({}, "USD")
    assert empty["ctr"] is None and empty["cpc"] is None


def test_zero_decimal_currency() -> None:
    m = reporting.metrics({"spend_minor": 500, "impressions": 10, "clicks": 2, "leads": 1}, "JPY")
    assert m["spend"] == 500 and m["cpl"] == 500


# --------------------------------------------------------------------------- #
# State + labels
# --------------------------------------------------------------------------- #
def test_state_roundtrip_and_rejections(monkeypatch) -> None:
    _enable(monkeypatch)
    cfg = config.platform_config("meta")
    state = connections.sign_state(cfg, USER, now=1000)
    connections.verify_state(cfg, state, USER, now=1100)
    with pytest.raises(connections.ConnectionError_):
        connections.verify_state(cfg, state, "someone-else", now=1100)
    with pytest.raises(connections.ConnectionError_):
        connections.verify_state(cfg, state, USER, now=1000 + connections.STATE_TTL_S + 1)
    with pytest.raises(connections.ConnectionError_):
        connections.verify_state(cfg, state[:-3] + "AAA", USER, now=1100)


def test_label_roundtrip() -> None:
    acct = AccountRef(account_id="act_123", identity_id="456", currency="EUR")
    label = connections.build_label("meta", acct)
    assert connections.parse_label(label) == acct
    assert connections.parse_label("Meta ads") is None


# --------------------------------------------------------------------------- #
# Service with a fake platform client
# --------------------------------------------------------------------------- #
class FakeClient:
    platform = "meta"

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.ready: set[str] = set()
        self.stats: list[AdStats] = []
        self.fail_on: str = ""
        self._n = 0

    def _id(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n}"

    def _log(self, *call) -> None:
        self.calls.append(call)
        if self.fail_on and call[0] == self.fail_on:
            raise AdsApiError("meta", "Meta: (#100) invalid parameter", status_code=400)

    def authorize_url(self, state: str) -> str:
        return f"https://example.test/oauth?state={state}"

    def exchange_code(self, code: str) -> TokenGrant:
        return TokenGrant(access_token="EAAtoken-" + code)

    def list_accounts(self, token):
        return [{"id": "act_1", "name": "Shop", "currency": "USD", "active": True}]

    def list_identities(self, token, account_id):
        return [{"id": "page1", "name": "Shop page"}]

    def create_campaign(self, token, acct, name):
        self._log("campaign", name)
        return self._id("c")

    def create_ad_group(self, token, acct, campaign_id, name, budget, audience):
        self._log("adgroup", campaign_id, budget)
        return self._id("g")

    def upload_video(self, token, acct, url, name):
        self._log("video", url)
        return self._id("v")

    def video_state(self, token, acct, video_id):
        return VideoState(ready=video_id in self.ready, thumbnail_url="https://cdn.test/t.jpg")

    def create_ad(self, token, acct, group_id, creative):
        self._log("ad", group_id, creative.landing_url)
        return {"ad_id": "ad-" + group_id, "creative_id": "cr-" + group_id}

    def set_campaign_status(self, token, acct, cid, active):
        self._log("campaign_status", cid, active)

    def set_ad_group_status(self, token, acct, gid, active):
        self._log("group_status", gid, active)

    def set_ad_group_budget(self, token, acct, gid, budget):
        self._log("group_budget", gid, budget)

    def campaign_status(self, token, acct, cid):
        return "active"

    def campaign_stats(self, token, acct, cid):
        return list(self.stats)


@pytest.fixture()
def env(monkeypatch):
    _clear_env(monkeypatch)
    _enable(monkeypatch, "meta")
    monkeypatch.setenv("SOCIAL_TOKEN_KEY", "test-key-for-ads")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory.begin() as s:
        s.add(User(id=USER, email="u1@x.com"))
        s.add(User(id="u2", email="u2@x.com"))
        angle = {"id": "a1", "kind": "offer", "hook": "Stop wasting money.", "offer": "20% off", "cta": "Shop now"}
        s.add(AdStudioProject(id=PROJECT, user_id=USER, title="Blender", source_url="https://shop.example/blender",
                              language="en", product={"title": "Blender"}, angles=[angle], images=[]))
        s.flush()
        for vid, status in (("v1", "done"), ("v2", "done"), ("v3", "rendering")):
            s.add(AdVariant(id=vid, project_id=PROJECT, user_id=USER, angle_id="a1", format="showcase", aspect="9:16",
                            status=status, script="x", spec={"angle": angle}, output_key=f"uploads/{vid}.mp4",
                            poster_key=f"uploads/{vid}.jpg"))

    class R2:
        def presign_result_get(self, key, download_name=None):
            return f"https://r2.test/{key}"

    monkeypatch.setattr("app.domains.adstudio.views._r2", lambda: R2())
    fake = FakeClient()
    monkeypatch.setattr(service, "client_for", lambda platform: fake)
    return factory, fake


def _connect(factory, fake) -> None:
    with factory.begin() as s:
        state = connections.sign_state(config.platform_config("meta"), USER)
        service.finish_connect(s, USER, "meta", "code1", state)
        service.choose_account(s, USER, "meta", "act_1", "page1", "USD")


def _launch(factory, **overrides):
    req = service.LaunchRequest(project_id=PROJECT, platform="meta", variant_ids=("v1", "v2"),
                                daily_budget_minor=overrides.pop("budget", 2000), audience=Audience(), **overrides)
    with factory.begin() as s:
        return service.launch(s, USER, req)


def test_connect_stores_encrypted_token(env) -> None:
    factory, fake = env
    _connect(factory, fake)
    with factory.begin() as s:
        row = s.query(marketplace.ProviderKey).filter_by(user_id=USER, provider_key="meta_ads", status="active").one()
        assert "EAAtoken" not in row.encrypted_secret and row.scope == "ads"
        assert "acct=act_1" in row.label and "ident=page1" in row.label
        detail = service.connection_detail(s, USER, "meta")
        assert detail["connected"] and detail["ready"] and detail["accounts"][0]["id"] == "act_1"
        assert "token" not in json.dumps({k: v for k, v in detail.items() if k != "token_hint"})


def test_launch_requires_connection(env) -> None:
    factory, _ = env
    with pytest.raises(service.AdsError) as err:
        _launch(factory)
    assert err.value.status_code == 409


def test_launch_rejects_unfinished_and_low_budget(env) -> None:
    factory, fake = env
    _connect(factory, fake)
    with pytest.raises(service.AdsError) as err:
        _launch(factory, budget=150)
    assert err.value.status_code == 400 and "at least 200" in err.value.message
    req = service.LaunchRequest(project_id=PROJECT, platform="meta", variant_ids=("v3",), daily_budget_minor=500,
                                audience=Audience())
    with factory.begin() as s, pytest.raises(service.AdsError) as err2:
        service.launch(s, USER, req)
    assert err2.value.status_code == 409


def test_launch_sync_optimize_flow(env) -> None:
    factory, fake = env
    _connect(factory, fake)
    key, rows = _launch(factory)
    assert [c[0] for c in fake.calls] == ["campaign", "adgroup", "video", "adgroup", "video"]
    assert [c[2] for c in fake.calls if c[0] == "adgroup"] == [1000, 1000]
    view = reporting.campaign_view(key, rows)
    assert view["status"] == "paused" and len(view["creatives"]) == 2
    assert all(c["phase"] == "processing" for c in view["creatives"])

    with factory.begin() as s, pytest.raises(service.AdsError):
        service.set_status(s, USER, key, True)  # nothing live yet

    fake.ready = {"v3", "v5"}
    with factory.begin() as s:
        rows = optimizer.sync(s, USER, key)
    assert {i["phase"] for _, i in rows} == {"live"}
    assert all(c[2] == "https://shop.example/blender" for c in fake.calls if c[0] == "ad")

    with factory.begin() as s:
        service.set_status(s, USER, key, True)
    fake.stats = [AdStats("ad-g2", 3000, 20000, 600, None), AdStats("ad-g4", 3000, 20000, 150, None)]
    fake.calls.clear()
    now = datetime.now(timezone.utc) + timedelta(days=2)
    with factory.begin() as s:
        rows = optimizer.sync(s, USER, key, now=now)
    view = reporting.campaign_view(key, rows)
    assert view["metrics"]["impressions"] == 40000 and view["metrics"]["spend"] == 60.0
    assert view["metrics"]["cpl"] is None
    assert view["allocation"]["conclusive"] and view["allocation"]["metric"] == "ctr"
    assert ("group_budget", "g2", 2000) in fake.calls
    assert ("group_status", "g4", False) in fake.calls


def test_other_user_cannot_see_campaign(env) -> None:
    factory, fake = env
    _connect(factory, fake)
    key, _ = _launch(factory)
    with factory.begin() as s:
        assert store.campaign_rows(s, "u2", key) == []
        with pytest.raises(service.AdsError) as err:
            optimizer.sync(s, "u2", key)
    assert err.value.status_code == 404


def test_partial_failure_keeps_created_objects(env) -> None:
    factory, fake = env
    _connect(factory, fake)
    fake.fail_on = "video"
    req = service.LaunchRequest(project_id=PROJECT, platform="meta", variant_ids=("v1",), daily_budget_minor=500,
                                audience=Audience())
    with factory.begin() as s:
        with pytest.raises(service.AdsError) as err:
            service.launch(s, USER, req)
        assert "partial campaign kept" in err.value.message
    with factory.begin() as s:
        camps = store.campaigns(s, USER)
    assert len(camps) == 1
    (_, rows), = camps.items()
    assert rows[0][1]["campaign"]["status"] == "error" and rows[0][1]["ad_group_id"]


def test_leads_metric_falls_back_to_ctr_without_lead_events() -> None:
    class V:
        def __init__(self, i):
            self.id = i

    rows = [(V("a"), {"phase": "live", "stats": {"impressions": 100, "clicks": 5, "leads": None}})]
    arms, metric = optimizer.arms_for(rows, "leads")
    assert metric == "ctr" and arms[0].trials == 100
    rows[0][1]["stats"]["leads"] = 2
    arms, metric = optimizer.arms_for(rows, "leads")
    assert metric == "leads" and arms[0].trials == 5 and arms[0].successes == 2


# --------------------------------------------------------------------------- #
# HTTP clients against a mock transport
# --------------------------------------------------------------------------- #
def test_meta_client_payloads(monkeypatch) -> None:
    _enable(monkeypatch)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path.endswith("/campaigns"):
            return httpx.Response(200, json={"id": "c1"})
        if path.endswith("/adsets"):
            return httpx.Response(200, json={"id": "s1"})
        if path.endswith("/insights"):
            return httpx.Response(200, json={"data": [{"ad_id": "a1", "spend": "12.50", "impressions": "1000",
                                                       "inline_link_clicks": "30",
                                                       "actions": [{"action_type": "lead", "value": "3"}]}]})
        return httpx.Response(400, json={"error": {"message": "Unsupported", "code": 100}})

    client = MetaAdsClient(config.platform_config("meta"), http=httpx.Client(transport=httpx.MockTransport(handler)))
    acct = AccountRef("act_9", "page9", "USD")
    assert client.create_campaign("tok", acct, "Launch") == "c1"
    assert client.create_ad_group("tok", acct, "c1", "set", 700, Audience(("US", "GB"), 25, 44, "female")) == "s1"
    form = dict(httpx.QueryParams(seen[1].content.decode()))
    assert form["daily_budget"] == "700" and form["campaign_id"] == "c1"
    targeting = json.loads(form["targeting"])
    assert targeting["geo_locations"]["countries"] == ["US", "GB"] and targeting["genders"] == [2]
    assert "appsecret_proof" in form and seen[1].headers["Authorization"] == "Bearer tok"
    stats = client.campaign_stats("tok", acct, "c1")
    assert stats == [AdStats("a1", 1250, 1000, 30, 3)]
    with pytest.raises(AdsApiError) as err:
        client.set_campaign_status("tok", acct, "c1", True)
    assert "Unsupported" in err.value.message


def test_tiktok_client_payloads(monkeypatch) -> None:
    _enable(monkeypatch, "tiktok")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path.endswith("/adgroup/create/"):
            return httpx.Response(200, json={"code": 0, "data": {"adgroup_id": "g1"}})
        if path.endswith("/report/integrated/get/"):
            return httpx.Response(200, json={"code": 0, "data": {"list": [
                {"dimensions": {"ad_id": "x"}, "metrics": {"spend": "20.00", "impressions": "500", "clicks": "10", "conversion": "2"}}]}})
        return httpx.Response(200, json={"code": 40001, "message": "Access token is invalid"})

    client = TikTokAdsClient(config.platform_config("tiktok"), http=httpx.Client(transport=httpx.MockTransport(handler)))
    acct = AccountRef("adv1", "id1", "USD")
    assert client.create_ad_group("tok", acct, "c1", "g", 2500, Audience(("TR",), 18, 34, "all")) == "g1"
    body = json.loads(seen[0].content)
    assert body["budget"] == 25.0 and body["location_ids"] == ["298795"]
    assert body["age_groups"] == ["AGE_18_24", "AGE_25_34"] and seen[0].headers["Access-Token"] == "tok"
    assert client.campaign_stats("tok", acct, "c1") == [AdStats("x", 2000, 500, 10, 2)]
    with pytest.raises(AdsApiError) as err:
        client.set_campaign_status("tok", acct, "c1", True)
    assert err.value.status_code == 401


def test_tiktok_targeting_helpers() -> None:
    assert age_groups(18, 65) == ["AGE_18_24", "AGE_25_34", "AGE_35_44", "AGE_45_54", "AGE_55_100"]
    assert location_ids(("US", "123")) == ["6252001", "123"]
    with pytest.raises(AdsApiError):
        location_ids(("ZZ",))


def test_status_route_is_public_and_reports_gate(monkeypatch) -> None:
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    from app.controllers.v1 import ads as ads_controller

    _clear_env(monkeypatch)
    app = FastAPI()
    app.include_router(ads_controller.router)
    body = TestClient(app).get("/api/v1/ads/status").json()
    assert body["data"]["enabled"] is False
    assert body["data"]["reason"] == "Ads not enabled — requires Meta/TikTok app approval"
