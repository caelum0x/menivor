"""Engagement autopilot: labels, rules, approvals, caps, leads and the audit log.

Runs the real autopilot, inbox reply path and extended-connection credential
code on in-memory SQLite. Only the platform HTTP calls are faked (a routing
fake transport that records every request).
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
from app.domains.social_inbox import autopilot, replies, sync
from app.domains.social_inbox.engagement_classify import classify, lead_score
from app.domains.social_inbox.engagement_models import EngagementAction, EngagementLead
from app.domains.social_inbox.models import InboxPost, InboxThread
from app.domains.social_inbox.suggestions import Suggestions
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


class RouteTransport:
    """Answers by (method, url suffix); records every call."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def request(self, method, url, *, headers=None, params=None, json=None, data=None):
        self.calls.append({"method": method, "url": url, "params": params or {}, "data": data, "json": json})
        for (m, suffix), resp in self.routes.items():
            if m == method and url.endswith(suffix):
                return resp
        raise AssertionError(f"unexpected request {method} {url}")


# --------------------------------------------------------------------------- #
# Classifier
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,kind,label", [
    ("Love this, great video!", "comment", "positive"),
    ("check my profile for free followers", "comment", "spam"),
    ("visit www.cheap-deals.shop now!!!!!!!!!", "comment", "spam"),
    ("you are an idiot", "comment", "abuse"),
    ("How much does it cost? Do you ship to Canada?", "dm", "buying_intent"),
    ("This is a scam, I want a refund", "comment", "negative"),
    ("What camera do you use?", "comment", "question"),
    ("ok", "comment", "neutral"),
    ("here is the link https://example.com/file", "dm", "neutral"),
])
def test_classify(text, kind, label):
    assert classify(text, kind=kind).label == label


def test_blocked_words_count_as_spam_and_whole_words_only():
    assert classify("buy my course", blocked_words=["course"]).label == "spam"
    assert classify("of course it works", blocked_words=["cour"]).label != "spam"
    assert classify("I'd order this in order to try").label != "buying_intent"


def test_lead_score_ranks_dms_higher():
    c = classify("price and shipping please?", kind="dm")
    assert lead_score(c, kind="dm") > lead_score(c, kind="comment") > 0


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
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

    for module in (sync, replies, autopilot, ext_connections):
        monkeypatch.setattr(module, "get_session", _session)
    monkeypatch.setenv("SOCIAL_TOKEN_KEY", "unit-test-autopilot-key")
    monkeypatch.setattr(replies, "publishing_open", lambda: True)
    monkeypatch.setattr(autopilot, "publishing_open", lambda: True)
    monkeypatch.setattr(autopilot, "suggest", lambda **kw: Suggestions(
        replies=("Thank you, that means a lot!",), source="template", intent="praise"))
    return Factory


def _seed(Factory):
    """A creator with a connected Facebook Page, one published video and four comments."""
    now = datetime.now(timezone.utc)
    with Factory() as s:
        user = User(email="c@example.com", api_key_hash=hashlib.sha256(b"c").hexdigest(), credits=0)
        s.add(user)
        s.flush()
        s.add(PlatformConnection(
            user_id=user.id, platform="facebook", status="connected",
            access_token_enc=crypto_tokens.encrypt("user-token"), target_kind="page", target_id="page1",
            target_name="Shop", target_token_enc=crypto_tokens.encrypt("page-token"),
            scopes="pages_read_user_content,pages_manage_engagement", targets=[], meta={},
        ))
        post = InboxPost(user_id=user.id, platform="facebook", external_id="vid1", title="Launch video",
                         posted_at=now - timedelta(hours=3))
        s.add(post)
        s.flush()
        texts = {
            "c1": ("Ana", "Love this, great video!"),
            "c2": ("Bot", "check my profile for free followers"),
            "c3": ("Ben", "How much does it cost? Do you ship to Canada?"),
            "c4": ("Troll", "you are an idiot"),
        }
        for i, (cid, (author, text)) in enumerate(texts.items()):
            at = now - timedelta(minutes=10 + i)
            s.add(InboxThread(
                user_id=user.id, post_id=post.id, platform="facebook", kind="comment", external_thread_id=cid,
                author_name=author, text=text, status="needs_reply", last_inbound_at=at, last_message_at=at,
                messages=[{"id": cid, "author": author, "text": text, "at": at.isoformat(), "from_me": False}],
            ))
        s.commit()
        return user.id


