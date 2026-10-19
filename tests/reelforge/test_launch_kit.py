"""Launch Kit (Menivor Growth phase 3): launch directory catalog + tracking,
Reddit pain-point search + drafted replies (never posted), competitor
backlinks (gated, never spends credits on its own), and the 10-step playbook
checklist. Every external call goes through an injected fake transport --
no live network, mirroring tests/reelforge/test_keyword_tracker.py and
tests/reelforge/test_wave2_competitors.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest

from app.domains.launch_kit import backlinks as backlinks_source
from app.domains.launch_kit import catalog
from app.domains.launch_kit import reddit_search
from app.domains.launch_kit import router as launch_kit_router
from app.domains.launch_kit import service
from app.domains.launch_kit.models import LaunchPlatformStatus, PainPointDraft, PlaybookStepStatus
from app.domains.launch_kit.service import LaunchKitError
from tests.reelforge._wave2_support import H, OTHER, client_for, data, make_env

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


@dataclass
class FakeResponse:
    status_code: int = 200
    payload: dict = field(default_factory=dict)

    def json(self):
        return self.payload


@dataclass
class FakeTransport:
    """Records every call and answers from a ``(method, url)``-keyed table."""

    answers: dict
    calls: list = field(default_factory=list)

    def request(self, method, url, *, headers=None, params=None, json=None):  # noqa: A002 - matches the real shape
        self.calls.append({"method": method, "url": url, "headers": headers, "params": params, "json": json})
        key = (method, url)
        if key not in self.answers:
            return FakeResponse(200, {})
        return self.answers[key]


def _reddit_child(permalink="/r/saas/comments/abc/help/", title="Need help with onboarding drop-off",
                  selftext="Our signup funnel loses half of people on step 2.", subreddit="saas", ups=42,
                  created_utc=1_760_000_000):
    return {"kind": "t3", "data": {"permalink": permalink, "title": title, "selftext": selftext,
                                   "subreddit": subreddit, "ups": ups, "created_utc": created_utc,
                                   "id": "abc", "num_comments": 3, "author": "someone"}}


@pytest.fixture()
def env(monkeypatch):
    return make_env(monkeypatch)


# --------------------------------------------------------------------------- #
# catalog
# --------------------------------------------------------------------------- #
def test_platforms_for_category_filters_by_tag():
    ai_only = catalog.platforms_for_category("ai")
    assert ai_only and all("ai" in p["categories"] for p in ai_only)
    assert len(ai_only) < len(catalog.PLATFORMS)


def test_platforms_for_category_none_returns_everything():
    assert catalog.platforms_for_category(None) == catalog.PLATFORMS
    assert catalog.platforms_for_category("") == catalog.PLATFORMS


def test_every_platform_url_is_https_and_unique_id():
    ids = [p["id"] for p in catalog.PLATFORMS]
    assert len(ids) == len(set(ids))
    assert all(p["url"].startswith("https://") for p in catalog.PLATFORMS)


def test_is_known_product_is_case_insensitive():
    assert catalog.is_known_product("menivor")
    assert catalog.is_known_product("MENIVOR")
    assert not catalog.is_known_product("totally-unknown-product")


def test_refresh_products_from_portfolio_md_returns_none_without_a_reachable_file(monkeypatch):
    monkeypatch.delenv("LAUNCH_KIT_PORTFOLIO_MD", raising=False)
    assert catalog.refresh_products_from_portfolio_md("/no/such/file.md") is None


def test_refresh_products_from_portfolio_md_parses_a_real_table(tmp_path):
    md = tmp_path / "PORTFOLIO.md"
    md.write_text(
        "| Product | Kind | Status | Market | Main link |\n"
        "|---|---|---|---|---|\n"
        "| Rally | website | live | yes | https://vcpeer.com |\n"
        "| Menivor | website | live | yes | https://menivor.com |\n",
        encoding="utf-8",
    )
    names = catalog.refresh_products_from_portfolio_md(str(md))
    assert names == ("Rally", "Menivor")


# --------------------------------------------------------------------------- #
# list_launch_platforms / set_platform_status
# --------------------------------------------------------------------------- #
def test_list_launch_platforms_defaults_to_not_started(env):
    with env.db.scope() as s:
        out = service.list_launch_platforms(s, env.uid, product_name="Oxhan Atelier")
    assert out["platforms"]
    assert all(p["status"] == "not_started" for p in out["platforms"])


def test_set_platform_status_rejects_unknown_platform(env):
    with env.db.scope() as s:
        with pytest.raises(LaunchKitError) as err:
            service.set_platform_status(s, env.uid, product_name="Oxhan Atelier", platform_id="not-a-real-site",
                                        status="submitted")
    assert err.value.status_code == 422


def test_set_platform_status_rejects_bad_status(env):
    with env.db.scope() as s:
        with pytest.raises(LaunchKitError) as err:
            service.set_platform_status(s, env.uid, product_name="Oxhan Atelier", platform_id="product_hunt",
                                        status="definitely_live")
    assert err.value.status_code == 422


def test_set_platform_status_records_submitted_at_and_is_idempotent(env):
    with env.db.scope() as s:
        out = service.set_platform_status(s, env.uid, product_name="Oxhan Atelier", platform_id="product_hunt",
                                          status="submitted", note="queued for Tuesday", now=NOW)
    assert out["status"] == "submitted" and out["submitted_at"] == NOW.isoformat()
    with env.db.scope() as s:
        assert s.query(LaunchPlatformStatus).count() == 1
        # Re-setting the same platform upserts instead of duplicating.
        out2 = service.set_platform_status(s, env.uid, product_name="Oxhan Atelier", platform_id="product_hunt",
                                           status="live", now=NOW + timedelta(days=1))
    assert out2["status"] == "live"
    with env.db.scope() as s:
        assert s.query(LaunchPlatformStatus).count() == 1


def test_set_platform_status_back_to_not_started_clears_submitted_at(env):
    with env.db.scope() as s:
        service.set_platform_status(s, env.uid, product_name="Oxhan Atelier", platform_id="product_hunt",
                                    status="submitted", now=NOW)
        out = service.set_platform_status(s, env.uid, product_name="Oxhan Atelier", platform_id="product_hunt",
                                          status="not_started", now=NOW + timedelta(hours=1))
    assert out["submitted_at"] is None


def test_list_launch_platforms_reflects_tracked_status(env):
    with env.db.scope() as s:
        service.set_platform_status(s, env.uid, product_name="Oxhan Atelier", platform_id="betalist",
                                    status="live", now=NOW)
    with env.db.scope() as s:
        out = service.list_launch_platforms(s, env.uid, product_name="Oxhan Atelier")
    row = next(p for p in out["platforms"] if p["id"] == "betalist")
    assert row["status"] == "live"
    others = [p for p in out["platforms"] if p["id"] != "betalist"]
    assert all(p["status"] == "not_started" for p in others)


# --------------------------------------------------------------------------- #
# find_pain_point_threads (Reddit search, read-only, drafts only)
# --------------------------------------------------------------------------- #
def test_reddit_search_restricted_to_subreddits_hits_the_subreddit_endpoint():
    transport = FakeTransport({
        ("GET", "https://www.reddit.com/r/saas/search.json"): FakeResponse(200, {"data": {"children": [
            _reddit_child()]}}),
    })
    threads = reddit_search.search(transport, query="onboarding drop-off", subreddits=["saas"], now=1_760_100_000)
    assert len(threads) == 1
    assert threads[0].subreddit == "saas" and threads[0].upvotes == 42 and threads[0].age_days >= 0
    assert transport.calls[0]["url"].endswith("/r/saas/search.json")
    assert transport.calls[0]["headers"]["User-Agent"]


def test_reddit_search_without_subreddits_hits_the_global_endpoint():
    transport = FakeTransport({
        ("GET", "https://www.reddit.com/search.json"): FakeResponse(200, {"data": {"children": [_reddit_child()]}}),
    })
    threads = reddit_search.search(transport, query="onboarding drop-off")
    assert len(threads) == 1
    assert transport.calls[0]["url"] == "https://www.reddit.com/search.json"


def test_reddit_search_dedupes_across_subreddits_and_sorts_by_upvotes():
    low = _reddit_child(permalink="/r/a/comments/1/x/", ups=5)
    high = _reddit_child(permalink="/r/b/comments/2/y/", ups=99)
    dup = _reddit_child(permalink="/r/a/comments/1/x/", ups=5)  # same permalink as `low`
    transport = FakeTransport({
        ("GET", "https://www.reddit.com/r/a/search.json"): FakeResponse(200, {"data": {"children": [low, dup]}}),
        ("GET", "https://www.reddit.com/r/b/search.json"): FakeResponse(200, {"data": {"children": [high]}}),
    })
    threads = reddit_search.search(transport, query="x", subreddits=["a", "b"])
    assert [t.upvotes for t in threads] == [99, 5]  # deduped + sorted high-to-low


def test_reddit_search_raises_on_rate_limit():
    transport = FakeTransport({("GET", "https://www.reddit.com/search.json"): FakeResponse(429, {})})
    with pytest.raises(reddit_search.RedditSearchError) as err:
        reddit_search.search(transport, query="x")
    assert err.value.status_code == 429


def test_reddit_search_rejects_blank_query():
    with pytest.raises(reddit_search.RedditSearchError):
        reddit_search.search(FakeTransport({}), query="   ")


def test_find_pain_point_threads_saves_drafts_and_never_sets_status_posted(env):
    transport = FakeTransport({
        ("GET", "https://www.reddit.com/r/saas/search.json"): FakeResponse(200, {"data": {"children": [
            _reddit_child()]}}),
    })
    with env.db.scope() as s:
        out = service.find_pain_point_threads(s, env.uid, query="onboarding drop-off", subreddits=["saas"],
                                              product_name="Menivor", transport=transport, now=NOW)
    assert out["count"] == 1
    assert "menivor" in out["threads"][0]["draft_reply"].lower()
    with env.db.scope() as s:
        row = s.query(PainPointDraft).one()
        assert row.status == "drafted"
        assert row.thread_url.startswith("https://www.reddit.com/r/saas/")


def test_find_pain_point_threads_is_idempotent_for_the_same_query(env):
    transport = FakeTransport({
        ("GET", "https://www.reddit.com/search.json"): FakeResponse(200, {"data": {"children": [_reddit_child()]}}),
    })
    with env.db.scope() as s:
        service.find_pain_point_threads(s, env.uid, query="onboarding drop-off", transport=transport, now=NOW)
    with env.db.scope() as s:
        service.find_pain_point_threads(s, env.uid, query="onboarding drop-off", transport=transport, now=NOW)
    with env.db.scope() as s:
        assert s.query(PainPointDraft).count() == 1  # the same thread is not re-saved


def test_find_pain_point_threads_requires_a_query(env):
    with env.db.scope() as s:
        with pytest.raises(LaunchKitError) as err:
            service.find_pain_point_threads(s, env.uid, query="   ", transport=FakeTransport({}))
    assert err.value.status_code == 422


def test_pain_point_draft_status_can_be_approved_or_dismissed_never_posted(env):
    transport = FakeTransport({
        ("GET", "https://www.reddit.com/search.json"): FakeResponse(200, {"data": {"children": [_reddit_child()]}}),
    })
    with env.db.scope() as s:
        out = service.find_pain_point_threads(s, env.uid, query="onboarding", transport=transport, now=NOW)
    draft_id = None
    with env.db.scope() as s:
        draft_id = s.query(PainPointDraft).one().id
        approved = service.set_pain_point_draft_status(s, env.uid, draft_id, "approved")
    assert approved["status"] == "approved"
    with env.db.scope() as s:
        with pytest.raises(LaunchKitError):
            service.set_pain_point_draft_status(s, env.uid, draft_id, "posted")


def test_pain_point_draft_status_is_owner_scoped(env):
    transport = FakeTransport({
        ("GET", "https://www.reddit.com/search.json"): FakeResponse(200, {"data": {"children": [_reddit_child()]}}),
    })
    with env.db.scope() as s:
        service.find_pain_point_threads(s, env.uid, query="onboarding", transport=transport, now=NOW)
    with env.db.scope() as s:
        draft_id = s.query(PainPointDraft).one().id
        with pytest.raises(LaunchKitError) as err:
            service.set_pain_point_draft_status(s, env.other, draft_id, "approved")
    assert err.value.status_code == 404


def test_list_pain_point_drafts_filters_by_status_and_product(env):
    transport = FakeTransport({
        ("GET", "https://www.reddit.com/search.json"): FakeResponse(200, {"data": {"children": [_reddit_child()]}}),
    })
    with env.db.scope() as s:
        service.find_pain_point_threads(s, env.uid, query="onboarding", product_name="Menivor", transport=transport,
                                        now=NOW)
    with env.db.scope() as s:
        drafted = service.list_pain_point_drafts(s, env.uid, status="drafted")
        approved = service.list_pain_point_drafts(s, env.uid, status="approved")
    assert len(drafted) == 1 and approved == []


# --------------------------------------------------------------------------- #
# find_competitor_backlinks (gated, never spends credits by itself)
# --------------------------------------------------------------------------- #
def test_backlinks_not_configured_returns_the_free_fallback(monkeypatch):
    monkeypatch.delenv(backlinks_source.DATAFORSEO_LOGIN_ENV, raising=False)
    monkeypatch.delenv(backlinks_source.DATAFORSEO_PASSWORD_ENV, raising=False)
    monkeypatch.delenv(backlinks_source.CRAWLGRAPH_API_KEY_ENV, raising=False)
    out = service.find_competitor_backlinks("https://rival.com")
    assert out["live"] is False and out["configured"] is False
    assert out["domain"] == "rival.com"
    assert out["fallback_directories"]


def test_backlinks_configured_but_not_live_still_does_not_call_the_api(monkeypatch):
    monkeypatch.setenv(backlinks_source.DATAFORSEO_LOGIN_ENV, "owner")
    monkeypatch.setenv(backlinks_source.DATAFORSEO_PASSWORD_ENV, "secret")
    monkeypatch.delenv(backlinks_source.CRAWLGRAPH_API_KEY_ENV, raising=False)
    transport = FakeTransport({})
    out = service.find_competitor_backlinks("rival.com", transport=transport, allow_live=False)
    assert out["configured"] is True and out["live"] is False
    assert transport.calls == []  # never called


def test_backlinks_live_call_requires_both_the_flag_and_credentials(monkeypatch):
    monkeypatch.delenv(backlinks_source.DATAFORSEO_LOGIN_ENV, raising=False)
    monkeypatch.delenv(backlinks_source.DATAFORSEO_PASSWORD_ENV, raising=False)
    monkeypatch.delenv(backlinks_source.CRAWLGRAPH_API_KEY_ENV, raising=False)
    transport = FakeTransport({})
    out = service.find_competitor_backlinks("rival.com", transport=transport, allow_live=True)
    assert out["live"] is False  # no credentials, so still the fallback, not a live call
    assert transport.calls == []


def test_backlinks_live_call_parses_dataforseo_response(monkeypatch):
    monkeypatch.setenv(backlinks_source.DATAFORSEO_LOGIN_ENV, "owner")
    monkeypatch.setenv(backlinks_source.DATAFORSEO_PASSWORD_ENV, "secret")
    monkeypatch.delenv(backlinks_source.CRAWLGRAPH_API_KEY_ENV, raising=False)
    body = {"tasks": [{"result": [{"items": [
        {"domain_from": "producthunt.com", "url_to": "https://rival.com", "anchor": "Rival", "rank": 900},
    ]}]}]}
    transport = FakeTransport({("POST", backlinks_source.LIVE_BACKLINKS_BASE): FakeResponse(200, body)})
    out = service.find_competitor_backlinks("rival.com", transport=transport, allow_live=True)
    assert out["live"] is True
    assert out["backlinks"] == [{"source_domain": "producthunt.com", "target_url": "https://rival.com",
                                 "anchor": "Rival", "rank": 900}]
    assert transport.calls[0]["headers"]["Authorization"].startswith("Basic ")


def test_backlinks_configured_via_crawlgraph_key_alone(monkeypatch):
    monkeypatch.delenv(backlinks_source.DATAFORSEO_LOGIN_ENV, raising=False)
    monkeypatch.delenv(backlinks_source.DATAFORSEO_PASSWORD_ENV, raising=False)
    monkeypatch.setenv(backlinks_source.CRAWLGRAPH_API_KEY_ENV, "cg_live_test")
    transport = FakeTransport({})
    out = service.find_competitor_backlinks("rival.com", transport=transport, allow_live=False)
    assert out["configured"] is True and out["live"] is False
    assert transport.calls == []  # never called without allow_live


def test_backlinks_live_call_parses_crawlgraph_response(monkeypatch):
    monkeypatch.delenv(backlinks_source.DATAFORSEO_LOGIN_ENV, raising=False)
    monkeypatch.delenv(backlinks_source.DATAFORSEO_PASSWORD_ENV, raising=False)
    monkeypatch.setenv(backlinks_source.CRAWLGRAPH_API_KEY_ENV, "cg_live_test")
    body = {"domain": "rival.com", "total_linking_domains": 2, "cg_authority": 40, "results": [
        {"linking_domain": "producthunt.com", "num_hosts": 3, "cg_rank": 900},
        {"linking_domain": "news.ycombinator.com", "num_hosts": 1, "cg_rank": 950},
    ]}
    transport = FakeTransport({("POST", backlinks_source.CRAWLGRAPH_BACKLINKS_BASE): FakeResponse(200, body)})
    out = service.find_competitor_backlinks("rival.com", transport=transport, allow_live=True)
    assert out["live"] is True
    assert out["provider"] == "crawlgraph"
    assert out["backlinks"] == [
        {"source_domain": "producthunt.com", "target_url": "", "anchor": "", "rank": 900, "linking_hosts": 3},
        {"source_domain": "news.ycombinator.com", "target_url": "", "anchor": "", "rank": 950, "linking_hosts": 1},
    ]
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer cg_live_test"


def test_backlinks_prefers_crawlgraph_over_dataforseo_when_both_configured(monkeypatch):
    monkeypatch.setenv(backlinks_source.DATAFORSEO_LOGIN_ENV, "owner")
    monkeypatch.setenv(backlinks_source.DATAFORSEO_PASSWORD_ENV, "secret")
    monkeypatch.setenv(backlinks_source.CRAWLGRAPH_API_KEY_ENV, "cg_live_test")
    transport = FakeTransport({
        ("POST", backlinks_source.CRAWLGRAPH_BACKLINKS_BASE): FakeResponse(200, {"results": []}),
    })
    out = service.find_competitor_backlinks("rival.com", transport=transport, allow_live=True)
    assert out["provider"] == "crawlgraph"
    assert len(transport.calls) == 1  # DataForSEO never called


def test_backlinks_rejects_an_obviously_bad_domain():
    with pytest.raises(LaunchKitError) as err:
        service.find_competitor_backlinks("not a domain")
    assert err.value.status_code == 422


# --------------------------------------------------------------------------- #
# get_launch_checklist / mark_playbook_step
# --------------------------------------------------------------------------- #
def test_checklist_defaults_every_step_to_pending_for_a_fresh_product(env):
    with env.db.scope() as s:
        out = service.get_launch_checklist(s, env.uid, product_name="Oxhan Atelier")
    assert out["total"] == len(catalog.PLAYBOOK_STEPS)
    assert out["done"] == 0
    assert out["known_product"] is True
    assert all(step["status"] == "pending" for step in out["steps"])


def test_checklist_flags_an_unlisted_product_as_not_known_but_still_works(env):
    with env.db.scope() as s:
        out = service.get_launch_checklist(s, env.uid, product_name="Some Brand New Thing")
    assert out["known_product"] is False
    assert out["total"] == len(catalog.PLAYBOOK_STEPS)


def test_launch_everywhere_step_is_derived_from_submitted_platforms(env):
    with env.db.scope() as s:
        service.set_platform_status(s, env.uid, product_name="Oxhan Atelier", platform_id="product_hunt",
                                    status="submitted", now=NOW)
    with env.db.scope() as s:
        out = service.get_launch_checklist(s, env.uid, product_name="Oxhan Atelier")
    step = next(s for s in out["steps"] if s["key"] == "launch_everywhere")
    assert step["status"] == "done"
    assert out["platforms_submitted"] == ["product_hunt"]


def test_mark_playbook_step_rejects_unknown_key(env):
    with env.db.scope() as s:
        with pytest.raises(LaunchKitError) as err:
            service.mark_playbook_step(s, env.uid, product_name="Oxhan Atelier", step_key="not_a_step",
                                       status="done")
    assert err.value.status_code == 422


def test_mark_playbook_step_persists_and_is_read_back(env):
    with env.db.scope() as s:
        service.mark_playbook_step(s, env.uid, product_name="Oxhan Atelier", step_key="ugc_creators",
                                   status="done", note="3 creators DMed", now=NOW)
    with env.db.scope() as s:
        out = service.get_launch_checklist(s, env.uid, product_name="Oxhan Atelier")
    step = next(s for s in out["steps"] if s["key"] == "ugc_creators")
    assert step["status"] == "done" and step["note"] == "3 creators DMed"
    assert out["done"] == 1
    with env.db.scope() as s:
        assert s.query(PlaybookStepStatus).count() == 1


def test_mark_playbook_step_is_idempotent_per_product_and_step(env):
    with env.db.scope() as s:
        service.mark_playbook_step(s, env.uid, product_name="Oxhan Atelier", step_key="ugc_creators", status="done")
        service.mark_playbook_step(s, env.uid, product_name="Oxhan Atelier", step_key="ugc_creators",
                                   status="pending")
    with env.db.scope() as s:
        assert s.query(PlaybookStepStatus).count() == 1


# --------------------------------------------------------------------------- #
# router
# --------------------------------------------------------------------------- #
def test_router_platforms_list_and_set_status(env, monkeypatch):
    client = client_for(launch_kit_router, monkeypatch=monkeypatch, db=env.db)
    listed = data(client.get("/api/v1/launch-kit/platforms", headers=H, params={"product_name": "Oxhan Atelier"}))
    assert listed["platforms"]

    set_resp = data(client.post("/api/v1/launch-kit/platforms/status", headers=H,
                                json={"product_name": "Oxhan Atelier", "platform_id": "product_hunt",
                                     "status": "submitted"}))
    assert set_resp["status"] == "submitted"

    bad = client.post("/api/v1/launch-kit/platforms/status", headers=H,
                      json={"product_name": "Oxhan Atelier", "platform_id": "not-real", "status": "submitted"})
    assert bad.status_code == 422


def test_router_pain_point_search_and_draft_review(env, monkeypatch):
    transport = FakeTransport({
        ("GET", "https://www.reddit.com/search.json"): FakeResponse(200, {"data": {"children": [_reddit_child()]}}),
    })
    monkeypatch.setattr(launch_kit_router, "TRANSPORT", transport)
    client = client_for(launch_kit_router, monkeypatch=monkeypatch, db=env.db)

    searched = data(client.post("/api/v1/launch-kit/pain-points/search", headers=H,
                                json={"query": "onboarding drop-off", "product_name": "Menivor"}))
    assert searched["count"] == 1

    drafts = data(client.get("/api/v1/launch-kit/pain-points/drafts", headers=H))["drafts"]
    assert len(drafts) == 1
    draft_id = drafts[0]["id"]

    approved = data(client.post(f"/api/v1/launch-kit/pain-points/drafts/{draft_id}", headers=H,
                                json={"status": "approved"}))
    assert approved["status"] == "approved"

    assert client.post(f"/api/v1/launch-kit/pain-points/drafts/{draft_id}", headers=OTHER,
                       json={"status": "dismissed"}).status_code == 404


def test_router_backlinks_defaults_to_the_free_fallback(env, monkeypatch):
    monkeypatch.delenv(backlinks_source.DATAFORSEO_LOGIN_ENV, raising=False)
    client = client_for(launch_kit_router, monkeypatch=monkeypatch, db=env.db)
    out = data(client.get("/api/v1/launch-kit/backlinks", headers=H, params={"domain": "rival.com"}))
    assert out["live"] is False
    assert out["fallback_directories"]


def test_router_checklist_and_mark_step(env, monkeypatch):
    client = client_for(launch_kit_router, monkeypatch=monkeypatch, db=env.db)
    checklist = data(client.get("/api/v1/launch-kit/checklist", headers=H,
                                params={"product_name": "Oxhan Atelier"}))
    assert checklist["done"] == 0

    marked = data(client.post("/api/v1/launch-kit/checklist/step", headers=H,
                              json={"product_name": "Oxhan Atelier", "step_key": "build_in_public",
                                   "status": "done"}))
    assert marked["status"] == "done"

    checklist_after = data(client.get("/api/v1/launch-kit/checklist", headers=H,
                                      params={"product_name": "Oxhan Atelier"}))
    assert checklist_after["done"] == 1


def test_router_rejects_a_bad_step_status(env, monkeypatch):
    client = client_for(launch_kit_router, monkeypatch=monkeypatch, db=env.db)
    resp = client.post("/api/v1/launch-kit/checklist/step", headers=H,
                       json={"product_name": "Oxhan Atelier", "step_key": "build_in_public", "status": "maybe"})
    assert resp.status_code == 422
