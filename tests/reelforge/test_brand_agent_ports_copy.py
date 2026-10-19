"""Brand Agent: the "indie" copy rule, the system prompt, and the interface ports.

The Arcads demo labelled an audience "indie hackers"; ours must not. The rule
is stricter than the shared policy: "Indie Hackers" may only name the site.
Ports resolve another branch's implementation by module path and fall back to a
stub that raises :class:`PortUnavailable` with a plain reason.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from app.domains.brand_agent import copy_rules
from app.domains.brand_agent.ports import ad_clone, base, integrations, search

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("text", [
    "Audience: indie hackers shipping SaaS",
    "Built for indie founders",
    "A backend for indie mobile developers",
    "Indie SaaS at $1-5K MRR",
    "#indiehacker #buildinpublic",
    "Great for indies",
])
def test_indie_audience_wording_is_flagged(text):
    assert copy_rules.violations(text), text


@pytest.mark.parametrize("text", [
    "Built for early-stage founders",
    "Post it on Indie Hackers",
    "https://www.indiehackers.com/products",
    "IndieBio and Indiegogo",
    "indien beschikbaar",
])
def test_site_names_and_lookalikes_are_allowed(text):
    assert copy_rules.violations(text) == [], text


def test_scrub_rewrites_audience_wording():
    out = copy_rules.scrub("Indie hackers and indie founders love it; indie mobile developers too.")
    assert copy_rules.violations(out) == []
    assert "Founders" in out and "early-stage founders" in out and "mobile app developers" in out


def test_scrub_walks_nested_memory_without_mutating_it():
    data = {"segments": [{"name": "Indie hackers", "pains": ["indie devs hate ops"]}], "n": 3}
    out = copy_rules.scrub_obj(data)
    assert data["segments"][0]["name"] == "Indie hackers"  # input untouched
    assert copy_rules.violations(json.dumps(out)) == []
    assert out["n"] == 3


def test_system_prompt_carries_the_rule_and_is_clean_itself():
    prompt = copy_rules.SYSTEM_PROMPT
    assert "Never use the word" in prompt and "founders" in prompt and "app studios" in prompt
    assert "approval" in prompt.lower()
    # The prompt quotes the banned word once, in quotes; nothing else may use it.
    assert copy_rules.violations(prompt.replace('"indie"', "")) == []


def test_policy_file_examples_agree_when_present():
    path = REPO / "policy" / "copy-denylist.json"
    if not path.exists():
        pytest.skip("policy file not vendored")
    rule = next(r for r in json.loads(path.read_text())["rules"] if r["id"] == "indie-audience")
    for hit in rule["examples"]["hit"]:
        assert copy_rules.violations(hit), hit
    for miss in rule["examples"]["miss"]:
        assert copy_rules.violations(miss) == [], miss


# --------------------------------------------------------------------------- #
# Ports
# --------------------------------------------------------------------------- #
def test_ad_clone_stub_is_used_until_the_other_branch_lands(monkeypatch):
    monkeypatch.delenv("BRAND_AGENT_AD_CLONE_PORT", raising=False)
    port = ad_clone.get_port()
    with pytest.raises(base.PortUnavailable) as err:
        port.clone_from_link("u1", "https://www.tiktok.com/@a/video/1", brand={}, space_id="s1")
    assert "Ad Clone" in err.value.reason


def test_integrations_stub_explains_meta_is_not_connected():
    port = integrations.StubIntegrations()
    with pytest.raises(base.PortUnavailable) as err:
        port.top_performing_creatives("u1", platform="meta", limit=5)
    assert "Meta" in err.value.reason or "ad account" in err.value.reason.lower()
    assert port.list_connected_accounts("u1") == []


def test_ports_resolve_a_registered_module(monkeypatch):
    module = types.ModuleType("fake_clone_port")

    class Impl:
        def clone_from_link(self, user_id, url, *, brand, space_id):
            return {"status": "queued", "job_id": "j1", "url": url}

    module.PORT = Impl()
    monkeypatch.setitem(sys.modules, "fake_clone_port", module)
    monkeypatch.setenv("BRAND_AGENT_AD_CLONE_PORT", "fake_clone_port:PORT")
    assert ad_clone.get_port().clone_from_link("u", "https://x.test/a", brand={}, space_id="s")["job_id"] == "j1"


def test_a_broken_port_module_falls_back_to_the_stub(monkeypatch):
    monkeypatch.setenv("BRAND_AGENT_INTEGRATIONS_PORT", "does.not.exist:PORT")
    assert isinstance(integrations.get_port(), integrations.StubIntegrations)


def test_search_is_off_by_default_and_parses_searxng(monkeypatch):
    monkeypatch.delenv("BRAND_AGENT_SEARCH", raising=False)
    monkeypatch.delenv("SEARXNG_URL", raising=False)
    assert isinstance(search.get_port(), search.NoSearch)
    assert search.get_port().search("postgres backend competitors") == []

    seen = {}

    def getter(url, **_kw):
        seen["url"] = url

        class R:
            content_type = "application/json"

            def text(self):
                return json.dumps({"results": [
                    {"title": "Supabase", "url": "https://supabase.com", "content": "Postgres dev platform"},
                    {"title": "", "url": "", "content": "junk"},
                ]})
        return R()

    port = search.SearxngSearch("https://searx.example", getter=getter)
    results = port.search("postgres backend", limit=5)
    assert results == [{"title": "Supabase", "url": "https://supabase.com", "snippet": "Postgres dev platform"}]
    assert seen["url"].startswith("https://searx.example/search?") and "format=json" in seen["url"]


def test_duckduckgo_html_results_are_parsed():
    page = (
        '<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fneon.tech%2F&rut=x">'
        'Neon <b>Serverless</b> Postgres</a><a class="result__snippet">Branching Postgres.</a></div>'
    )
    results = search.parse_duckduckgo_html(page, limit=3)
    assert results == [{"title": "Neon Serverless Postgres", "url": "https://neon.tech/", "snippet": "Branching Postgres."}]
