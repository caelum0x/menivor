"""Trend-pull providers: fake TikTok payload → TrendSignal → EXISTING scorer.

No real network: the Playwright transport is substituted with an in-memory
``FakeTransport`` that returns canned JSON, and the service test swaps in a fake
``TrendPullProvider`` that yields canned posts. Pins the ported contract:

* ``hashtag_analysis`` pure helpers (normalize / co-occur / prioritize / merge /
  ``bucket_daily_counts`` / ``native_sound_id``).
* ``TikTokPullClient`` over a fake transport → raw ``itemList`` → daily counts →
  ``TrendSignal`` → ``score_trend`` recommends the rising trend.
* Provider registry: register / resolve / unknown-id fallback.
* Graceful degradation: an unready transport yields ``[]`` and disables the
  provider — never raises.
* Consent/allowlist ToS gate blocks a pull when consent is absent or the target
  is off-allowlist, and ``TrendsPullService.run_pull`` records an observation
  only when the gate passes.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from datetime import timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.trends.providers import base as pull_base
from app.domains.trends.providers import consent as pull_consent
from app.domains.trends.providers import hashtag_analysis as ha
from app.domains.trends.providers.tiktok_pull import TikTokPullClient
from app.domains.trends.scoring import TrendSignal, score_trend
from app.models.db import models as _models  # noqa: F401 - register jobs/consent tables
from app.models.db import trends as _trends  # noqa: F401 - register trend_observations
from app.models.db.base import Base


# =========================================================================== #
# Fakes
# =========================================================================== #
class FakeTransport:
    """Canned-JSON transport double (keyed by URL substring). No network."""

    def __init__(self, responses: list[tuple[str, dict]], *, ready: bool = True) -> None:
        self._responses = responses
        self._ready = ready
        self.signed: list[str] = []

    def is_ready(self) -> bool:
        return self._ready

    def ms_token(self) -> str | None:
        return "fake-token"

    async def sign_url(self, url: str, *, session_index=None) -> str:
        self.signed.append(url)
        return url + "&X-Bogus=fake"

    async def fetch(self, signed_url: str, headers=None, *, session_index=None) -> str:
        for substr, body in self._responses:
            if substr in signed_url:
                return json.dumps(body)
        return json.dumps({"itemList": [], "hasMore": False})

    async def health_check(self) -> dict:
        return {"ready": self._ready, "healthy_sessions": 1 if self._ready else 0}


def _post(pid: str, create_time: int, tags: list[str], music_id: str = "m1") -> dict:
    return {
        "id": pid,
        "createTime": create_time,
        "music": {"id": music_id, "title": "sound"},
        "textExtra": [{"hashtagName": t} for t in tags],
    }


# One rising hashtag: post counts climb across four days (oldest→newest).
_DAY = 86400
_RISING_POSTS = (
    [_post(f"a{i}", 1_600_000_000, ["fyp", "dance"]) for i in range(1)]
    + [_post(f"b{i}", 1_600_000_000 + _DAY, ["fyp"]) for i in range(3)]
    + [_post(f"c{i}", 1_600_000_000 + 2 * _DAY, ["fyp", "viral"]) for i in range(9)]
    + [_post(f"d{i}", 1_600_000_000 + 3 * _DAY, ["fyp"]) for i in range(27)]
)


# =========================================================================== #
# hashtag_analysis — pure helpers
# =========================================================================== #
def test_normalize_hashtags_strips_dedupes_lowercases():
    assert ha.normalize_hashtags(["#FYP", " fyp ", "Dance", "", "#dance"]) == ["fyp", "dance"]


def test_cooccurring_hashtags_counts_once_per_post():
    posts = [
        {"textExtra": [{"hashtagName": "fyp"}, {"hashtagName": "fyp"}, {"hashtagName": "dance"}]},
        {"textExtra": [{"hashtagName": "fyp"}]},
    ]
    counter = ha.cooccurring_hashtags(posts)
    assert counter["fyp"] == 2  # deduped within the first post
    assert counter["dance"] == 1


def test_prioritize_hashtags_least_recently_scraped_first():
    order = ha.prioritize_hashtags({"old": 100, "never": 0, "recent": 999})
    assert order == ["never", "old", "recent"]


def test_merge_posts_dedupes_by_id_fresh_wins():
    existing = [{"id": "1", "v": "old"}, {"id": "2"}]
    fetched = [{"id": "1", "v": "new"}, {"id": "3"}]
    merged = ha.merge_posts(existing, fetched)
    ids = [p["id"] for p in merged]
    assert ids == ["2", "1", "3"]  # retained old (2) + fresh (1,3)
    assert next(p for p in merged if p["id"] == "1")["v"] == "new"


def test_native_sound_id_picks_dominant():
    posts = [_post("1", 1, [], "sound-A"), _post("2", 1, [], "sound-A"), _post("3", 1, [], "sound-B")]
    assert ha.native_sound_id(posts) == "sound-A"


def test_bucket_daily_counts_is_contiguous_oldest_to_newest():
    counts = ha.bucket_daily_counts(_RISING_POSTS, tz=timezone.utc)
    assert counts == (1, 3, 9, 27)  # four contiguous days, rising


def test_bucket_daily_counts_empty_when_no_createtime():
    assert ha.bucket_daily_counts([{"id": "x"}], tz=timezone.utc) == ()


# =========================================================================== #
# TikTokPullClient over a fake transport → scorer
# =========================================================================== #
def test_pull_hashtag_posts_returns_raw_itemlist():
    transport = FakeTransport(
        [
            ("challenge/detail", {"challengeInfo": {"challenge": {"id": "999"}}}),
            ("challenge/item_list", {"itemList": _RISING_POSTS, "hasMore": False}),
        ]
    )
    client = TikTokPullClient(transport=transport)
    posts = asyncio.run(client.pull_hashtag_posts("#fyp", max_posts=100))
    assert len(posts) == len(_RISING_POSTS)
    assert transport.signed, "the transport must have signed the request URL"


def test_fake_payload_feeds_existing_scorer_and_recommends():
    transport = FakeTransport(
        [
            ("challenge/detail", {"challengeInfo": {"challenge": {"id": "999"}}}),
            ("challenge/item_list", {"itemList": _RISING_POSTS, "hasMore": False}),
        ]
    )
    posts = asyncio.run(TikTokPullClient(transport=transport).pull_hashtag_posts("fyp"))
    counts = ha.bucket_daily_counts(posts, tz=timezone.utc)
    signal = TrendSignal(trend_id="fyp", kind="hashtag", counts=counts, label="fyp")
    score = score_trend(signal)
    assert score.opportunity > 0
    assert score.recommend is True
    assert score.phase in ("emerging", "rising")


def test_sound_pull_paginates_until_hasmore_false():
    page1 = {"itemList": [_post("1", 1, [])], "hasMore": True, "cursor": 30}
    page2 = {"itemList": [_post("2", 1, [])], "hasMore": False}
    calls = {"n": 0}

    class Paging(FakeTransport):
        async def fetch(self, signed_url, headers=None, *, session_index=None):
            calls["n"] += 1
            return json.dumps(page1 if calls["n"] == 1 else page2)

    client = TikTokPullClient(transport=Paging([]))
    posts = asyncio.run(client.pull_sound_posts("123", max_posts=100))
    assert [p["id"] for p in posts] == ["1", "2"]


# =========================================================================== #
# Graceful degradation — never raises
# =========================================================================== #
def test_unready_transport_yields_empty_and_never_raises():
    client = TikTokPullClient(transport=FakeTransport([], ready=False))
    assert client.is_ready() is False
    assert asyncio.run(client.pull_hashtag_posts("fyp")) == []
    assert asyncio.run(client.pull_trending()) == []


def test_blank_target_short_circuits_to_empty():
    client = TikTokPullClient(transport=FakeTransport([]))
    assert asyncio.run(client.pull_hashtag_posts("")) == []
    assert asyncio.run(client.pull_sound_posts("  ")) == []


# =========================================================================== #
# Provider registry
# =========================================================================== #
def test_registry_register_resolve_and_unknown_fallback():
    class FakeProvider:
        name = "tiktok"

        def is_enabled(self):
            return True

        async def pull_hashtag_posts(self, tag, *, max_posts=30):
            return []

        async def pull_sound_posts(self, sound_id, *, max_posts=30):
            return []

        async def pull_trending(self, *, max_posts=30):
            return []

    pull_base._ensure_providers_loaded()
    fake = FakeProvider()
    pull_base.register_trend_pull_provider(fake)
    assert pull_base.get_trend_pull_provider("tiktok") is fake
    # Unknown id falls back to the configured default rather than raising.
    assert pull_base.get_trend_pull_provider("does-not-exist") is fake


# =========================================================================== #
# Consent / allowlist ToS gate
# =========================================================================== #
def test_allowlist_closed_by_default(monkeypatch):
    monkeypatch.delenv("TREND_PULL_ALLOWLIST", raising=False)
    assert pull_consent.is_target_allowed("fyp") is False


def test_allowlist_allows_listed_and_wildcard(monkeypatch):
    monkeypatch.setenv("TREND_PULL_ALLOWLIST", "#FYP, dance")
    assert pull_consent.is_target_allowed("fyp") is True
    assert pull_consent.is_target_allowed("unlisted") is False
    monkeypatch.setenv("TREND_PULL_ALLOWLIST", "*")
    assert pull_consent.is_target_allowed("anything") is True


# =========================================================================== #
# Service end-to-end (sqlite + consent + fake provider)
# =========================================================================== #
@pytest.fixture
def db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool, future=True,
    )
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _gs():
        s = Factory()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr("app.models.db.base.get_session", _gs)
    return _gs


class _CannedProvider:
    name = "tiktok"

    def __init__(self, posts):
        self._posts = posts

    def is_enabled(self):
        return True

    async def pull_hashtag_posts(self, tag, *, max_posts=30):
        return list(self._posts)

    async def pull_sound_posts(self, sound_id, *, max_posts=30):
        return list(self._posts)

    async def pull_trending(self, *, max_posts=30):
        return list(self._posts)


def _make_job(gs, user_id: str, target: str) -> str:
    from app.models.db.repositories import JobRepository

    with gs() as session:
        job = JobRepository(session).create(
            user_id=user_id,
            kind="trends_pull",
            params={"target": target, "kind": "hashtag", "max_posts": 50, "credits_cost": 0},
        )
        return job.id


def _grant_consent(gs, user_id: str) -> None:
    from app.models.db.repositories import ConsentRepository

    with gs() as session:
        ConsentRepository(session).create(user_id, pull_consent.CONSENT_KIND, True)


def test_run_pull_records_observation_when_gate_passes(db, monkeypatch):
    monkeypatch.setenv("TREND_PULL_ALLOWLIST", "fyp")
    monkeypatch.setenv("TREND_PULL_PROVIDER", "tiktok")
    pull_base._ensure_providers_loaded()
    pull_base.register_trend_pull_provider(_CannedProvider(_RISING_POSTS))

    from app.domains.trends.service import TrendsPullService

    _grant_consent(db, "user-1")
    job_id = _make_job(db, "user-1", "fyp")

    summary = TrendsPullService().run_pull(job_id)
    assert summary["post_count"] == len(_RISING_POSTS)
    assert summary["counts"] == [1, 3, 9, 27]
    assert summary["native_sound_id"] == "m1"
    assert summary["recommend"] is True
    assert summary["observation_id"]

    # The scored observation is persisted through the UNCHANGED repository.
    from app.domains.trends.repository import TrendRepository

    with db() as session:
        rec = TrendRepository(session).recommended()
        assert any(r.trend_id == "fyp" for r in rec)


def test_run_pull_blocked_when_consent_absent(db, monkeypatch):
    monkeypatch.setenv("TREND_PULL_ALLOWLIST", "fyp")
    monkeypatch.setenv("TREND_PULL_PROVIDER", "tiktok")
    pull_base._ensure_providers_loaded()
    pull_base.register_trend_pull_provider(_CannedProvider(_RISING_POSTS))

    from app.domains.trends.service import TrendPullError, TrendsPullService

    job_id = _make_job(db, "user-2", "fyp")  # no consent recorded
    with pytest.raises(TrendPullError):
        TrendsPullService().run_pull(job_id)


def test_run_pull_blocked_when_target_off_allowlist(db, monkeypatch):
    monkeypatch.setenv("TREND_PULL_ALLOWLIST", "dance")  # 'fyp' not listed
    monkeypatch.setenv("TREND_PULL_PROVIDER", "tiktok")
    pull_base._ensure_providers_loaded()
    pull_base.register_trend_pull_provider(_CannedProvider(_RISING_POSTS))

    from app.domains.trends.service import TrendPullError, TrendsPullService

    _grant_consent(db, "user-3")
    job_id = _make_job(db, "user-3", "fyp")
    with pytest.raises(TrendPullError):
        TrendsPullService().run_pull(job_id)
