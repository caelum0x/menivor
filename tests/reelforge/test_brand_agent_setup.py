"""Brand Agent setup flow + versioned brand memory ("Brain").

"Let's set up my brand from my website: <url>" -> analysis + market search ->
Positioning, Product(s), Market, Voice and audience, each confirmed with Yes/No
chips and written to brand memory only after Yes -> optional "Connect Meta Ads?"
(skippable; a failure shows the reason with Retry) -> done.
"""

from __future__ import annotations

import json

import pytest

from app.domains.brand_agent import agent, copy_rules, memory, sessions, setup_flow, spaces
from app.domains.brand_agent.models import AgentInspiration
from app.domains.brand_agent.ports.base import PortUnavailable

from tests.reelforge._brand_agent_support import (
    SITE_URL,
    FakeIntegrations,
    FakeLLM,
    make_deps,
    make_factory,
    make_user,
)

SETUP_TEXT = f"Let's set up my brand from my website: {SITE_URL}"


@pytest.fixture()
def db():
    return make_factory()


@pytest.fixture()
def owner(db):
    return make_user(db)


def _new_session(db, uid):
    with db.scope() as s:
        space = spaces.ensure_default(s, uid)
        return space.id, sessions.create(s, uid, space.id).id


def _say(db, deps, uid, sid, text):
    with db.scope() as s:
        return agent.handle_text(s, deps, uid, sid, text)


def _chip(db, deps, uid, sid, step, choice, edits=None):
    with db.scope() as s:
        return agent.handle_chip(s, deps, uid, sid, step=step, choice=choice, edits=edits)


def _current(db, space_id):
    with db.scope() as s:
        return memory.current(s, space_id)


def _last_card(messages):
    cards = [m for m in messages if m.get("card")]
    return cards[-1] if cards else None


def test_setup_starts_with_analysis_and_a_positioning_card(db, owner):
    deps = make_deps()
    space_id, sid = _new_session(db, owner)
    out = _say(db, deps, owner, sid, SETUP_TEXT)
    text = " ".join(m["content"] for m in out)
    assert "Basepoint" in text
    card = _last_card(out)
    assert card["card"]["step"] == setup_flow.STEP_POSITIONING
    data = card["card"]["data"]
    assert data["category"] == "Developer tools: backend platform"
    assert data["colors"][0] == "#3d3f9e"
    assert "Instrument Sans" in data["fonts"]
    assert data["logo_url"].endswith("basepoint-logo.svg")
    assert "$25 a project" in data["pricing_hook"]
    assert [c["choice"] for c in card["chips"]] == ["yes", "no"]
    # The market search ran, but nothing is saved before a Yes.
    assert deps.search.queries
    assert _current(db, space_id)["sections"] == {}


def test_each_yes_writes_one_memory_version_and_advances(db, owner):
    deps = make_deps()
    space_id, sid = _new_session(db, owner)
    _say(db, deps, owner, sid, SETUP_TEXT)

    out = _chip(db, deps, owner, sid, setup_flow.STEP_POSITIONING, "yes")
    mem = _current(db, space_id)
    assert mem["version"] == 1 and set(mem["sections"]) == {"positioning"}
    assert _last_card(out)["card"]["step"] == setup_flow.STEP_PRODUCT
    product = _last_card(out)["card"]["data"]
    assert product["products"][0]["name"] == "Basepoint"
    assert "Postgres with branching" in product["products"][0]["key_features"]

    out = _chip(db, deps, owner, sid, setup_flow.STEP_PRODUCT, "yes")
    market = _last_card(out)["card"]["data"]
    names = [c["name"] for c in market["competitors"]]
    assert "Supabase" in names and "Neon Serverless Postgres" in names
    assert not any("basepoint" in c["url"] for c in market["competitors"])  # never ourselves

    out = _chip(db, deps, owner, sid, setup_flow.STEP_MARKET, "yes")
    voice = _last_card(out)["card"]["data"]
    assert voice["sample_lines"] and voice["segments"]
    assert all(seg["pains"] for seg in voice["segments"])

    out = _chip(db, deps, owner, sid, setup_flow.STEP_VOICE, "yes")
    mem = _current(db, space_id)
    assert mem["version"] == 4
    assert set(mem["sections"]) == {"positioning", "product", "market", "voice_audience"}
    meta = _last_card(out)
    assert meta["card"]["step"] == setup_flow.STEP_META
    assert {c["choice"] for c in meta["chips"]} == {"connect", "skip"}