def _transport():
    return RouteTransport({
        ("POST", "/c1/likes"): _Resp(200, {"success": True}),
        ("POST", "/c5/likes"): _Resp(200, {"success": True}),
        ("POST", "/c2"): _Resp(200, {"success": True}),
        ("POST", "/c1/comments"): _Resp(200, {"id": "r1"}),
        ("POST", "/c5/comments"): _Resp(200, {"id": "r5"}),
    })


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #
def test_autopilot_is_off_by_default(db):
    uid = _seed(db)
    t = _transport()
    assert autopilot.run_for_user(uid, transport=t)["checked"] == 0
    assert t.calls == []
    with db() as s:
        overview = autopilot.overview(s, uid)
    fb = next(p for p in overview["platforms"] if p["platform"] == "facebook")
    assert fb["enabled"] is False and fb["reply_mode"] == "approve"
    assert fb["support"]["like"] is True and fb["support"]["hide"] is True
    yt = next(p for p in overview["platforms"] if p["platform"] == "youtube")
    assert yt["support"]["like"] is False and "YouTube" in yt["support"]["like_note"]


def test_rules_like_hide_route_flag_and_draft(db):
    uid = _seed(db)
    autopilot.update_settings(uid, "facebook", {"enabled": True})
    t = _transport()
    summary = autopilot.run_for_user(uid, transport=t)
    assert summary["checked"] == 4
    assert summary["liked"] == 1 and summary["hidden"] == 1
    assert summary["leads"] == 1 and summary["flagged"] == 1 and summary["drafts"] == 1
    assert summary["replies_sent"] == 0  # approval required by default
    urls = [c["url"] for c in t.calls]
    assert any(u.endswith("/c1/likes") for u in urls)
    hide = next(c for c in t.calls if c["url"].endswith("/c2"))
    assert hide["data"]["is_hidden"] == "true" and hide["data"]["access_token"] == "page-token"
    assert not any(u.endswith("/comments") for u in urls)

    with db() as s:
        spam_thread = s.query(InboxThread).filter_by(external_thread_id="c2").one()
        assert spam_thread.status == "done"
        lead = s.query(EngagementLead).one()
        assert lead.author_name == "Ben" and lead.status == "new" and lead.source == "comment"

    pending = autopilot.list_actions(uid, statuses=("pending_approval",))
    assert pending["total"] == 1
    draft = pending["actions"][0]
    assert draft["kind"] == "reply" and draft["text"] == "Thank you, that means a lot!"
    assert draft["text_source"] == "template" and draft["label"] == "positive"

    # A second run finds nothing new: every message is handled once.
    again = autopilot.run_for_user(uid, transport=_transport())
    assert again["liked"] == again["hidden"] == again["drafts"] == 0


def test_approve_sends_edited_reply_and_reject_discards(db):
    uid = _seed(db)
    autopilot.update_settings(uid, "facebook", {"enabled": True})
    autopilot.run_for_user(uid, transport=_transport())
    draft = autopilot.list_actions(uid, statuses=("pending_approval",))["actions"][0]

    import app.domains.social_inbox.replies as replies_mod

    t = _transport()
    original = replies_mod.default_transport
    replies_mod.default_transport = lambda: t
    try:
        done = autopilot.approve(uid, draft["id"], text="Thanks Ana, glad it helped.")
    finally:
        replies_mod.default_transport = original
    assert done["status"] == "done" and done["actor"] == "creator"
    reply_call = next(c for c in t.calls if c["url"].endswith("/c1/comments"))
    assert reply_call["data"]["message"] == "Thanks Ana, glad it helped."
    with db() as s:
        assert s.query(InboxThread).filter_by(external_thread_id="c1").one().status == "replied"
    with pytest.raises(autopilot.AutopilotError):
        autopilot.reject(uid, draft["id"])  # already handled


def test_auto_mode_sends_immediately(db, monkeypatch):
    uid = _seed(db)
    autopilot.update_settings(uid, "facebook", {"enabled": True, "reply_mode": "auto"})
    t = _transport()
    monkeypatch.setattr(replies, "default_transport", lambda: t)
    summary = autopilot.run_for_user(uid, transport=t)
    assert summary["replies_sent"] == 1 and summary["drafts"] == 0
    assert any(c["url"].endswith("/c1/comments") for c in t.calls)


def test_auto_mode_falls_back_to_draft_when_sending_is_closed(db, monkeypatch):
    uid = _seed(db)
    monkeypatch.setattr(autopilot, "publishing_open", lambda: False)
    autopilot.update_settings(uid, "facebook", {"enabled": True, "reply_mode": "auto"})
    summary = autopilot.run_for_user(uid, transport=_transport())
    assert summary["replies_sent"] == 0 and summary["drafts"] == 1
    draft = autopilot.list_actions(uid, statuses=("pending_approval",))["actions"][0]
    assert "Waiting for approval" in draft["reason"]


def test_daily_cap_skips_extra_platform_actions(db):
    uid = _seed(db)
    autopilot.update_settings(uid, "facebook", {"enabled": True, "daily_cap": 1})
    summary = autopilot.run_for_user(uid, transport=_transport())
    assert summary["liked"] + summary["hidden"] == 1
    assert summary["skipped"] == 1
    skipped = autopilot.list_actions(uid, statuses=("skipped",))["actions"][0]
    assert "Daily limit of 1" in skipped["reason"]
    with db() as s:
        overview = autopilot.overview(s, uid)
    fb = next(p for p in overview["platforms"] if p["platform"] == "facebook")
    assert fb["used_today"] == 1


