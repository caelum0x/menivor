"""Ad fatigue: frequency, CTR decay, CPA drift, score per creative, and "make variations" behind approval."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.domains.ad_fatigue import fatigue, service
from app.domains.ad_fatigue import router as fatigue_router
from app.domains.brand_agent.models import AgentAction
from app.domains.integrations.models import IntegrationAdAccount, IntegrationAdMetric, IntegrationConnection
from app.domains.integrations.scope import resolve
from tests.reelforge._wave2_support import H, OTHER, client_for, data, make_env

TODAY = date(2026, 10, 6)


def _day(i, **kw):
    return fatigue.Day(day=(TODAY - timedelta(days=13 - i)).isoformat(), **kw)


def _tired():
    """CTR halves, frequency climbs past 4, CPA doubles."""
    early = [_day(i, impressions=2000, clicks=40, spend=40.0, conversions=4, reach=1600) for i in range(11)]
    late = [_day(11 + i, impressions=2000, clicks=18, spend=40.0, conversions=2, reach=440) for i in range(3)]
    return early + late


def test_tired_creative_scores_fatigued_with_reasons():
    out = fatigue.analyze(_tired())
    assert out["frequency"] == pytest.approx(4.55, abs=0.01)
    assert out["ctr_decay"] == pytest.approx(0.55, abs=0.01)
    assert out["cpa_drift"] == pytest.approx(1.0, abs=0.01)
    assert out["score"] == 100 and out["status"] == "fatigued"
    assert any("CTR down 55%" in r for r in out["reasons"]) and any("Frequency" in r for r in out["reasons"])
    assert len(out["series"]) == 14


def test_fresh_creative_and_missing_metrics_are_not_invented():
    rows = [_day(i, impressions=1500, clicks=30, spend=20.0, conversions=None, reach=None) for i in range(6)]
    out = fatigue.analyze(rows)
    assert out["frequency"] is None and out["cpa_drift"] is None  # not reported -> None, never 0
    assert out["reported"] == ["ctr_decay"] and out["score"] == 0 and out["status"] == "fresh"


def test_not_enough_data():
    out = fatigue.analyze([_day(i, impressions=100, clicks=5) for i in range(3)])
    assert out["status"] == "not_enough_data" and out["score"] is None


def test_cpa_drift_when_recent_days_convert_nothing():
    early = [_day(i, impressions=2000, clicks=40, spend=10.0, conversions=2) for i in range(5)]
    late = [_day(5 + i, impressions=2000, clicks=40, spend=10.0, conversions=0) for i in range(3)]
    assert fatigue.cpa_drift(early, late) == 1.0


@pytest.fixture()
def env(monkeypatch):
    env = make_env(monkeypatch)
    with env.db.scope() as s:
        conn = IntegrationConnection(owner_scope=f"user:{env.uid}", user_id=env.uid, kind="ads", provider="meta",
                                     access_token_enc="enc")
        s.add(conn)
        s.flush()
        account = IntegrationAdAccount(connection_id=conn.id, owner_scope=f"user:{env.uid}", provider="meta",
                                       external_id="act_1", name="Brewly Ads", currency="USD")
        s.add(account)
        s.flush()
        env.account_id = account.id
        for d in _tired():
            s.add(IntegrationAdMetric(ad_account_id=account.id, owner_scope=f"user:{env.uid}", provider="meta",
                                      day=d.day, entity_id="ad-tired", entity_name="Summer UGC", currency="USD",
                                      spend_minor=int(d.spend * 100), impressions=d.impressions, clicks=d.clicks,
                                      conversions=d.conversions, reach=d.reach))
        for i in range(6):
            s.add(IntegrationAdMetric(ad_account_id=account.id, owner_scope=f"user:{env.uid}", provider="meta",
                                      day=(TODAY - timedelta(days=5 - i)).isoformat(), entity_id="ad-fresh",
                                      entity_name="New hook", currency="USD", spend_minor=1000, impressions=1500,
                                      clicks=45, conversions=3, reach=1400))
    return env


def test_report_ranks_tired_creatives_first_and_respects_scope(env):
    with env.db.scope() as s:
        out = service.report(s, resolve(s, env.uid), today=TODAY)
        assert [c["entity_id"] for c in out["creatives"]] == ["ad-tired", "ad-fresh"]
        assert out["creatives"][0]["status"] == "fatigued" and out["counts"]["fatigued"] == 1
        assert out["creatives"][1]["status"] == "fresh"
        assert service.report(s, resolve(s, env.other), today=TODAY)["creatives"] == []


def test_make_variations_only_queues_a_pending_batch(env):
    with env.db.scope() as s:
        out = service.make_variations(s, resolve(s, env.uid), ad_account_id=env.account_id, entity_id="ad-tired",
                                      today=TODAY)
        action = out["action"]
        assert action["status"] == "pending" and action["kind"] == "routine_batch"
        assert action["payload"]["count"] == 3 and "CTR down" in action["payload"]["prompt"]
        assert action["credits_estimate"] == 15  # 3 videos x 5 credits, shown before approval
        assert s.query(AgentAction).count() == 1
    assert env.deps.generation.calls == []


def test_http_report_and_variations(env, monkeypatch):
    client = client_for(fatigue_router, monkeypatch=monkeypatch, db=env.db)
    monkeypatch.setattr(service.metrics, "window", lambda days, today=None: (TODAY - timedelta(days=days - 1), TODAY))
    out = data(client.get("/api/v1/ad-fatigue?days=14", headers=H))
    assert out["creatives"][0]["entity_id"] == "ad-tired"
    made = data(client.post("/api/v1/ad-fatigue/variations", headers=H,
                            json={"ad_account_id": env.account_id, "entity_id": "ad-tired"}))
    assert made["action"]["status"] == "pending"
    missing = client.post("/api/v1/ad-fatigue/variations", headers=OTHER,
                          json={"ad_account_id": env.account_id, "entity_id": "ad-tired"})
    assert missing.status_code == 404