def _run_to_meta(db, deps, owner, sid):
    _say(db, deps, owner, sid, SETUP_TEXT)
    for step in (setup_flow.STEP_POSITIONING, setup_flow.STEP_PRODUCT, setup_flow.STEP_MARKET, setup_flow.STEP_VOICE):
        _chip(db, deps, owner, sid, step, "yes")


def test_meta_connect_failure_shows_reason_and_retry_then_succeeds(db, owner):
    integrations = FakeIntegrations()  # not connected yet
    deps = make_deps(integrations=integrations)
    space_id, sid = _new_session(db, owner)
    _run_to_meta(db, deps, owner, sid)

    out = _chip(db, deps, owner, sid, setup_flow.STEP_META, "connect")
    msg = out[-1]
    assert msg["content"].startswith("Couldn't connect Meta Ads")
    assert "Connect your ad account" in msg["content"]
    assert [c["choice"] for c in msg["chips"]] == ["retry", "skip"]

    integrations.creatives = [
        {"id": "ad1", "title": "Tell your agent", "url": "https://facebook.com/ads/1", "thumbnail_url": "",
         "metrics": {"ctr": 0.031, "spend": 120.0}},
    ]
    out = _chip(db, deps, owner, sid, setup_flow.STEP_META, "retry")
    assert "1 top-performing ad" in out[-1]["content"]
    with db.scope() as s:
        rows = s.query(AgentInspiration).filter_by(space_id=space_id).all()
        assert [(r.source, r.url) for r in rows] == [("meta_ads", "https://facebook.com/ads/1")]
        assert sessions.get(s, owner, sid).state["setup"]["step"] == setup_flow.STEP_DONE


def test_meta_connect_unexpected_error_is_handled(db, owner):
    deps = make_deps(integrations=FakeIntegrations(error=RuntimeError("token=secret-abc boom")))
    _, sid = _new_session(db, owner)
    _run_to_meta(db, deps, owner, sid)
    out = _chip(db, deps, owner, sid, setup_flow.STEP_META, "connect")
    assert out[-1]["content"].startswith("Couldn't connect Meta Ads")
    assert "secret-abc" not in out[-1]["content"]  # never echo raw exception text


def test_meta_can_be_skipped(db, owner):
    deps = make_deps()
    _, sid = _new_session(db, owner)
    _run_to_meta(db, deps, owner, sid)
    out = _chip(db, deps, owner, sid, setup_flow.STEP_META, "skip")
    assert "brand is set up" in out[-1]["content"].lower()
    assert deps.integrations.calls == []


def test_no_with_edits_saves_the_edited_section(db, owner):
    deps = make_deps()
    space_id, sid = _new_session(db, owner)
    _say(db, deps, owner, sid, SETUP_TEXT)
    edits = {"one_liner": "Backends your agent sets up in one command", "colors": ["#4F46E5", "zzz"]}
    _chip(db, deps, owner, sid, setup_flow.STEP_POSITIONING, "no", edits=edits)
    pos = _current(db, space_id)["sections"]["positioning"]
    assert pos["one_liner"] == "Backends your agent sets up in one command"
    assert pos["colors"] == ["#4f46e5"]  # normalized, junk dropped


def test_no_without_edits_asks_and_the_reply_revises_the_proposal(db, owner):
    revised = json.dumps({"products": [{"name": "Basepoint Cloud", "what_it_is": "Hosted Postgres for agents",
                                        "key_features": ["Branching"]}]})
    llm = FakeLLM(replies=["", revised])  # first call: setup enrichment (empty = keep heuristics)
    deps = make_deps(llm=llm)
    space_id, sid = _new_session(db, owner)
    _say(db, deps, owner, sid, SETUP_TEXT)
    _chip(db, deps, owner, sid, setup_flow.STEP_POSITIONING, "yes")
    out = _chip(db, deps, owner, sid, setup_flow.STEP_PRODUCT, "no")
    assert "what should change" in out[-1]["content"].lower()
    out = _say(db, deps, owner, sid, "It's called Basepoint Cloud")
    card = _last_card(out)
    assert card["card"]["step"] == setup_flow.STEP_PRODUCT
    assert card["card"]["data"]["products"][0]["name"] == "Basepoint Cloud"
    assert "product" not in _current(db, space_id)["sections"]  # still waits for Yes


