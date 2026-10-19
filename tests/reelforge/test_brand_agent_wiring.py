"""Brand Agent ports wired to the real Ad Clone service and the Integrations contract.

One in-memory SQLite holds the Brand Agent, Integrations and core tables. The
Integrations side runs the real contract (scope, accounts, metrics ranking); the
Ad Clone side runs the real plan builder, presets and engine pricing. Only the
video download/analysis step is replaced by the checked-in clone brief fixture.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.domains.adclone import agent_port as adclone_port
from app.domains.adclone import planschema, presets, service as adclone_service
from app.domains.adclone.linkresolve import LinkError
from app.domains.adclone.schemas import CloneBrief
from app.domains.brand_agent import agent, gate, inspirations, library, sessions, setup_flow, spaces
from app.domains.brand_agent.ports import ad_clone as ad_clone_ports
from app.domains.brand_agent.ports import integrations as integrations_ports
from app.domains.brand_agent.ports.base import PortUnavailable
from app.domains.brand_agent.router import _connectors
from app.domains.integrations import agent_port as integrations_port
from app.domains.integrations import contract
from app.domains.integrations.errors import IntegrationError
from app.domains.integrations.models import IntegrationAdAccount, IntegrationAdMetric, IntegrationConnection
from tests.reelforge._brand_agent_support import SITE_URL, make_deps
from tests.reelforge._integrations_fakes import add_user, make_db

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "adclone" / "brief-tiktok-price-shock.json"
TIKTOK = "https://www.tiktok.com/@brand/video/7300000000000000000"
OXHAN = presets.load("oxhan")


@pytest.fixture()
def db(monkeypatch):
    factory = make_db()
    monkeypatch.setattr(contract, "get_session", factory.scope)
    return factory


@pytest.fixture()
def owner(db):
    return add_user(db, "owner@example.com")


@pytest.fixture()
def brief() -> CloneBrief:
    return CloneBrief.model_validate(json.loads(FIXTURE.read_text()))


@pytest.fixture()
def adclone_env(monkeypatch, tmp_path):
    monkeypatch.setenv(adclone_service.ENABLED_ENV, "1")
    monkeypatch.setenv(adclone_service.LLM_ENV, "0")
    monkeypatch.setenv("ADCLONE_MJ_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.delenv(adclone_port.PRESET_ENV, raising=False)


def _meta_account(db, user_id, *, external_id="act_77", name="Shop US", status="active") -> str:
    with db.scope() as s:
        conn = IntegrationConnection(owner_scope=f"user:{user_id}", user_id=user_id, kind="ads", provider="meta",
                                     access_token_enc="enc", display_name="Meta")
        s.add(conn)
        s.flush()
        acct = IntegrationAdAccount(connection_id=conn.id, owner_scope=f"user:{user_id}", provider="meta",
                                    external_id=external_id, name=name, currency="USD", status=status)
        s.add(acct)
        s.flush()
        return acct.id


def _metrics(db, account_id, rows):
    day = date.today().isoformat()
    with db.scope() as s:
        acct = s.get(IntegrationAdAccount, account_id)
        for entity, name, spend, imp, clicks, conv, value in rows:
            s.add(IntegrationAdMetric(ad_account_id=account_id, owner_scope=acct.owner_scope, provider="meta",
                                      day=day, entity_id=entity, entity_name=name, group_id="", campaign_id="c1",
                                      spend_minor=spend, impressions=imp, clicks=clicks, conversions=conv,
                                      conversion_value_minor=value, currency="USD"))


def _agent_session(db, owner):
    with db.scope() as s:
        space = spaces.ensure_default(s, owner)
        return space.id, sessions.create(s, owner, space.id).id


def _run_setup_to_meta(db, deps, owner, sid):
    with db.scope() as s:
        agent.handle_text(s, deps, owner, sid, f"set up my brand from my website: {SITE_URL}")
    for step in (setup_flow.STEP_POSITIONING, setup_flow.STEP_PRODUCT, setup_flow.STEP_MARKET,
                 setup_flow.STEP_VOICE):
        with db.scope() as s:
            agent.handle_chip(s, deps, owner, sid, step=step, choice="yes")


# --------------------------------------------------------------------------- default lookup
def test_default_port_lookup_finds_both_adapters(monkeypatch):
    monkeypatch.delenv(ad_clone_ports.ENV, raising=False)
    monkeypatch.delenv(integrations_ports.ENV, raising=False)
    assert isinstance(ad_clone_ports.get_port(), adclone_port.AdCloneAgentPort)
    assert isinstance(integrations_ports.get_port(), integrations_port.IntegrationsAgentPort)


# --------------------------------------------------------------------------- integrations adapter
def test_accounts_and_top_creatives_come_from_the_contract(db, owner):
    account = _meta_account(db, owner)
    _metrics(db, account, [("ad-low", "Low ROAS", 10_000, 1000, 10, 1.0, 5_000),
                           ("ad-high", "High ROAS", 10_000, 1000, 30, 3.0, 40_000)])
    port = integrations_port.IntegrationsAgentPort()

    accounts = port.list_connected_accounts(owner)
    assert [(a["platform"], a["account_id"], a["name"], a["status"]) for a in accounts] == [
        ("meta", account, "Shop US", "active")]

    top = port.top_performing_creatives(owner, platform="meta", limit=5)
    assert [c["id"] for c in top] == ["ad-high", "ad-low"]
    assert top[0]["title"] == "High ROAS" and top[0]["metrics"]["roas"] == 4.0
    assert top[0]["url"].startswith("https://adsmanager.facebook.com/") and "act=77" in top[0]["url"]
    assert "selected_ad_ids=ad-high" in top[0]["url"]
    assert inspirations.kind_of(top[0]["url"]) == "meta_ad"


def test_not_connected_and_no_results_are_plain_reasons(db, owner):
    port = integrations_port.IntegrationsAgentPort()
    assert port.list_connected_accounts(owner) == []
    with pytest.raises(PortUnavailable) as err:
        port.top_performing_creatives(owner, platform="meta", limit=5)
    assert "Meta Ads is not connected" in err.value.reason
    _meta_account(db, owner)
    with pytest.raises(PortUnavailable) as err:
        port.top_performing_creatives(owner, platform="meta", limit=5)
    assert "No ad results" in err.value.reason


def test_other_users_accounts_are_never_visible(db, owner):
    other = add_user(db, "other@example.com")
    _metrics(db, _meta_account(db, other), [("ad-x", "Theirs", 100, 10, 1, 1.0, 500)])
    port = integrations_port.IntegrationsAgentPort()
    assert port.list_connected_accounts(owner) == []
    with pytest.raises(PortUnavailable):
        port.top_performing_creatives(owner, platform="meta", limit=5)


def test_contract_refusals_become_port_unavailable():
    class Refusing:
        def list_connected_accounts(self, user_id):
            raise IntegrationError(403, "You are not a member of this workspace.")

        def ask_campaign_question(self, user_id, question, **kw):
            raise IntegrationError(503, "Integrations storage is unavailable.")

    port = integrations_port.IntegrationsAgentPort(Refusing())
    assert port.list_connected_accounts("u1") == []
    with pytest.raises(PortUnavailable) as err:
        port.top_performing_creatives("u1", platform="meta", limit=3)
    assert err.value.reason == "You are not a member of this workspace."
    with pytest.raises(PortUnavailable) as err:
        port.ask_campaign_question("u1", "how are my ads?")
    assert "unavailable" in err.value.reason


def test_report_and_ads_agent_go_through_the_contract_rules(db, owner):
    account = _meta_account(db, owner)
    _metrics(db, account, [("ad-1", "One", 5_000, 500, 5, 1.0, 2_000)])
    port = integrations_port.IntegrationsAgentPort()
    report = port.pull_report(owner, ad_account_id=account)
    assert isinstance(report, dict) and report
    with pytest.raises(PortUnavailable) as err:  # the Ads agent's plan gate reaches the user as-is
        port.ask_campaign_question(owner, "Which ad is best?")
    assert "Pro" in err.value.reason


def test_setup_meta_step_saves_real_top_ads_to_inspirations(db, owner):
    _metrics(db, _meta_account(db, owner), [("ad-1", "Winner", 10_000, 1000, 40, 4.0, 60_000),
                                            ("ad-2", "Runner up", 10_000, 1000, 20, 2.0, 20_000)])
    deps = make_deps(integrations=integrations_port.IntegrationsAgentPort())
    space_id, sid = _agent_session(db, owner)
    _run_setup_to_meta(db, deps, owner, sid)
    with db.scope() as s:
        out = agent.handle_chip(s, deps, owner, sid, step=setup_flow.STEP_META, choice="connect")
    assert "Saved 2 top-performing ads from Meta Ads" in out[-1]["content"]
    with db.scope() as s:
        items = inspirations.list_items(s, owner, space_id)
    assert {i["title"] for i in items} == {"Winner", "Runner up"}
    assert all(i["source"] == "meta_ads" and i["kind"] == "meta_ad" for i in items)


def test_connectors_panel_reads_the_real_adapters(db, owner, monkeypatch):
    monkeypatch.setenv(adclone_service.ENABLED_ENV, "1")
    _meta_account(db, owner, name="Shop US")
    deps = make_deps(integrations=integrations_port.IntegrationsAgentPort(),
                     ad_clone=adclone_port.AdCloneAgentPort())
    with db.scope() as s:
        panel = {c["id"]: c for c in _connectors(s, owner, deps)}
    assert panel["meta_ads"]["status"] == "connected" and panel["meta_ads"]["detail"] == "Shop US"
    assert panel["ad_clone"]["status"] == "connected"
    monkeypatch.setenv(adclone_service.ENABLED_ENV, "0")
    with db.scope() as s:
        panel = {c["id"]: c for c in _connectors(s, owner, deps)}
    assert panel["ad_clone"] == {"id": "ad_clone", "name": "Ad Clone", "status": "unavailable",
                                 "detail": "Switched off on this server"}


# --------------------------------------------------------------------------- ad clone adapter
def test_clone_builds_a_real_priced_plan_without_spending(adclone_env, brief):
    seen = []

    def analyze(url, *, llm=None):
        seen.append((url, llm))
        return brief

    port = adclone_port.AdCloneAgentPort(analyze=analyze)
    out = port.clone_from_link("u1", TIKTOK, brand={"positioning": {"site": "https://oxhanatelier.com"}},
                               space_id="s1")
    assert seen == [(TIKTOK, None)]  # ADCLONE_USE_LLM=0: no LLM step
    assert out["status"] == adclone_port.STATUS_PLANNED and out["preset"] == "oxhan"
    assert out["job_id"] == f"plan:{out['plans'][0]['slug']}"
    assert out["variations"][0]["ai_video_credits"] > 0 and out["paid_render"] is False
    assert not planschema.validate(out["plans"][0], cta_text=OXHAN["cta"]["text"],
                                   cta_speaker=OXHAN["cta"]["speaker"])
    assert "approve the render" in out["next"]


def test_clone_is_off_without_the_flag_and_needs_a_matching_product(monkeypatch, brief):
    monkeypatch.delenv(adclone_service.ENABLED_ENV, raising=False)
    monkeypatch.delenv(adclone_port.PRESET_ENV, raising=False)
    port = adclone_port.AdCloneAgentPort(analyze=lambda url, llm=None: brief, llm=lambda: None)
    with pytest.raises(PortUnavailable) as err:
        port.clone_from_link("u1", TIKTOK, brand={}, space_id="s1")
    assert err.value.reason == adclone_port.OFF
    monkeypatch.setenv(adclone_service.ENABLED_ENV, "1")
    with pytest.raises(PortUnavailable) as err:
        port.clone_from_link("u1", TIKTOK, brand={"positioning": {"name": "Basepoint"}}, space_id="s1")
    assert err.value.reason.startswith("Ad Clone has no product preset for this brand yet (it has: Oxhan Atelier)")
    monkeypatch.setenv(adclone_port.PRESET_ENV, "oxhan")
    assert port.clone_from_link("u1", TIKTOK, brand={}, space_id="s1")["preset"] == "oxhan"


def test_link_errors_are_shown_plainly(adclone_env):
    def bad_link(url, *, llm=None):
        raise LinkError(422, "That link is not a TikTok or Meta ad.")

    port = adclone_port.AdCloneAgentPort(analyze=bad_link, llm=lambda: None)
    with pytest.raises(PortUnavailable) as err:
        port.clone_from_link("u1", "https://example.com/x", brand={"n": "Oxhan Atelier"}, space_id="s1")
    assert err.value.reason == "That link is not a TikTok or Meta ad."


def test_approved_clone_action_runs_the_real_adapter_and_lands_in_the_library(db, owner, adclone_env, brief,
                                                                            monkeypatch):
    monkeypatch.setenv(adclone_port.PRESET_ENV, "oxhan")
    port = adclone_port.AdCloneAgentPort(analyze=lambda url, llm=None: brief)
    deps = make_deps(ad_clone=port)
    space_id, sid = _agent_session(db, owner)
    _run_setup_to_meta(db, deps, owner, sid)
    with db.scope() as s:
        agent.handle_chip(s, deps, owner, sid, step=setup_flow.STEP_META, choice="skip")
    with db.scope() as s:
        out = agent.handle_text(s, deps, owner, sid, f"clone this ad {TIKTOK}")
    action = next(m["action"] for m in reversed(out) if m.get("action"))
    with db.scope() as s:
        done = gate.decide(s, deps, owner, action["id"], gate.APPROVE)
    assert done["status"] == gate.STATUS_EXECUTED, done
    with db.scope() as s:
        items = library.list_items(s, owner, space_id)
    assert [i["kind"] for i in items] == ["clone"] and items[0]["ref"].startswith("plan:")


def test_platform_links_use_the_connector_provider_ids():
    url = integrations_port._ads_manager_url
    assert url("google_ads", "123-456", "ad9").startswith("https://ads.google.com/") and "adId=ad9" in url(
        "google_ads", "123-456", "ad9")
    assert url("tiktok", "777", "c1").startswith("https://ads.tiktok.com/")
    assert url("applovin", "x", "y") == ""  # no public deep link: the creative is skipped, never a broken link
