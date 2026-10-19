"""Automatic performance tracking - links, platform reads, schedule, results.

No external I/O: platform APIs are a fake :class:`Transport` asserting the
request shapes, and Postgres is an in-memory SQLite database.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.performance import fetchers, links, summary, tracker
from app.domains.performance.access import metrics_access
from app.domains.performance.fetchers import Access
from app.domains.performance.models import PostSnapshot, TrackedPost
from app.models.db.base import Base
from app.models.db.models import Job, JobEvent, JobPerformance, User

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


# =========================================================================== #
# Fakes
# =========================================================================== #
class _Resp:
    def __init__(self, status: int = 200, body: dict | None = None, text: str = "") -> None:
        self.status_code = status
        self._body = body or {}
        self.headers: dict = {}
        self.text = text

    def json(self):
        return self._body


class FakeTransport:
    """Routes by URL substring; records every call."""

    def __init__(self, routes: dict[str, _Resp]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str, dict | None]] = []

    def request(self, method, url, *, headers=None, params=None, json=None, data=None):
        self.calls.append((method, url, params))
        for fragment, resp in self.routes.items():
            if fragment in url:
                return resp
        return _Resp(404, {})


@pytest.fixture()
def factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
                           future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _session_factory(Factory):
    @contextmanager
    def _cm():
        session = Factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return _cm


def _user(Factory, email="creator@example.com") -> str:
    with Factory() as s:
        u = User(email=email, credits=0)
        s.add(u)
        s.commit()
        return u.id


def _job(Factory, user_id: str, subject: str, *, style: str = "", layout: str = "pip",
         source_url: str = "") -> str:
    params = {"video_subject": subject, "layout": layout}
    if style:
        params["style"] = style
    if source_url:
        params["source_url"] = source_url
    with Factory() as s:
        job = Job(user_id=user_id, params=params, script=f"{subject}. The rest of the story.")
        s.add(job)
        s.commit()
        return job.id


def _published(Factory, job_id: str, platform: str, external_id: str, *, at: datetime = NOW) -> None:
    with Factory() as s:
        s.add(JobEvent(job_id=job_id, stage="publish", status="native_published",
                       payload={"platform": platform, "external_id": external_id,
                                "url": f"https://example.test/{external_id}"},
                       created_at=at))
        s.commit()


def _deps(Factory, transport, access=None) -> tracker.Deps:
    grants = access or {}
    return tracker.Deps(
        session_factory=_session_factory(Factory),
        transport=transport,
        access_fn=lambda user_id, platform: grants.get(platform, fetchers.NO_ACCESS),
        next_location=lambda url: "",
    )


def _tiktok_ok(views=1000, likes=100, comments=10, shares=5) -> _Resp:
    return _Resp(200, {"data": {"videos": [{"id": "7300000000000000001", "view_count": views,
                                            "like_count": likes, "comment_count": comments,
                                            "share_count": shares}]},
                       "error": {"code": "ok"}})


TIKTOK = Access(connected=True, token="tt-token", scopes="user.info.basic,video.publish,video.list")


# =========================================================================== #
# Links
# =========================================================================== #
@pytest.mark.parametrize(
    ("url", "platform", "external_id"),
    [
        ("https://www.tiktok.com/@maker/video/7300000000000000001?lang=en", "tiktok", "7300000000000000001"),
        ("tiktok.com/@maker/video/7300000000000000001", "tiktok", "7300000000000000001"),
        ("https://youtube.com/shorts/abcdefghijk", "youtube", "abcdefghijk"),
        ("https://www.youtube.com/watch?v=abcdefghijk&t=3", "youtube", "abcdefghijk"),
        ("https://youtu.be/abcdefghijk", "youtube", "abcdefghijk"),
        ("https://www.instagram.com/reel/C0dEfGh1234/?igsh=x", "instagram", "C0dEfGh1234"),
        ("https://www.facebook.com/reel/1234567890123", "facebook", "1234567890123"),
        ("https://www.facebook.com/watch/?v=1234567890123", "facebook", "1234567890123"),
        ("https://x.com/maker/status/1800000000000000000", "x", "1800000000000000000"),
        ("https://twitter.com/maker/status/1800000000000000000", "x", "1800000000000000000"),
        ("https://www.threads.net/@maker/post/C1aBcDeFgHi", "threads", "C1aBcDeFgHi"),
        ("https://bsky.app/profile/maker.bsky.social/post/3kabcde12345", "bluesky", "maker.bsky.social/3kabcde12345"),
    ],
)
def test_parse_post_link(url, platform, external_id):
    link = links.parse_post_link(url)
    assert (link.platform, link.external_id) == (platform, external_id)


@pytest.mark.parametrize("url", ["", "https://example.com/video/1", "https://www.tiktok.com/@maker",
                                 "ftp://tiktok.com/video/7300000000000000001", "javascript:alert(1)"])
def test_parse_post_link_rejects(url):
    with pytest.raises(links.LinkError):
        links.parse_post_link(url)


def test_short_link_expands_on_platform_hosts_only():
    hops = {"https://vm.tiktok.com/ZMabc/": "https://www.tiktok.com/@maker/video/7300000000000000001"}
    link = links.resolve_post_link("https://vm.tiktok.com/ZMabc/", next_location=lambda u: hops.get(u, ""))
    assert link.external_id == "7300000000000000001"

    with pytest.raises(links.LinkError):
        links.resolve_post_link("https://vm.tiktok.com/ZMabc/",
                                next_location=lambda u: "http://169.254.169.254/latest/meta-data")


# =========================================================================== #
# Access
# =========================================================================== #
def test_metrics_access_asks_for_missing_scope_plainly():
    missing = metrics_access("tiktok", connected=True, scopes="user.info.basic,video.publish")
    assert not missing.reads_numbers and missing.needs_reconnect
    assert "Reconnect TikTok" in missing.note and "video.list" not in missing.note

    assert metrics_access("tiktok", connected=True, scopes="video.list").reads_numbers
    assert metrics_access("tiktok", connected=True, scopes="").reads_numbers  # unknown grant: try
    assert metrics_access("youtube", connected=True,
                          scopes="https://www.googleapis.com/auth/yt-analytics.readonly").reads_numbers
    assert metrics_access("bluesky", connected=False).reads_numbers
    assert not metrics_access("linkedin", connected=True).reads_numbers
    assert not metrics_access("tiktok", connected=False).connected


# =========================================================================== #
# Fetchers
# =========================================================================== #
def test_tiktok_numbers_keep_saves_unknown():
    tx = FakeTransport({"/v2/video/query/": _tiktok_ok()})
    stats = fetchers.fetch("u1", "tiktok", "7300000000000000001", TIKTOK, posted_on=NOW.date(), transport=tx)
    assert stats.ok
    assert (stats.views, stats.likes, stats.comments, stats.shares) == (1000, 100, 10, 5)
    assert stats.saves is None  # TikTok does not report saves: never shown as 0


def test_tiktok_without_scope_skips_the_call_and_asks_to_reconnect():
    tx = FakeTransport({})
    no_scope = Access(connected=True, token="t", scopes="user.info.basic,video.publish")
    stats = fetchers.fetch("u1", "tiktok", "7300000000000000001", no_scope, posted_on=NOW.date(), transport=tx)
    assert stats.outcome == fetchers.NEEDS_ACCESS
    assert tx.calls == []


def test_rate_limit_is_reported():
    tx = FakeTransport({"/v2/video/query/": _Resp(429, {})})
    stats = fetchers.fetch("u1", "tiktok", "7300000000000000001", TIKTOK, posted_on=NOW.date(), transport=tx)
    assert stats.outcome == fetchers.RATE_LIMITED


def test_youtube_public_counters_with_server_key(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "server-key")
    tx = FakeTransport({"youtube/v3/videos": _Resp(200, {"items": [{
        "statistics": {"viewCount": "5400", "likeCount": "300", "commentCount": "12"},
        "snippet": {"title": "Stop wasting your mornings"}}]})})
    stats = fetchers.fetch("u1", "youtube", "abcdefghijk", fetchers.NO_ACCESS, posted_on=NOW.date(), transport=tx)
    assert stats.ok and stats.views == 5400 and stats.shares is None
    assert stats.title == "Stop wasting your mornings"
    assert tx.calls[0][2]["key"] == "server-key"


def test_youtube_empty_analytics_is_not_zero_views(monkeypatch):
    """Analytics lagging (or a video off this channel) must not read as 0 views."""
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    tx = FakeTransport({
        "youtubeanalytics": _Resp(200, {"columnHeaders": [{"name": "views"}], "rows": []}),
        "youtube/v3/videos": _Resp(200, {"items": [{"statistics": {
            "viewCount": "910", "likeCount": "40", "commentCount": "3"}}]}),
    })
    yt = Access(connected=True, token="t", scopes="https://www.googleapis.com/auth/youtube.readonly")
    stats = fetchers.fetch("u1", "youtube", "abcdefghijk", yt, posted_on=NOW.date(), transport=tx)
    assert stats.ok and stats.views == 910 and stats.likes == 40
    assert stats.shares is None


def test_youtube_without_key_or_connection_needs_access(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    stats = fetchers.youtube_public("abcdefghijk", FakeTransport({}), api_key="")
    assert stats.outcome == fetchers.NEEDS_ACCESS


def test_facebook_views_from_insights_and_counts_from_summaries():
    tx = FakeTransport({
        "/video_insights": _Resp(200, {"data": [{"name": "blue_reels_play_count", "values": [{"value": 800}]}]}),
        "/1234567890": _Resp(200, {"description": "Hook line\nmore", "likes": {"summary": {"total_count": 40}},
                                   "comments": {"summary": {"total_count": 4}}}),
    })
    stats = fetchers.fetch("u1", "facebook", "1234567890", Access(True, "page-token"),
                           posted_on=NOW.date(), transport=tx)
    assert (stats.views, stats.likes, stats.comments, stats.title) == (800, 40, 4, "Hook line")


def test_threads_shortcode_resolves_to_media_id():
    tx = FakeTransport({
        "/me/threads": _Resp(200, {"data": [{"id": "1799", "shortcode": "C1aBcDeFgHi", "text": "My hook"}]}),
        "/1799/insights": _Resp(200, {"data": [
            {"name": "views", "values": [{"value": 900}]}, {"name": "likes", "values": [{"value": 30}]},
            {"name": "replies", "values": [{"value": 3}]}, {"name": "reposts", "values": [{"value": 2}]},
            {"name": "quotes", "values": [{"value": 1}]}]}),
    })
    access = Access(True, "th-token", scopes="threads_basic,threads_manage_insights")
    stats = fetchers.fetch("u1", "threads", "C1aBcDeFgHi", access, posted_on=NOW.date(), id_kind="shortcode",
                           transport=tx)
    assert stats.ok and stats.resolved_id == "1799"
    assert (stats.views, stats.likes, stats.comments, stats.shares) == (900, 30, 3, 3)


def test_x_without_paid_plan_says_so():
    tx = FakeTransport({"/2/tweets/": _Resp(403, {})})
    stats = fetchers.fetch("u1", "x", "1800000000000000000", Access(True, "x-token", scopes="tweet.read"),
                           posted_on=NOW.date(), transport=tx)
    assert stats.outcome == fetchers.NO_STATS and "paid" in stats.note


def test_bluesky_is_public_and_has_no_views():
    tx = FakeTransport({
        "resolveHandle": _Resp(200, {"did": "did:plc:abc"}),
        "getPosts": _Resp(200, {"posts": [{"likeCount": 7, "replyCount": 2, "repostCount": 1, "quoteCount": 1,
                                           "record": {"text": "Hook"}}]}),
    })
    stats = fetchers.fetch("u1", "bluesky", "maker.bsky.social/3kabcde12345", fetchers.NO_ACCESS,
                           posted_on=NOW.date(), transport=tx)
    assert stats.ok and stats.views is None and stats.likes == 7 and stats.shares == 2
    assert stats.resolved_id == "at://did:plc:abc/app.bsky.feed.post/3kabcde12345"


# =========================================================================== #
# Tracker
# =========================================================================== #
def test_tick_discovers_reads_and_feeds_hook_ranking(factory):
    uid = _user(factory)
    jid = _job(factory, uid, "Nobody tells you this about mornings", style="meme_hook")
    _published(factory, jid, "tiktok", "7300000000000000001")
    tx = FakeTransport({"/v2/video/query/": _tiktok_ok()})

    result = tracker.tick(NOW, deps=_deps(factory, tx, {"tiktok": TIKTOK}))
    assert result["discovered"] == 1 and result["ok"] == 1

    with factory() as s:
        post = s.execute(select(TrackedPost)).scalars().one()
        assert post.state == "tracking" and post.views == 1000 and post.saves is None
        assert post.next_check_at.replace(tzinfo=timezone.utc) == NOW + timedelta(hours=2)
        assert s.execute(select(PostSnapshot)).scalars().one().views == 1000
        perf = s.execute(select(JobPerformance)).scalars().one()
        assert (perf.job_id, perf.views, perf.likes, perf.platform) == (jid, 1000, 100, "tiktok")

    # A second tick right away reads nothing (not due) and discovers nothing new.
    again = tracker.tick(NOW + timedelta(minutes=5), deps=_deps(factory, tx, {"tiktok": TIKTOK}))
    assert again == {"discovered": 0, "read": 0, "ok": 0, "skipped": 0, "errors": 0}


def test_tick_marks_needs_access_and_retries_daily(factory):
    uid = _user(factory)
    jid = _job(factory, uid, "A hook")
    _published(factory, jid, "tiktok", "7300000000000000001")
    tracker.tick(NOW, deps=_deps(factory, FakeTransport({})))
    with factory() as s:
        post = s.execute(select(TrackedPost)).scalars().one()
        assert post.state == "needs_access" and "Connect TikTok" in post.note
        assert post.next_check_at.replace(tzinfo=timezone.utc) == NOW + timedelta(hours=24)
        assert post.views is None


def test_rate_limited_platform_is_skipped_for_the_rest_of_the_tick(factory):
    uid = _user(factory)
    for i in range(3):
        jid = _job(factory, uid, f"Hook number {i}")
        _published(factory, jid, "tiktok", f"730000000000000000{i}")
    tx = FakeTransport({"/v2/video/query/": _Resp(429, {})})
    result = tracker.tick(NOW, deps=_deps(factory, tx, {"tiktok": TIKTOK}))
    assert result["read"] == 1 and result["skipped"] == 2
    assert len(tx.calls) == 1


def test_posts_stop_being_read_after_sixty_days():
    assert tracker.cadence(NOW - timedelta(days=61), NOW) is None
    assert tracker.cadence(NOW - timedelta(hours=3), NOW) == timedelta(hours=2)
    assert tracker.cadence(NOW - timedelta(days=20), NOW) == timedelta(hours=72)


def test_track_link_matches_the_reel_by_caption(factory):
    uid = _user(factory)
    jid = _job(factory, uid, "Stop wasting your mornings on email")
    tx = FakeTransport({
        "/v2/video/query/": _tiktok_ok(views=2500),
        "tiktok.com/oembed": _Resp(200, {"title": "Stop wasting your mornings on email #productivity"}),
    })
    post_id = tracker.track_link(uid, "https://www.tiktok.com/@maker/video/7300000000000000001", now=NOW,
                                 deps=_deps(factory, tx, {"tiktok": TIKTOK}))
    with factory() as s:
        post = s.get(TrackedPost, post_id)
        assert post.source == "link" and post.job_id == jid and post.views == 2500

    # Pasting the same link again returns the same post (no duplicate).
    again = tracker.track_link(uid, "tiktok.com/@maker/video/7300000000000000001", now=NOW,
                               deps=_deps(factory, tx, {"tiktok": TIKTOK}))
    assert again == post_id


def test_track_link_rejects_other_sites(factory):
    uid = _user(factory)
    with pytest.raises(links.LinkError):
        tracker.track_link(uid, "https://example.com/post/1", now=NOW, deps=_deps(factory, FakeTransport({})))


def test_typed_numbers_are_owner_scoped(factory):
    owner = _user(factory)
    other = _user(factory, "other@example.com")
    tx = FakeTransport({})
    post_id = tracker.track_link(owner, "https://www.tiktok.com/@maker/video/7300000000000000009", now=NOW,
                                 deps=_deps(factory, tx))
    with pytest.raises(tracker.PostNotFound):
        tracker.add_numbers(other, post_id, {"views": 10}, now=NOW, deps=_deps(factory, tx))
    with pytest.raises(ValueError):
        tracker.add_numbers(owner, post_id, {}, now=NOW, deps=_deps(factory, tx))
    tracker.add_numbers(owner, post_id, {"views": 1200, "likes": 80}, now=NOW, deps=_deps(factory, tx))
    with factory() as s:
        post = s.get(TrackedPost, post_id)
        assert (post.views, post.likes, post.comments, post.state) == (1200, 80, None, "tracking")
    with pytest.raises(tracker.PostNotFound):
        tracker.stop_tracking(other, post_id, deps=_deps(factory, tx))
    tracker.stop_tracking(owner, post_id, deps=_deps(factory, tx))
    with factory() as s:
        assert s.execute(select(TrackedPost)).first() is None
        assert s.execute(select(PostSnapshot)).first() is None


# =========================================================================== #
# Results summary
# =========================================================================== #
def test_results_rank_hooks_and_styles_from_real_numbers(factory, monkeypatch):
    monkeypatch.setattr("app.services.oauth_connect._provider_credential", lambda provider, suffix: "cid")
    uid = _user(factory)
    winner = _job(factory, uid, "Nobody tells you this", style="meme_hook", source_url="https://shop.test/p")
    loser = _job(factory, uid, "Here is a product", layout="split")
    _published(factory, winner, "tiktok", "7300000000000000001")
    _published(factory, loser, "tiktok", "7300000000000000002")

    class Split(FakeTransport):
        def request(self, method, url, *, headers=None, params=None, json=None, data=None):
            vid = json["filters"]["video_ids"][0]
            views = 9000 if vid.endswith("1") else 1000
            return _Resp(200, {"data": {"videos": [{"id": vid, "view_count": views, "like_count": 10,
                                                    "comment_count": 1, "share_count": 1}]},
                               "error": {"code": "ok"}})

    tracker.tick(NOW, deps=_deps(factory, Split({}), {"tiktok": TIKTOK}))
    with factory() as s:
        data = summary.build_results(s, uid, now=NOW, connected={"tiktok": "video.list"})
    assert data["has_data"] and data["totals"]["views"] == 10000
    assert data["winner"]["hook"] == "Nobody tells you this."
    assert data["winner"]["remake"] == {"q": "https://shop.test/p", "preset": "meme_hook"}
    assert "9x your other hooks" in data["winner"]["why"]
    assert [s_["preset"] for s_ in data["styles"]] == ["meme_hook", "story"]
    assert data["platforms"][0] == {
        "platform": "tiktok", "label": "TikTok", "connected": True, "reads_numbers": True,
        "needs_reconnect": False, "reconnect_here": True, "can_connect": True, "note": "",
    }


def test_connect_button_hidden_when_oauth_client_missing(monkeypatch):
    from app.domains.performance.access import can_connect

    monkeypatch.delenv("TIKTOK_CLIENT_ID", raising=False)
    monkeypatch.setattr("app.services.oauth_connect._provider_credential", lambda provider, suffix: "")
    assert can_connect("tiktok") is False
    assert can_connect("facebook") is True
    monkeypatch.setattr("app.services.oauth_connect._provider_credential", lambda provider, suffix: "cid")
    assert can_connect("tiktok") is True


def test_results_empty_state_suggests_connecting(factory):
    uid = _user(factory)
    with factory() as s:
        data = summary.build_results(s, uid, now=NOW, connected={})
    assert data["has_data"] is False and data["winner"] is None and data["series"] == []
    assert data["totals"]["views"] is None
    assert [p["platform"] for p in data["platforms"]] == ["tiktok", "youtube", "instagram"]
    assert all(not p["connected"] for p in data["platforms"])


def test_series_carries_each_posts_latest_views_forward(factory):
    uid = _user(factory)
    with factory() as s:
        post = TrackedPost(user_id=uid, platform="tiktok", external_id="1", source="link", state="tracking",
                           last_checked_at=NOW, views=300)
        s.add(post)
        s.flush()
        for days_ago, views in ((3, 100), (1, 300)):
            s.add(PostSnapshot(post_id=post.id, user_id=uid, captured_at=NOW - timedelta(days=days_ago),
                               views=views))
        s.commit()
    with factory() as s:
        series = summary.build_results(s, uid, now=NOW, connected={})["series"]
    assert [p["views"] for p in series] == [100, 100, 300, 300]


# =========================================================================== #
# OAuth scopes
# =========================================================================== #
def test_connect_requests_stats_scopes(monkeypatch):
    from app.services import oauth_connect

    monkeypatch.setenv("TIKTOK_CLIENT_ID", "ck")
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "yt")
    monkeypatch.delenv("OAUTH_METRICS_SCOPES_OFF", raising=False)
    tiktok = parse_qs(urlparse(oauth_connect.build_authorize_url("tiktok", "s", "https://r")).query)
    assert tiktok["scope"] == ["user.info.basic,video.publish,video.list"]
    youtube = parse_qs(urlparse(oauth_connect.build_authorize_url("youtube", "s", "https://r")).query)
    assert "yt-analytics.readonly" in youtube["scope"][0] and "youtube.upload" in youtube["scope"][0]
    assert youtube["access_type"] == ["offline"]

    monkeypatch.setenv("OAUTH_METRICS_SCOPES_OFF", "tiktok")
    tiktok = parse_qs(urlparse(oauth_connect.build_authorize_url("tiktok", "s", "https://r")).query)
    assert tiktok["scope"] == ["user.info.basic,video.publish"]
