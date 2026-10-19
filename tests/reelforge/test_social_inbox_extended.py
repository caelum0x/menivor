"""Social inbox on the extended platforms: Facebook Page comments, Threads and
Bluesky replies (read, reply, like, hide) plus sync of a Facebook post end to end.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.publishing.extended import connections as ext_connections
from app.domains.publishing.extended.models import PlatformConnection
from app.domains.social_inbox import bluesky_client, facebook_client, sync, threads_client
from app.domains.social_inbox.capabilities import capabilities_for
from app.domains.social_inbox.models import InboxPost, InboxThread
from app.models.db.base import Base
from app.models.db.models import User
from app.services import crypto_tokens


class _Resp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.headers = {}

    def json(self):
        return self._body

    @property
    def text(self):
        return str(self._body)


class FakeTransport:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def request(self, method, url, *, headers=None, params=None, json=None, data=None):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "params": params or {},
                           "json": json, "data": data})
        if not self._responses:
            raise AssertionError(f"unexpected extra request: {method} {url}")
        return self._responses.pop(0)


def test_capabilities_are_honest_per_platform():
    fb = capabilities_for("facebook", connected=True, scopes="pages_read_user_content,pages_manage_engagement")
    assert fb.comments.read == fb.comments.reply == "yes" and fb.dms.read == "not_offered"
    fb_ro = capabilities_for("facebook", connected=True, scopes="pages_read_user_content")
    assert fb_ro.comments.reply == "needs_permission"
    assert capabilities_for("pinterest", connected=True).comments.read == "not_offered"
    assert "Community Management" in capabilities_for("linkedin", connected=True).comments.note
    assert capabilities_for("bluesky", connected=True).comments.reply == "yes"


def test_facebook_comment_threads_parse_and_mark_page_replies():
    t = FakeTransport([_Resp(200, {"data": [{
        "id": "c1", "message": "Love it", "from": {"id": "u9", "name": "Ana"},
        "created_time": "2026-09-20T10:00:00+0000", "like_count": 3, "permalink_url": "https://fb/c1",
        "comments": {"data": [{"id": "c1r", "message": "Thanks!", "from": {"id": "page1", "name": "Shop"},
                               "created_time": "2026-09-20T11:00:00+0000"}]},
    }]})])
    threads = facebook_client.fetch_comment_threads("ptok", "vid1", "page1", transport=t)
    assert len(threads) == 1
    th = threads[0]
    assert th.author_name == "Ana" and th.like_count == 3 and th.permalink == "https://fb/c1"
    assert th.last_from_me is True  # the Page already answered
    assert t.calls[0]["params"]["access_token"] == "ptok"


def test_facebook_permission_error_is_mapped():
    t = FakeTransport([_Resp(403, {"error": {"code": 200, "message": "Permissions error"}})])
    from app.domains.social_inbox.platform_types import InboxPlatformError

    with pytest.raises(InboxPlatformError) as exc:
        facebook_client.fetch_comment_threads("ptok", "vid1", "page1", transport=t)
    assert exc.value.permission


def test_threads_reply_is_two_step_and_hide_uses_manage_reply():
    t = FakeTransport([_Resp(200, {"id": "cont"}), _Resp(200, {"id": "reply1"})])
    assert threads_client.reply_to_comment("tok", "me1", "r9", "thanks", transport=t) == "reply1"
    assert t.calls[0]["params"]["reply_to_id"] == "r9" and t.calls[0]["params"]["media_type"] == "TEXT"
    assert t.calls[1]["params"]["creation_id"] == "cont"
    t2 = FakeTransport([_Resp(200, {"success": True})])
    threads_client.hide_comment("tok", "r9", transport=t2)
    assert t2.calls[0]["url"].endswith("/r9/manage_reply") and t2.calls[0]["params"]["hide"] == "true"


def test_bluesky_read_reply_and_like():
    session = bluesky_client.Session(access_jwt="jwt", did="did:plc:me", handle="me.bsky.social",
                                     pds="https://bsky.social")
    post_uri = "at://did:plc:me/app.bsky.feed.post/root"
    t = FakeTransport([_Resp(200, {"thread": {"post": {"uri": post_uri}, "replies": [
        {"post": {"uri": "at://did:plc:ann/app.bsky.feed.post/r1", "cid": "c-r1", "likeCount": 2,
                  "author": {"did": "did:plc:ann", "handle": "ann.bsky.social", "displayName": "Ann"},
                  "record": {"text": "so good", "createdAt": "2026-09-20T10:00:00Z"}}},
    ]}})])
    threads = bluesky_client.fetch_comment_threads(session, post_uri, transport=t)
    assert threads[0].author_name == "Ann"
    assert threads[0].permalink == "https://bsky.app/profile/ann.bsky.social/post/r1"

    reply_uri = "at://did:plc:ann/app.bsky.feed.post/r1"
    t2 = FakeTransport([
        _Resp(200, {"posts": [{"uri": post_uri, "cid": "c-root"}, {"uri": reply_uri, "cid": "c-r1"}]}),
        _Resp(200, {"uri": "at://did:plc:me/app.bsky.feed.post/new", "cid": "x"}),
    ])
    bluesky_client.reply_to_comment(session, post_uri, reply_uri, "thank you", transport=t2)
    record = t2.calls[1]["json"]["record"]
    assert record["reply"]["root"] == {"uri": post_uri, "cid": "c-root"}
    assert record["reply"]["parent"] == {"uri": reply_uri, "cid": "c-r1"}

    t3 = FakeTransport([_Resp(200, {"posts": [{"uri": reply_uri, "cid": "c-r1"}]}),
                        _Resp(200, {"uri": "at://did:plc:me/app.bsky.feed.like/l1"})])
    bluesky_client.like_comment(session, reply_uri, transport=t3)
    assert t3.calls[1]["json"]["collection"] == "app.bsky.feed.like"
    assert t3.calls[1]["json"]["record"]["subject"] == {"uri": reply_uri, "cid": "c-r1"}


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
                           future=True)
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        session = Factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    for module in (sync, ext_connections):
        monkeypatch.setattr(module, "get_session", _session)
    monkeypatch.setenv("SOCIAL_TOKEN_KEY", "unit-test-inbox-ext-key")
    return Factory


def test_sync_facebook_post_pulls_comments_with_the_page_token(db):
    with db() as s:
        user = User(email="f@example.com", api_key_hash=hashlib.sha256(b"f").hexdigest(), credits=0)
        s.add(user)
        s.flush()
        s.add(PlatformConnection(
            user_id=user.id, platform="facebook", status="connected",
            access_token_enc=crypto_tokens.encrypt("user-token"), target_kind="page", target_id="page1",
            target_token_enc=crypto_tokens.encrypt("page-token"), scopes="", targets=[], meta={},
        ))
        post = InboxPost(user_id=user.id, platform="facebook", external_id="vid1",
                         posted_at=datetime.now(timezone.utc) - timedelta(hours=1))
        s.add(post)
        s.commit()
        uid, pid = user.id, post.id
    t = FakeTransport([_Resp(200, {"data": [{
        "id": "c1", "message": "How much is it?", "from": {"id": "u1", "name": "Ben"},
        "created_time": "2026-09-24T10:00:00+0000",
    }]})])
    result = sync.sync_post(uid, pid, transport=t)
    assert result == {"post_id": pid, "state": "ok", "threads": 1}
    assert t.calls[0]["params"]["access_token"] == "page-token"
    with db() as s:
        thread = s.query(InboxThread).one()
        assert thread.author_name == "Ben" and thread.status == "needs_reply"
        assert s.get(InboxPost, pid).needs_reply_count == 1


def test_sync_marks_linkedin_posts_as_open_in_app(db):
    with db() as s:
        user = User(email="l@example.com", api_key_hash=hashlib.sha256(b"l").hexdigest(), credits=0)
        s.add(user)
        s.flush()
        s.add(PlatformConnection(user_id=user.id, platform="linkedin", status="connected",
                                 access_token_enc=crypto_tokens.encrypt("tok"), targets=[], meta={}))
        post = InboxPost(user_id=user.id, platform="linkedin", external_id="urn:li:share:1",
                         posted_at=datetime.now(timezone.utc))
        s.add(post)
        s.commit()
        uid, pid = user.id, post.id
    result = sync.sync_post(uid, pid, transport=FakeTransport([]))
    assert result["state"] == "not_offered"
    with db() as s:
        assert "Community Management" in s.get(InboxPost, pid).state_note


def test_sync_reports_not_connected_for_missing_extended_connection(db):
    with db() as s:
        user = User(email="n@example.com", api_key_hash=hashlib.sha256(b"n").hexdigest(), credits=0)
        s.add(user)
        s.flush()
        post = InboxPost(user_id=user.id, platform="bluesky", external_id="at://x/app.bsky.feed.post/1",
                         posted_at=datetime.now(timezone.utc))
        s.add(post)
        s.commit()
        uid, pid = user.id, post.id
    assert sync.sync_post(uid, pid, transport=FakeTransport([]))["state"] == "not_connected"