def test_llm_audience_output_is_scrubbed_before_memory(db, owner):
    enrichment = json.dumps({"voice_audience": {"segments": [
        {"name": "Indie hackers", "pains": ["indie devs hate backend ops"]}]}})
    deps = make_deps(llm=FakeLLM(replies=[enrichment]))
    space_id, sid = _new_session(db, owner)
    _run_to_meta(db, deps, owner, sid)
    voice = _current(db, space_id)["sections"]["voice_audience"]
    assert copy_rules.violations(json.dumps(voice)) == []
    assert voice["segments"][0]["name"] == "Founders"
    system_prompt = deps.llm.calls[0][0]
    assert "Never use the word" in system_prompt


def test_brain_badge_counts_agent_updates_and_user_edits_are_versions(db, owner):
    deps = make_deps()
    space_id, sid = _new_session(db, owner)
    _run_to_meta(db, deps, owner, sid)
    with db.scope() as s:
        assert memory.unseen_count(s, space_id) == 4
        memory.mark_seen(s, owner, space_id)
        assert memory.unseen_count(s, space_id) == 0
        edited = memory.write(s, owner, space_id, "positioning",
                              {**memory.current(s, space_id)["sections"]["positioning"], "pricing_hook": "Flat $25"},
                              source=memory.SOURCE_USER)
        assert edited["version"] == 5
        assert memory.unseen_count(s, space_id) == 0
        history = memory.history(s, space_id, section="positioning")
        assert [h["version"] for h in history] == [5, 1]
        assert history[1]["data"]["pricing_hook"] != "Flat $25"  # old version kept


def test_memory_rejects_unknown_sections(db, owner):
    with db.scope() as s:
        space = spaces.ensure_default(s, owner)
        with pytest.raises(memory.MemoryError_):
            memory.write(s, owner, space.id, "secrets", {"x": 1})


def test_setup_without_a_url_asks_for_one(db, owner):
    deps = make_deps()
    _, sid = _new_session(db, owner)
    out = _say(db, deps, owner, sid, "Let's set up my brand")
    assert "website" in out[-1]["content"].lower()


def test_analysis_failure_is_explained(db, owner):
    from app.domains.brand_agent.site_analysis import SiteAnalysisError

    def broken(url):
        raise SiteAnalysisError("the website blocked the automated visit")

    deps = make_deps(analyzer=broken)
    _, sid = _new_session(db, owner)
    out = _say(db, deps, owner, sid, SETUP_TEXT)
    assert "blocked the automated visit" in out[-1]["content"]


def test_messages_are_stored_in_order(db, owner):
    deps = make_deps()
    _, sid = _new_session(db, owner)
    _say(db, deps, owner, sid, SETUP_TEXT)
    with db.scope() as s:
        msgs = sessions.messages(s, owner, sid)
    assert msgs[0]["role"] == "user" and msgs[0]["content"] == SETUP_TEXT
    assert [m["seq"] for m in msgs] == sorted(m["seq"] for m in msgs)
    assert all(m["role"] in {"user", "assistant"} for m in msgs)


def test_port_unavailable_is_a_plain_exception():
    err = PortUnavailable("x")
    assert err.reason == "x"


# --------------------------------------------------------------------------- #
# Owner rule 2026-10-06: the user can correct the audience ("No, change it"),
# competitors the site names are framed as where switchers come from, and
# comparisons never imply an affiliation.
# --------------------------------------------------------------------------- #
def _to_voice(db, deps, owner, sid):
    _say(db, deps, owner, sid, SETUP_TEXT)
    for step in (setup_flow.STEP_POSITIONING, setup_flow.STEP_PRODUCT, setup_flow.STEP_MARKET):
        _chip(db, deps, owner, sid, step, "yes")