def test_settings_changes_are_validated_and_audited(db):
    uid = _seed(db)
    with pytest.raises(autopilot.AutopilotError):
        autopilot.update_settings(uid, "facebook", {"reply_mode": "yolo"})
    with pytest.raises(autopilot.AutopilotError):
        autopilot.update_settings(uid, "facebook", {"daily_cap": 5000})
    with pytest.raises(autopilot.AutopilotError) as exc:
        autopilot.update_settings(uid, "myspace", {"enabled": True})
    assert exc.value.status_code == 404
    record = autopilot.update_settings(uid, "facebook", {"enabled": True, "blocked_words": [" Promo ", "promo"]})
    assert record["blocked_words"] == ["promo"]
    log = autopilot.list_actions(uid, kinds=("settings",))["actions"]
    assert len(log) == 1 and "Autopilot: off -> on" in log[0]["reason"] and log[0]["actor"] == "creator"
    autopilot.update_settings(uid, "facebook", {"enabled": True})  # no change, no audit row
    assert autopilot.list_actions(uid, kinds=("settings",))["total"] == 1


def test_leads_are_owner_scoped_and_updatable(db):
    uid = _seed(db)
    autopilot.update_settings(uid, "facebook", {"enabled": True})
    autopilot.run_for_user(uid, transport=_transport())
    lead = autopilot.list_leads(uid)["leads"][0]
    assert lead["score"] > 0 and "how much" in lead["signals"]
    with db() as s:
        stranger = User(email="s@example.com", api_key_hash=hashlib.sha256(b"s").hexdigest(), credits=0)
        s.add(stranger)
        s.commit()
        stranger_id = stranger.id
    with pytest.raises(autopilot.AutopilotError) as exc:
        autopilot.update_lead(stranger_id, lead["id"], status="won")
    assert exc.value.status_code == 404
    updated = autopilot.update_lead(uid, lead["id"], status="contacted", note="Sent price list")
    assert updated["status"] == "contacted" and updated["note"] == "Sent price list"
    with pytest.raises(autopilot.AutopilotError):
        autopilot.update_lead(uid, lead["id"], status="maybe")


def test_new_message_after_handling_is_processed_again(db):
    uid = _seed(db)
    autopilot.update_settings(uid, "facebook", {"enabled": True})
    autopilot.run_for_user(uid, transport=_transport())
    now = datetime.now(timezone.utc)
    with db() as s:
        post = s.query(InboxPost).one()
        s.add(InboxThread(
            user_id=uid, post_id=post.id, platform="facebook", kind="comment", external_thread_id="c5",
            author_name="Cy", text="Amazing work, thank you", status="needs_reply", last_inbound_at=now,
            last_message_at=now,
            messages=[{"id": "c5", "author": "Cy", "text": "Amazing work, thank you", "at": now.isoformat(),
                       "from_me": False}],
        ))
        s.commit()
    summary = autopilot.run_for_user(uid, transport=_transport())
    assert summary["checked"] == 1 and summary["liked"] == 1 and summary["drafts"] == 1
    with db() as s:
        assert s.query(EngagementAction).filter_by(kind="like").count() == 2


def test_http_settings_and_leads_endpoints(db, monkeypatch):
    from fastapi import FastAPI
    from starlette.responses import JSONResponse
    from starlette.testclient import TestClient

    from app.domains.social_inbox import autopilot_router
    from app.models.exception import HttpException
    from app.utils import utils

    @contextmanager
    def _session():
        session = db()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    monkeypatch.setattr(autopilot_router, "get_session", _session)
    app = FastAPI()
    app.include_router(autopilot_router.router)
    app.add_exception_handler(HttpException, lambda request, exc: JSONResponse(
        status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)))
    client = TestClient(app)
    _seed(db)
    headers = {"x-api-key": "c"}

    resp = client.get("/api/v1/social-inbox/autopilot", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["pending_approvals"] == 0

    put = client.put("/api/v1/social-inbox/autopilot/facebook", headers=headers,
                     json={"enabled": True, "reply_mode": "approve", "daily_cap": 20})
    assert put.status_code == 200, put.text
    assert put.json()["data"]["enabled"] is True and put.json()["data"]["daily_cap"] == 20

    bad = client.put("/api/v1/social-inbox/autopilot/facebook", headers=headers, json={"reply_mode": "sometimes"})
    assert bad.status_code == 400

    leads = client.get("/api/v1/social-inbox/leads", headers=headers)
    assert leads.status_code == 200 and leads.json()["data"]["total"] == 0
    assert client.get("/api/v1/social-inbox/autopilot/activity?kind=settings", headers=headers).json()["data"]["total"] == 1
