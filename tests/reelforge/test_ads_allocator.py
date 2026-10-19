"""Cross-network allocator: deterministic engine, stats, proposals, approvals, apply, report."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.ads import service as ads_service
from app.domains.ads import store
from app.domains.ads.allocation_models import AdAllocationProposal
from app.domains.ads.allocator import engine, service
from app.domains.ads.allocator.engine import NetworkStats
from app.domains.ads.allocator.stats import ManualNetwork, collect
from app.domains.adstudio.models import AdStudioProject, AdVariant
from app.domains.approvals.models import ApprovalItem
from app.models.db import marketplace, models  # noqa: F401 - register tables
from app.models.db.base import Base
from app.models.db.models import User

USER = "u1"
NOW = datetime(2026, 9, 25, 9, 0, tzinfo=timezone.utc)


def _plan(stats, **kw):
    params = {"seed": 42, "max_step": 0.2, "min_share": 0.1, "min_results": 30}
    params.update(kw)
    return engine.plan_split(stats, **params)


# --------------------------------------------------------------------------- #
# Engine (pure, fixture stats)
# --------------------------------------------------------------------------- #
def test_cheaper_network_gains_budget_within_step_cap() -> None:
    stats = [NetworkStats("meta", spend_minor=100_000, results=500, current_daily_minor=5000),
             NetworkStats("tiktok", spend_minor=100_000, results=200, current_daily_minor=5000)]
    plan = _plan(stats)
    assert plan.method == "thompson"
    assert plan.p_best["meta"] > 0.99
    assert plan.proposed == {"meta": 0.7, "tiktok": 0.3}
    assert plan.max_delta == pytest.approx(0.2)
    assert "Capped at 20%" in plan.reason
    assert sum(plan.proposed.values()) == pytest.approx(1.0)


def test_plan_is_deterministic_for_a_seed() -> None:
    stats = [NetworkStats("meta", 20_000, 40, current_daily_minor=3000),
             NetworkStats("tiktok", 20_000, 35, current_daily_minor=3000),
             NetworkStats("organic_boost", 5000, 12, current_daily_minor=1000, source="manual")]
    assert _plan(stats) == _plan(stats)
    assert _plan(stats, seed=1).p_best != _plan(stats, seed=2).p_best


def test_min_share_floor_keeps_exploring() -> None:
    stats = [NetworkStats("meta", 1_000_000, 10_000, current_daily_minor=1000),
             NetworkStats("tiktok", 1_000_000, 100, current_daily_minor=1000)]
    plan = _plan(stats, max_step=1.0)
    assert plan.proposed["tiktok"] == pytest.approx(0.1)
    assert plan.proposed["meta"] == pytest.approx(0.9)


def test_no_results_holds_current_split() -> None:
    stats = [NetworkStats("meta", 5000, 0, current_daily_minor=3000), NetworkStats("tiktok", 0, 0, current_daily_minor=1000)]
    plan = _plan(stats)
    assert plan.method == "rules" and plan.max_delta == 0
    assert plan.proposed == {"meta": 0.75, "tiktok": 0.25}
    assert "unknown, not zero" in plan.warnings["meta"]
    assert "No spend" in plan.warnings["tiktok"]


def test_single_network_keeps_everything() -> None:
    plan = _plan([NetworkStats("meta", 5000, 50, current_daily_minor=2000)])
    assert plan.proposed == {"meta": 1.0} and plan.method == "rules"


def test_small_sample_is_flagged() -> None:
    s = NetworkStats("meta", 5000, 7)
    assert "Only 7 results" in engine.sample_warning(s, 30)
    assert engine.sample_warning(NetworkStats("meta", 5000, 40), 30) == ""
    assert engine.cost_per_result_minor(NetworkStats("meta", 5000, 0)) is None
    assert engine.cost_per_result_minor(s) == pytest.approx(714.29)


def test_split_budget_is_exact() -> None:
    assert engine.split_budget(1001, {"a": 0.3333, "b": 0.3333, "c": 0.3334}) == {"a": 333, "b": 333, "c": 335}
    assert sum(engine.split_budget(9_999, {"a": 0.7, "b": 0.3}).values()) == 9_999


def test_money_conversions() -> None:
    assert service.to_micros(1234, "USD") == 12_340_000
    assert service.to_minor(12_340_000, "USD") == 1234
    assert service.to_micros(500, "JPY") == 500_000_000


# --------------------------------------------------------------------------- #
# Stats + service against in-memory SQLite with a fake platform client
# --------------------------------------------------------------------------- #
class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def set_ad_group_budget(self, token, acct, gid, budget):
        self.calls.append(("group_budget", gid, budget))

    def set_ad_group_status(self, token, acct, gid, active):
        self.calls.append(("group_status", gid, active))


def _campaign(s, key: str, platform: str, *, daily: int, spend: int, clicks: int, impressions: int,
              currency: str = "USD", status: str = store.STATUS_ACTIVE, leads=None, variant: str = "") -> None:
    variant = variant or f"v{key}"
    project = f"p{key}".ljust(32, "0")
    s.add(AdStudioProject(id=project, user_id=USER, title="P", source_url="https://shop.example/p", language="en",
                          product={}, angles=[], images=[]))
    s.flush()
    camp = {"key": key, "platform": platform, "name": f"{platform} {key}", "account_id": "act_1", "identity_id": "",
            "currency": currency, "daily_budget_minor": daily, "status": status, "external_id": f"c{key}",
            "optimize_for": "ctr", "created_at": "2026-09-01T00:00:00+00:00"}
    item = {"order": 0, "campaign": camp, "phase": store.PHASE_LIVE, "budget_minor": daily, "active": True,
            "ad_group_id": f"g{key}", "ad_id": f"ad{key}",
            "stats": {"spend_minor": spend, "impressions": impressions, "clicks": clicks, "leads": leads}}
    s.add(AdVariant(id=variant, project_id=project, user_id=USER, angle_id="a1", format="showcase", aspect="9:16",
                    status="done", spec={store.SPEC_KEY: {key: item}}))


@pytest.fixture()
def env(monkeypatch):
    for name in ("META", "TIKTOK"):
        monkeypatch.setenv(f"MENIVOR_{name}_APP_ID", "app")
        monkeypatch.setenv(f"MENIVOR_{name}_APP_SECRET", "secret")
    monkeypatch.delenv("MENIVOR_ALLOCATOR_AUTO_APPLY_DELTA", raising=False)
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(eng)
    factory = sessionmaker(bind=eng, expire_on_commit=False, future=True)
    with factory.begin() as s:
        s.add(User(id=USER, email="u1@x.com"))
        s.add(User(id="u2", email="u2@x.com"))
        s.flush()
        _campaign(s, "a" * 16, "meta", daily=5000, spend=100_000, clicks=500, impressions=40_000)
        _campaign(s, "b" * 16, "tiktok", daily=5000, spend=100_000, clicks=200, impressions=60_000)
        _campaign(s, "c" * 16, "tiktok", daily=9000, spend=50_000, clicks=900, impressions=9000, currency="EUR")
    fake = FakeClient()

    class Conn:
        token = "tok"
        account = type("A", (), {"account_id": "act_1"})()

    monkeypatch.setattr(ads_service, "client_for", lambda platform: fake)
    monkeypatch.setattr(ads_service.connections, "load", lambda s, u, p: Conn())
    return factory, fake


def test_collect_uses_dominant_currency_and_common_metric(env) -> None:
    factory, _ = env
    with factory.begin() as s:
        c = collect(s, USER, [ManualNetwork("organic_boost", 20_000, 150, 1000)])
    assert c.currency == "USD" and c.metric == "clicks"
    by = {n.network: n for n in c.networks}
    assert by["meta"].results == 500 and by["tiktok"].results == 200
    assert by["organic_boost"].source == "manual"
    assert [e["currency"] for e in c.excluded] == ["EUR"]


def test_propose_queues_approval_and_is_idempotent_per_day(env) -> None:
    factory, fake = env
    with factory.begin() as s:
        view = service.propose(s, USER, now=NOW)
    assert view["status"] == "proposed" and view["total_daily_minor"] == 10_000
    shares = {r["network"]: r["proposed_share"] for r in view["networks"]}
    assert shares == {"meta": 0.7, "tiktok": 0.3}
    assert fake.calls == []  # nothing applied without approval
    with factory.begin() as s:
        item = s.query(ApprovalItem).one()
        assert item.source == "ad_budget" and item.status == "pending" and item.risk == "high"
        assert item.external_ref == view["id"]
        again = service.propose(s, USER, total_daily_minor=20_000, now=NOW)
        assert again["id"] == view["id"] and again["total_daily_minor"] == 20_000
        assert s.query(ApprovalItem).count() == 1 and s.query(AdAllocationProposal).count() == 1


def test_approve_applies_budgets_through_optimizer(env) -> None:
    factory, fake = env
    with factory.begin() as s:
        pid = service.propose(s, USER, now=NOW)["id"]
    with factory.begin() as s:
        view = service.decide(s, USER, pid, approve=True, now=NOW)
    assert view["status"] == "applied"
    assert ("group_budget", "g" + "a" * 16, 7000) in fake.calls
    assert ("group_budget", "g" + "b" * 16, 3000) in fake.calls
    with factory.begin() as s:
        rows = store.campaign_rows(s, USER, "a" * 16)
        assert rows[0][1]["campaign"]["daily_budget_minor"] == 7000
        assert s.query(ApprovalItem).one().status == "executed"
        with pytest.raises(service.AllocatorError) as err:
            service.propose(s, USER, now=NOW)
    assert err.value.status_code == 409


def test_reject_and_edited_split(env) -> None:
    factory, fake = env
    with factory.begin() as s:
        pid = service.propose(s, USER, now=NOW)["id"]
        with pytest.raises(service.AllocatorError):
            service.decide(s, USER, pid, approve=True, split={"meta": 0.9, "tiktok": 0.3})
        view = service.decide(s, USER, pid, approve=True, split={"meta": 0.6, "tiktok": 0.4}, now=NOW)
    assert view["status"] == "applied"
    assert ("group_budget", "g" + "a" * 16, 6000) in fake.calls
    with factory.begin() as s:
        assert s.query(ApprovalItem).one().status == "executed"
        s.query(AdAllocationProposal).delete()
        s.query(ApprovalItem).delete()
        pid = service.propose(s, USER, now=NOW)["id"]
        assert service.decide(s, USER, pid, approve=False, note="not now")["status"] == "rejected"
        assert s.query(ApprovalItem).one().status == "rejected"


def test_platform_disabled_records_failure(env, monkeypatch) -> None:
    factory, _ = env

    def closed(platform):
        raise ads_service.AdsError(503, "Ads not enabled")

    monkeypatch.setattr(ads_service, "client_for", closed)
    with factory.begin() as s:
        pid = service.propose(s, USER, now=NOW)["id"]
        view = service.decide(s, USER, pid, approve=True, now=NOW)
    assert view["status"] == "failed" and "Ads not enabled" in view["error"]
    with factory.begin() as s:
        assert store.campaign_rows(s, USER, "a" * 16)[0][1]["campaign"]["daily_budget_minor"] == 5000
        assert s.query(ApprovalItem).one().status == "failed"


def test_auto_apply_only_below_delta(env, monkeypatch) -> None:
    factory, fake = env
    monkeypatch.setenv("MENIVOR_ALLOCATOR_AUTO_APPLY_DELTA", "0.1")
    with factory.begin() as s:
        assert service.propose(s, USER, now=NOW)["status"] == "proposed"  # 20-point move > 10
    assert fake.calls == []
    monkeypatch.setenv("MENIVOR_ALLOCATOR_MAX_STEP", "0.05")
    with factory.begin() as s:
        view = service.propose(s, USER, now=NOW)
    assert view["status"] == "applied" and view["max_delta"] == pytest.approx(0.05)


def test_manual_network_is_reused_and_marked_apply_by_hand(env) -> None:
    factory, _ = env
    with factory.begin() as s:
        view = service.propose(s, USER, manual=[ManualNetwork("organic_boost", 10_000, 100, 2000)], now=NOW)
        assert {r["network"] for r in view["networks"]} == {"meta", "tiktok", "organic_boost"}
        assert view["total_daily_minor"] == 12_000
        report = service.report(s, USER)
    assert report["cheapest"] == "organic_boost"
    organic = next(r for r in report["networks"] if r["network"] == "organic_boost")
    assert organic["source"] == "manual" and organic["ctr"] is None
    with factory.begin() as s:
        view = service.decide(s, USER, view["id"], approve=True, now=NOW)
    manual = next(r for r in view["apply_result"]["networks"] if r["network"] == "organic_boost")
    assert manual["manual"] and "by hand" in manual["detail"]


def test_report_warns_and_is_owner_scoped(env) -> None:
    factory, _ = env
    with factory.begin() as s:
        rep = service.report(s, USER)
        other = service.report(s, "u2")
    by = {r["network"]: r for r in rep["networks"]}
    assert by["meta"]["cost_per_result_minor"] == 200.0 and by["tiktok"]["cost_per_result_minor"] == 500.0
    assert rep["cheapest"] == "meta" and rep["latest"] is None
    assert other["networks"] == [] and other["cheapest"] is None
    with factory.begin() as s, pytest.raises(service.AllocatorError) as err:
        service.propose(s, "u2", now=NOW)
    assert err.value.status_code == 409


def test_feed_approved_proposal_is_applied_once(env) -> None:
    factory, fake = env
    with factory.begin() as s:
        pid = service.propose(s, USER, now=NOW)["id"]
        s.get(AdAllocationProposal, pid).status = "approved"  # what the approvals feed adapter does
        with pytest.raises(service.AllocatorError):
            service.apply_approved(s, "u2", pid)
        assert service.approved_waiting(s) == [(USER, pid)]
    with factory.begin() as s:
        view = service.apply_approved(s, USER, pid, now=NOW)
    assert view["status"] == "applied"
    assert ("group_budget", "g" + "a" * 16, 7000) in fake.calls
    with factory.begin() as s:
        assert service.approved_waiting(s) == []
        with pytest.raises(service.AllocatorError) as err:
            service.apply_approved(s, USER, pid)
    assert err.value.status_code == 409