def test_no_change_it_rewrites_the_audience_without_an_llm(db, owner):
    deps = make_deps()  # no LLM: the deterministic correction path
    space_id, sid = _new_session(db, owner)
    _to_voice(db, deps, owner, sid)
    out = _chip(db, deps, owner, sid, setup_flow.STEP_VOICE, "no")
    assert "what should change" in out[-1]["content"].lower()
    out = _say(db, deps, owner, sid, "Our audience is teams already on Supabase and Neon")
    card = _last_card(out)
    assert card["card"]["step"] == setup_flow.STEP_VOICE
    assert [s["name"] for s in card["card"]["data"]["segments"]] == ["Teams already on Supabase and Neon"]
    assert card["card"]["data"]["segments"][0]["pains"]  # the site's pains are kept
    assert "voice_audience" not in _current(db, space_id)["sections"]
    _chip(db, deps, owner, sid, setup_flow.STEP_VOICE, "yes")
    saved = _current(db, space_id)["sections"]["voice_audience"]
    assert [s["name"] for s in saved["segments"]] == ["Teams already on Supabase and Neon"]
    with db.scope() as s:
        assert memory.history(s, space_id, section="voice_audience")[0]["source"] == memory.SOURCE_USER


def test_audience_can_be_changed_again_after_setup(db, owner):
    deps = make_deps()
    space_id, sid = _new_session(db, owner)
    _run_to_meta(db, deps, owner, sid)
    _chip(db, deps, owner, sid, setup_flow.STEP_META, "skip")
    before = _current(db, space_id)["version"]
    out = _say(db, deps, owner, sid, "Change the audience to teams on Supabase; teams on Neon")
    assert "Updated your audience" in out[-1]["content"]
    with db.scope() as s:
        versions = memory.history(s, space_id, section="voice_audience")
    assert versions[0]["version"] == before + 1 and versions[0]["source"] == memory.SOURCE_USER
    assert [seg["name"] for seg in versions[0]["data"]["segments"]] == ["Teams on Supabase", "Teams on Neon"]
    assert len(versions) == 2  # the earlier version is kept


def test_competitors_named_on_the_site_are_switch_sources():
    from app.domains.brand_agent import proposals
    from tests.reelforge._brand_agent_support import FakeSearch, fixture_analysis

    analysis = {**fixture_analysis(), "sample_lines": ["Drop-in compatible with Supabase clients."]}
    out = proposals.market(analysis, FakeSearch().results, search_enabled=True)
    rel = {c["name"]: c["relationship"] for c in out["competitors"]}
    assert rel["Supabase"] == "switch_source"
    assert rel["Neon Serverless Postgres"] == "competitor"
    assert any("likeliest switchers" in i for i in out["insights"])
    assert any("never imply an affiliation" in i for i in out["insights"])


def test_market_correction_marks_switch_sources(db, owner):
    deps = make_deps()
    space_id, sid = _new_session(db, owner)
    _say(db, deps, owner, sid, SETUP_TEXT)
    _chip(db, deps, owner, sid, setup_flow.STEP_POSITIONING, "yes")
    _chip(db, deps, owner, sid, setup_flow.STEP_PRODUCT, "yes")
    _chip(db, deps, owner, sid, setup_flow.STEP_MARKET, "no")
    out = _say(db, deps, owner, sid, "switch from: Supabase, Neon")
    comps = {c["name"]: c["relationship"] for c in _last_card(out)["card"]["data"]["competitors"]}
    assert comps["Supabase"] == "switch_source" and comps["Neon Serverless Postgres"] == "switch_source"
    insight = _last_card(out)["card"]["data"]["insights"][0]
    assert "likeliest switchers" in insight and "never imply an affiliation" in insight


def test_system_prompt_requires_verifiable_comparisons_without_affiliation():
    prompt = copy_rules.SYSTEM_PROMPT.lower()
    assert "verifiable" in prompt and "affiliation" in prompt
    assert "maker communities" in prompt
