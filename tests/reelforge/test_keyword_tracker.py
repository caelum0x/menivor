"""Keyword tracker (Menivor Growth phase 2): add/remove, free-vs-paid limit,
rank history (7/30-day change), manual refresh, and the beat's "everything
due" pass. Every rank reading goes through a fake search function — never a
live network call — mirroring tests/reelforge/test_appaudit.py's visibility
tests and tests/reelforge/test_wave2_competitors.py's refresh_due pattern.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.domains.appaudit.visibility import reset_cache
from app.domains.integrations.scope import resolve as resolve_scope
from app.domains.keyword_tracker import models as _models  # noqa: F401  (registers tables)
from app.domains.keyword_tracker import router as keyword_tracker_router
from app.domains.keyword_tracker import service
from app.domains.keyword_tracker.models import KeywordRankSnapshot, TrackedKeyword
from app.domains.keyword_tracker.service import KeywordTrackerError
from tests.reelforge._integrations_fakes import FakeTransport, Resp, add_workspace
from tests.reelforge._wave2_support import H, client_for, data, make_env

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
APPLE_TOKEN = "https://appleid.apple.com/auth/oauth2/token"
APPLE_BASE = "https://api.searchads.apple.com/api/v5"


def _fake_search(rows_by_term: dict[str, list[dict[str, str]]]):
    def search(term: str, *, country: str = "us") -> list[dict[str, str]]:
        return rows_by_term.get(term, [])
    return search


def _apple_creds() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.PKCS8,
                            encryption_algorithm=serialization.NoEncryption()).decode()
    return json.dumps({"client_id": "SEARCHADS.abc", "team_id": "TEAM123", "key_id": "KEY456", "private_key": pem},
                      separators=(",", ":"))


def _connect_apple(env, monkeypatch, *, workspace_id: str | None = None):
    """Connects an apple_search_ads account for ``env.uid``'s personal scope
    (or ``workspace_id``'s, if given); returns the resulting Scope."""
    from app.domains.integrations import service as integrations_service

    monkeypatch.setenv("SOCIAL_TOKEN_KEY", "unit-test-keyword-tracker-key")
    t = FakeTransport().add("POST", APPLE_TOKEN, Resp(200, {"access_token": "ap-tok", "expires_in": 3600}))
    t.add("GET", f"{APPLE_BASE}/acls", Resp(200, {"data": [{"orgId": 4001, "orgName": "Acme", "currency": "USD"}]}))
    with env.db.scope() as s:
        sc = resolve_scope(s, env.uid, workspace_id=workspace_id)
        integrations_service.connect_api_key(s, sc, "apple_search_ads", _apple_creds(), transport=t)
    return sc


def _insights_transport(popularity_by_term: dict[str, int | None]) -> FakeTransport:
    """A fresh insights ad group gets provisioned, then every term is added in
    one `bulk` call (nothing was already a targeting keyword, so `find`
    returns nothing)."""
    t = FakeTransport()
    t.add("POST", f"{APPLE_BASE}/campaigns", Resp(200, {"data": {"id": 9001}}))
    t.add("POST", f"{APPLE_BASE}/campaigns/9001/adgroups", Resp(200, {"data": {"id": 7001}}))
    t.add("POST", f"{APPLE_BASE}/campaigns/9001/adgroups/7001/targetingkeywords/find", Resp(200, {"data": []}))
    t.add("POST", f"{APPLE_BASE}/campaigns/9001/adgroups/7001/targetingkeywords/bulk", Resp(200, {"data": [
        {"text": term, "searchPopularity": score} for term, score in popularity_by_term.items()]}))
    return t


@pytest.fixture(autouse=True)
def _reset_itunes_cache():
    reset_cache()
    yield
    reset_cache()


@pytest.fixture()
def env(monkeypatch):
    return make_env(monkeypatch)


# --------------------------------------------------------------------------- #
# add / dedupe / validation
# --------------------------------------------------------------------------- #
def test_add_keyword_runs_an_immediate_rank_check(env):
    search = _fake_search({"calorie tracker": [{"app_id": "rival", "title": "Rival"},
                                               {"app_id": "999", "title": "CalDesk"}]})
    with env.db.scope() as s:
        out = service.add_keyword(s, env.uid, app_id="999", term="calorie tracker", app_name="CalDesk",
                                  search=search, now=NOW, cache_now=0.0)
    assert out["current_rank"] == 2
    assert out["checked_count"] == 2
    assert out["last_checked_at"] is not None
    assert out["change_7d"] is None and out["change_30d"] is None  # no older baseline yet
    with env.db.scope() as s:
        assert s.query(KeywordRankSnapshot).count() == 1


def test_add_keyword_rejects_a_non_numeric_app_id(env):
    with env.db.scope() as s:
        with pytest.raises(KeywordTrackerError) as err:
            service.add_keyword(s, env.uid, app_id="not-a-number", term="fitness", now=NOW, cache_now=0.0)
    assert err.value.status_code == 422


def test_add_keyword_rejects_a_blank_term(env):
    with env.db.scope() as s:
        with pytest.raises(KeywordTrackerError) as err:
            service.add_keyword(s, env.uid, app_id="999", term="   ", now=NOW, cache_now=0.0)
    assert err.value.status_code == 422


def test_add_keyword_is_idempotent_per_app_term_country(env):
    search = _fake_search({})
    with env.db.scope() as s:
        service.add_keyword(s, env.uid, app_id="999", term="fitness", search=search, now=NOW, cache_now=0.0)
    with env.db.scope() as s:
        with pytest.raises(KeywordTrackerError) as err:
            service.add_keyword(s, env.uid, app_id="999", term="fitness", search=search, now=NOW, cache_now=1.0)
    assert err.value.status_code == 409
    # A different country is a distinct tracked keyword, not a duplicate.
    with env.db.scope() as s:
        service.add_keyword(s, env.uid, app_id="999", term="fitness", country="gb", search=search, now=NOW,
                            cache_now=2.0)
        assert len(s.query(TrackedKeyword).all()) == 2


def test_free_tier_limit_blocks_the_eleventh_keyword(env, monkeypatch):
    monkeypatch.setattr(service, "keyword_limit", lambda _uid: service.FREE_KEYWORD_LIMIT)
    search = _fake_search({})
    with env.db.scope() as s:
        for i in range(service.FREE_KEYWORD_LIMIT):
            service.add_keyword(s, env.uid, app_id="999", term=f"term{i}", search=search, now=NOW, cache_now=float(i))
    with env.db.scope() as s:
        with pytest.raises(KeywordTrackerError) as err:
            service.add_keyword(s, env.uid, app_id="999", term="one too many", search=search, now=NOW,
                                cache_now=99.0)
    assert err.value.status_code == 402
    assert "10" in err.value.message


def test_paid_limit_is_higher_than_free(env, monkeypatch):
    monkeypatch.setattr(service, "keyword_limit", lambda _uid: service.PAID_KEYWORD_LIMIT)
    with env.db.scope() as s:
        out = service.list_keywords(s, env.uid, now=NOW)
    assert out["limit"] == service.PAID_KEYWORD_LIMIT
    assert out["paid"] is True


def test_keyword_limit_fails_closed_to_free_on_an_entitlement_outage(env, monkeypatch):
    def _boom(_uid):
        raise RuntimeError("entitlements db down")
    monkeypatch.setattr("app.services.user_entitlements.user_entitlements", _boom)
    assert service.keyword_limit(env.uid) == service.FREE_KEYWORD_LIMIT


# --------------------------------------------------------------------------- #
# ownership
# --------------------------------------------------------------------------- #
def test_remove_keyword_is_owner_scoped(env):
    search = _fake_search({})
    with env.db.scope() as s:
        kw = service.add_keyword(s, env.uid, app_id="999", term="fitness", search=search, now=NOW, cache_now=0.0)
    with env.db.scope() as s:
        with pytest.raises(KeywordTrackerError) as err:
            service.remove_keyword(s, env.other, kw["id"])
    assert err.value.status_code == 404
    with env.db.scope() as s:
        assert service.remove_keyword(s, env.uid, kw["id"]) is True
    with env.db.scope() as s:
        assert s.query(TrackedKeyword).count() == 0
        assert s.query(KeywordRankSnapshot).count() == 0  # snapshots cascade-delete


# --------------------------------------------------------------------------- #
# history / 7-30 day change
# --------------------------------------------------------------------------- #
def test_change_7d_and_30d_compare_against_the_closest_older_snapshot(env):
    search_now = _fake_search({"fitness": [{"app_id": "999", "title": "CalDesk"}]})  # rank 1 today
    with env.db.scope() as s:
        kw = service.add_keyword(s, env.uid, app_id="999", term="fitness", search=search_now, now=NOW, cache_now=0.0)
        row = s.get(TrackedKeyword, kw["id"])
        # Backfill two older snapshots as if the beat had been running for a month.
        s.add(KeywordRankSnapshot(keyword_id=row.id, checked_at=NOW - timedelta(days=8), position=5, checked_count=50))
        s.add(KeywordRankSnapshot(keyword_id=row.id, checked_at=NOW - timedelta(days=35), position=20, checked_count=50))
        s.flush()
    with env.db.scope() as s:
        row = s.get(TrackedKeyword, kw["id"])
        view = service.keyword_view(s, row, now=NOW)
    assert view["current_rank"] == 1
    assert view["change_7d"] == 4  # 5 -> 1: improved by 4 places
    assert view["change_30d"] == 19  # 20 -> 1
    assert len(view["history"]) >= 1


def test_change_is_none_when_currently_unranked(env):
    search = _fake_search({})  # app never appears
    with env.db.scope() as s:
        kw = service.add_keyword(s, env.uid, app_id="999", term="fitness", search=search, now=NOW, cache_now=0.0)
    assert kw["current_rank"] is None
    assert kw["change_7d"] is None and kw["change_30d"] is None


def test_history_window_excludes_snapshots_older_than_requested_days(env):
    with env.db.scope() as s:
        kw = service.add_keyword(s, env.uid, app_id="999", term="fitness", search=_fake_search({}), now=NOW,
                                 cache_now=0.0)
        row = s.get(TrackedKeyword, kw["id"])
        s.add(KeywordRankSnapshot(keyword_id=row.id, checked_at=NOW - timedelta(days=90), position=10, checked_count=50))
        s.flush()
    with env.db.scope() as s:
        row = s.get(TrackedKeyword, kw["id"])
        view = service.keyword_view(s, row, now=NOW, history_days=30)
    dates = [h["date"] for h in view["history"]]
    assert (NOW - timedelta(days=90)).date().isoformat() not in dates


# --------------------------------------------------------------------------- #
# refresh (manual + beat "everything due")
# --------------------------------------------------------------------------- #
def test_refresh_one_updates_the_rank_and_appends_a_snapshot(env):
    with env.db.scope() as s:
        kw = service.add_keyword(s, env.uid, app_id="999", term="fitness",
                                 search=_fake_search({"fitness": [{"app_id": "999", "title": "CalDesk"}]}),
                                 now=NOW, cache_now=0.0)
    assert kw["current_rank"] == 1
    later_search = _fake_search({"fitness": [{"app_id": "rival", "title": "Rival"},
                                             {"app_id": "999", "title": "CalDesk"}]})
    reset_cache()  # force a fresh search instead of reusing the 24h-cached first result
    with env.db.scope() as s:
        out = service.refresh_one(s, env.uid, kw["id"], search=later_search, now=NOW + timedelta(hours=1),
                                  cache_now=10_000.0)
    assert out["current_rank"] == 2
    with env.db.scope() as s:
        assert s.query(KeywordRankSnapshot).count() == 2


def test_a_store_error_keeps_the_previous_rank_and_records_the_error(env, monkeypatch):
    from app.domains.capture.store import StoreError

    def boom(_term, *, country="us"):
        raise StoreError(502, "the App Store search is unavailable")

    with env.db.scope() as s:
        kw = service.add_keyword(s, env.uid, app_id="999", term="fitness",
                                 search=_fake_search({"fitness": [{"app_id": "999", "title": "CalDesk"}]}),
                                 now=NOW, cache_now=0.0)
    assert kw["current_rank"] == 1
    reset_cache()  # force the fake search to actually run instead of reusing the cached first result
    with env.db.scope() as s:
        out = service.refresh_one(s, env.uid, kw["id"], search=boom, now=NOW + timedelta(hours=1), cache_now=1.0)
    assert out["current_rank"] == 1  # unchanged, not wiped to None
    assert "unavailable" in out["last_error"]
    with env.db.scope() as s:
        # The failed check never appends a new (fabricated) snapshot.
        assert s.query(KeywordRankSnapshot).count() == 1


def test_refresh_due_skips_keywords_checked_within_the_last_20_hours(env):
    with env.db.scope() as s:
        kw = service.add_keyword(s, env.uid, app_id="999", term="fitness", search=_fake_search({}), now=NOW,
                                 cache_now=0.0)
    with env.db.scope() as s:
        done = service.refresh_due(s, now=NOW + timedelta(hours=1), search=_fake_search({}), cache_now=1.0)
    assert done == 0
    with env.db.scope() as s:
        done = service.refresh_due(s, now=NOW + timedelta(hours=21), search=_fake_search({}), cache_now=2.0)
    assert done == 1
    with env.db.scope() as s:
        row = s.get(TrackedKeyword, kw["id"])
        # SQLite round-trips the column back as a naive datetime (it was written in UTC).
        assert row.last_checked_at.replace(tzinfo=timezone.utc) == NOW + timedelta(hours=21)


def test_refresh_due_keeps_going_after_one_keyword_fails(env, monkeypatch):
    with env.db.scope() as s:
        service.add_keyword(s, env.uid, app_id="1", term="a", search=_fake_search({}), now=NOW, cache_now=0.0)
        service.add_keyword(s, env.uid, app_id="2", term="b", search=_fake_search({}), now=NOW, cache_now=1.0)

    real_refresh = service.refresh_keyword
    calls = {"n": 0}

    def flaky(session, row, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real_refresh(session, row, **kwargs)

    monkeypatch.setattr(service, "refresh_keyword", flaky)
    with env.db.scope() as s:
        done = service.refresh_due(s, now=NOW + timedelta(hours=21), search=_fake_search({}), cache_now=2.0)
    assert done == 1  # one failed, one succeeded


# --------------------------------------------------------------------------- #
# popularity (Apple Search Ads keyword insights; only when connected)
# --------------------------------------------------------------------------- #
def test_list_keywords_without_a_scope_never_touches_popularity(env):
    with env.db.scope() as s:
        service.add_keyword(s, env.uid, app_id="999", term="fitness", search=_fake_search({}), now=NOW, cache_now=0.0)
        out = service.list_keywords(s, env.uid, now=NOW)
    assert out["apple_ads_connected"] is False
    assert out["keywords"][0]["popularity"] is None


def test_list_keywords_reports_not_connected_with_no_apple_ads_account(env):
    with env.db.scope() as s:
        service.add_keyword(s, env.uid, app_id="999", term="fitness", search=_fake_search({}), now=NOW, cache_now=0.0)
        sc = resolve_scope(s, env.uid, workspace_id=None)
        out = service.list_keywords(s, env.uid, now=NOW, scope=sc)
    assert out["apple_ads_connected"] is False
    assert out["keywords"][0]["popularity"] is None


def test_list_keywords_decorates_popularity_once_apple_ads_is_connected(env, monkeypatch):
    sc = _connect_apple(env, monkeypatch)
    with env.db.scope() as s:
        service.add_keyword(s, env.uid, app_id="999", term="fitness", search=_fake_search({}), now=NOW, cache_now=0.0)
    t = _insights_transport({"fitness": 72})
    with env.db.scope() as s:
        out = service.list_keywords(s, env.uid, now=NOW, scope=sc, transport=t)
    assert out["apple_ads_connected"] is True
    assert out["keywords"][0]["popularity"] == 72
    bulk_body = t.find("POST", f"{APPLE_BASE}/campaigns/9001/adgroups/7001/targetingkeywords/bulk")[0]["json"]
    assert [row["text"] for row in bulk_body] == ["fitness"]


def test_popularity_is_not_refetched_within_the_refresh_window(env, monkeypatch):
    sc = _connect_apple(env, monkeypatch)
    with env.db.scope() as s:
        service.add_keyword(s, env.uid, app_id="999", term="fitness", search=_fake_search({}), now=NOW, cache_now=0.0)
    with env.db.scope() as s:
        service.list_keywords(s, env.uid, now=NOW, scope=sc, transport=_insights_transport({"fitness": 72}))
    empty = FakeTransport()  # no routes registered: any call would raise AssertionError
    with env.db.scope() as s:
        out = service.list_keywords(s, env.uid, now=NOW + timedelta(hours=1), scope=sc, transport=empty)
    assert out["keywords"][0]["popularity"] == 72
    assert empty.calls == []


def test_popularity_refreshes_again_once_stale(env, monkeypatch):
    sc = _connect_apple(env, monkeypatch)
    with env.db.scope() as s:
        service.add_keyword(s, env.uid, app_id="999", term="fitness", search=_fake_search({}), now=NOW, cache_now=0.0)
    with env.db.scope() as s:
        service.list_keywords(s, env.uid, now=NOW, scope=sc, transport=_insights_transport({"fitness": 72}))
    later = FakeTransport()
    later.add("POST", f"{APPLE_BASE}/campaigns/9001/adgroups/7001/targetingkeywords/find",
             Resp(200, {"data": [{"text": "fitness", "searchPopularity": 90}]}))
    with env.db.scope() as s:
        out = service.list_keywords(s, env.uid, now=NOW + timedelta(hours=21), scope=sc, transport=later)
    assert out["keywords"][0]["popularity"] == 90


def test_popularity_fetch_failure_never_blocks_the_keyword_list(env, monkeypatch):
    sc = _connect_apple(env, monkeypatch)
    with env.db.scope() as s:
        service.add_keyword(s, env.uid, app_id="999", term="fitness", search=_fake_search({}), now=NOW, cache_now=0.0)
    broken = FakeTransport()  # no routes registered -> the provisioning call fails
    with env.db.scope() as s:
        out = service.list_keywords(s, env.uid, now=NOW, scope=sc, transport=broken)
    assert out["apple_ads_connected"] is True
    assert len(out["keywords"]) == 1
    assert out["keywords"][0]["popularity"] is None


def test_popularity_is_grouped_per_app_and_country_into_one_call_each(env, monkeypatch):
    sc = _connect_apple(env, monkeypatch)
    with env.db.scope() as s:
        service.add_keyword(s, env.uid, app_id="999", term="fitness", search=_fake_search({}), now=NOW, cache_now=0.0)
        service.add_keyword(s, env.uid, app_id="999", term="calorie tracker", search=_fake_search({}), now=NOW,
                            cache_now=0.0)
    t = FakeTransport()
    t.add("POST", f"{APPLE_BASE}/campaigns", Resp(200, {"data": {"id": 9001}}))
    t.add("POST", f"{APPLE_BASE}/campaigns/9001/adgroups", Resp(200, {"data": {"id": 7001}}))
    t.add("POST", f"{APPLE_BASE}/campaigns/9001/adgroups/7001/targetingkeywords/find", Resp(200, {"data": []}))
    t.add("POST", f"{APPLE_BASE}/campaigns/9001/adgroups/7001/targetingkeywords/bulk", Resp(200, {"data": [
        {"text": "fitness", "searchPopularity": 72}, {"text": "calorie tracker", "searchPopularity": 55}]}))
    with env.db.scope() as s:
        out = service.list_keywords(s, env.uid, now=NOW, scope=sc, transport=t)
    by_term = {k["term"]: k["popularity"] for k in out["keywords"]}
    assert by_term == {"fitness": 72, "calorie tracker": 55}
    # One `campaigns` create call total for both keywords (same app+country).
    create_calls = [c for c in t.calls if c["method"] == "POST" and c["url"] == f"{APPLE_BASE}/campaigns"]
    assert len(create_calls) == 1


# --------------------------------------------------------------------------- #
# router
# --------------------------------------------------------------------------- #
def test_router_add_list_refresh_remove(env, monkeypatch):
    monkeypatch.setattr(keyword_tracker_router, "SEARCH", _fake_search({"fitness": [{"app_id": "999", "title": "CalDesk"}]}))
    client = client_for(keyword_tracker_router, monkeypatch=monkeypatch, db=env.db)

    added = data(client.post("/api/v1/keyword-tracker", json={"app_id": "999", "term": "fitness", "app_name": "CalDesk"},
                             headers=H))
    assert added["current_rank"] == 1
    keyword_id = added["id"]

    listed = data(client.get("/api/v1/keyword-tracker", headers=H))
    assert listed["limit"] == service.FREE_KEYWORD_LIMIT
    assert len(listed["keywords"]) == 1

    refreshed = data(client.post(f"/api/v1/keyword-tracker/{keyword_id}/refresh", headers=H))
    assert refreshed["current_rank"] == 1

    removed = data(client.delete(f"/api/v1/keyword-tracker/{keyword_id}", headers=H))
    assert removed["removed"] is True

    listed_after = data(client.get("/api/v1/keyword-tracker", headers=H))
    assert listed_after["keywords"] == []


def test_router_rejects_a_duplicate_keyword_with_409(env, monkeypatch):
    monkeypatch.setattr(keyword_tracker_router, "SEARCH", _fake_search({}))
    client = client_for(keyword_tracker_router, monkeypatch=monkeypatch, db=env.db)
    client.post("/api/v1/keyword-tracker", json={"app_id": "999", "term": "fitness"}, headers=H)
    resp = client.post("/api/v1/keyword-tracker", json={"app_id": "999", "term": "fitness"}, headers=H)
    assert resp.status_code == 409


def test_router_cannot_refresh_or_delete_someone_elses_keyword(env, monkeypatch):
    from tests.reelforge._wave2_support import OTHER

    monkeypatch.setattr(keyword_tracker_router, "SEARCH", _fake_search({}))
    client = client_for(keyword_tracker_router, monkeypatch=monkeypatch, db=env.db)
    added = data(client.post("/api/v1/keyword-tracker", json={"app_id": "999", "term": "fitness"}, headers=H))
    assert client.delete(f"/api/v1/keyword-tracker/{added['id']}", headers=OTHER).status_code == 404
    assert client.post(f"/api/v1/keyword-tracker/{added['id']}/refresh", headers=OTHER).status_code == 404


def test_router_list_without_workspace_id_reports_not_connected(env, monkeypatch):
    monkeypatch.setattr(keyword_tracker_router, "SEARCH", _fake_search({}))
    client = client_for(keyword_tracker_router, monkeypatch=monkeypatch, db=env.db)
    client.post("/api/v1/keyword-tracker", json={"app_id": "999", "term": "fitness"}, headers=H)
    listed = data(client.get("/api/v1/keyword-tracker", headers=H))
    assert listed["apple_ads_connected"] is False
    assert listed["keywords"][0]["popularity"] is None


def test_router_list_with_workspace_id_shows_popularity_once_connected(env, monkeypatch):
    ws = add_workspace(env.db, env.uid)
    _connect_apple(env, monkeypatch, workspace_id=ws)
    monkeypatch.setattr(keyword_tracker_router, "SEARCH",
                        _fake_search({"fitness": [{"app_id": "999", "title": "CalDesk"}]}))
    monkeypatch.setattr(keyword_tracker_router, "TRANSPORT", _insights_transport({"fitness": 90}))
    client = client_for(keyword_tracker_router, monkeypatch=monkeypatch, db=env.db)

    client.post("/api/v1/keyword-tracker", json={"app_id": "999", "term": "fitness"}, headers=H)
    listed = data(client.get(f"/api/v1/keyword-tracker?workspace_id={ws}", headers=H))
    assert listed["apple_ads_connected"] is True
    assert listed["keywords"][0]["popularity"] == 90

    # The same keyword, read from the personal (no-workspace) scope, sees no
    # connection -- the Apple Ads account belongs to the workspace, not the user.
    personal = data(client.get("/api/v1/keyword-tracker", headers=H))
    assert personal["apple_ads_connected"] is False
