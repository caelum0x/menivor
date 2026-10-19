"""Extended publish platforms: connectors, formats, OAuth connect, scheduling.

Connector tests drive the real request assembly / response parsing against a
fake :class:`Transport` and assert the exact API contract (the network is the
only thing faked). Service tests run on an in-memory SQLite database with the
real encryption, state and scheduling code.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.publishing.extended import catalog, formats, oauth
from app.domains.publishing.extended import connections as conn_service
from app.domains.publishing.extended import posts as post_service
from app.domains.publishing.extended.connectors import PublishContext, PublishError, get, registered
from app.domains.publishing.extended.connectors.bluesky import tag_facets
from app.domains.publishing.extended.connectors.linkedin import little_text
from app.domains.publishing.extended.models import PlatformConnection, PlatformPost
from app.models.const import TASK_STATE_COMPLETE
from app.models.db.base import Base
from app.models.db.models import Job, User


# --------------------------------------------------------------------------- #
# Fake network
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, status_code=200, body=None, headers=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.headers = headers or {}

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


@pytest.fixture()
def video(tmp_path):
    path = tmp_path / "reel.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 5000)
    return str(path)


# --------------------------------------------------------------------------- #
# Registry + catalog
# --------------------------------------------------------------------------- #
def test_extended_registry_is_separate_from_native():
    from app.domains.publishing.connectors import available_platforms

    assert set(registered()) == {"facebook", "linkedin", "x", "threads", "pinterest", "bluesky",
                                 "telegram", "discord", "mastodon"}
    assert set(available_platforms()) == {"youtube", "tiktok", "instagram"}


def test_server_availability_states(monkeypatch):
    for name in ("FACEBOOK_CLIENT_ID", "FACEBOOK_CLIENT_SECRET", "FACEBOOK_REDIRECT_URI", "X_API_PLAN",
                 "PUBLISHING_OAUTH_REDIRECT_URL", "WEB_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    state, note = catalog.server_availability("facebook")
    assert state == catalog.NOT_CONFIGURED and "developer app" in note
    assert catalog.server_availability("bluesky")[0] == catalog.AVAILABLE  # free, no app needed
    assert catalog.server_availability("x")[0] == catalog.PLAN_REQUIRED
    monkeypatch.setenv("X_API_PLAN", "free")
    assert catalog.server_availability("x")[0] == catalog.PLAN_REQUIRED
    monkeypatch.setenv("X_API_PLAN", "basic")
    assert catalog.server_availability("x")[0] == catalog.NOT_CONFIGURED  # plan ok, app not registered
    monkeypatch.setenv("FACEBOOK_CLIENT_ID", "id")
    monkeypatch.setenv("FACEBOOK_CLIENT_SECRET", "secret")
    monkeypatch.setenv("PUBLISHING_OAUTH_REDIRECT_URL", "https://menivor.test/connections")
    assert catalog.server_availability("facebook")[0] == catalog.AVAILABLE


# --------------------------------------------------------------------------- #
# Formats
# --------------------------------------------------------------------------- #
def test_fit_keeps_hashtags_and_shortens_caption_for_x():
    caption = "word " * 100
    fitted = formats.fit("x", caption=caption, hashtags=["#one", "two", "three", "four", "five", "six", "seven"])
    assert fitted.length <= 280
    assert fitted.hashtags == ("one", "two", "three", "four", "five")
    assert fitted.text.endswith("#one #two #three #four #five")
    assert any(i.field == "hashtags" for i in fitted.issues)
    assert any(i.field == "caption" for i in fitted.issues)
    assert fitted.ok


def test_fit_titles_only_where_the_platform_has_them():
    assert formats.fit("pinterest", caption="c", title="T" * 150).title.endswith("...")
    assert len(formats.fit("pinterest", caption="c", title="T" * 150).title) <= 100
    assert formats.fit("x", caption="c", title="ignored").title == ""


def test_bluesky_counts_graphemes_not_code_points():
    flag_heavy = "é" * 300  # 300 graphemes, 600 code points
    fitted = formats.fit("bluesky", caption=flag_heavy)
    assert fitted.length <= 300


def test_check_video_size_limit():
    issues = formats.check_video("bluesky", size_bytes=200 * 1024 * 1024, duration_s=None)
    assert issues and issues[0].level == "error"
    assert formats.check_video("facebook", size_bytes=10, duration_s=30) == ()


def test_linkedin_little_text_escapes_and_templates_hashtags():
    out = little_text("Launch (v2) is live! #AI #video_tools")
    assert "\\(v2\\)" in out
    assert "{hashtag|\\#|AI}" in out and "{hashtag|\\#|video_tools}" in out


def test_bluesky_tag_facets_use_utf8_byte_offsets():
    text = "café #tag"
    facet = tag_facets(text)[0]
    assert facet["index"] == {"byteStart": 6, "byteEnd": 10}
    assert facet["features"][0]["tag"] == "tag"


# --------------------------------------------------------------------------- #
# Connectors (exact API contracts)
# --------------------------------------------------------------------------- #
def test_facebook_publishes_by_file_url_then_polls_status():
    t = FakeTransport([
        _Resp(200, {"id": "vid1"}),
        _Resp(200, {"status": {"video_status": "processing"}}),
        _Resp(200, {"status": {"video_status": "ready"}, "permalink_url": "/page/videos/vid1/"}),
    ])
    ctx = PublishContext(platform="facebook", access_token="user", target_id="p1", target_token="pagetok",
                         video_url="https://r2/x.mp4", text="hello", title="T")
    step = get("facebook").publish(ctx, transport=t)
    assert step.status == "processing" and step.progress == {"video_id": "vid1"}
    assert t.calls[0]["url"] == "https://graph-video.facebook.com/v21.0/p1/videos"
    assert t.calls[0]["data"]["file_url"] == "https://r2/x.mp4"
    assert t.calls[0]["data"]["access_token"] == "pagetok"
    done = get("facebook").resume(PublishContext(platform="facebook", access_token="u", target_token="pagetok",
                                                 progress=step.progress), transport=t)
    assert done.done and done.url == "https://www.facebook.com/page/videos/vid1/"


def test_facebook_requires_a_page():
    with pytest.raises(PublishError, match="choose which Facebook Page"):
        get("facebook").publish(PublishContext(platform="facebook", access_token="u", video_url="u"),
                                transport=FakeTransport([]))


def test_linkedin_upload_finalize_then_post(video):
    size = len(open(video, "rb").read())
    t = FakeTransport([
        _Resp(200, {"value": {"video": "urn:li:video:9", "uploadToken": "tok",
                              "uploadInstructions": [{"uploadUrl": "https://up/1", "firstByte": 0,
                                                      "lastByte": size - 1}]}}),
        _Resp(200, {}, headers={"ETag": "etag-1"}),
        _Resp(200, {}),
        _Resp(200, {"status": "AVAILABLE"}),
        _Resp(201, {}, headers={"x-restli-id": "urn:li:share:77"}),
    ])
    ctx = PublishContext(platform="linkedin", access_token="lt", video_path=video, text="Hi #AI",
                         meta={"member_urn": "urn:li:person:abc"}, title="Clip")
    step = get("linkedin").publish(ctx, transport=t)
    assert step.done and step.external_id == "urn:li:share:77"
    assert step.url == "https://www.linkedin.com/feed/update/urn:li:share:77/"
    init = t.calls[0]
    assert init["json"]["initializeUploadRequest"]["owner"] == "urn:li:person:abc"
    assert init["json"]["initializeUploadRequest"]["fileSizeBytes"] == size
    assert init["headers"]["LinkedIn-Version"] and init["headers"]["X-Restli-Protocol-Version"] == "2.0.0"
    assert t.calls[1]["method"] == "PUT" and len(t.calls[1]["data"]) == size
    assert t.calls[2]["json"]["finalizeUploadRequest"]["uploadedPartIds"] == ["etag-1"]
    post = t.calls[4]["json"]
    assert post["author"] == "urn:li:person:abc"
    assert post["content"]["media"]["id"] == "urn:li:video:9"
    assert "{hashtag|\\#|AI}" in post["commentary"]


def test_linkedin_waits_while_video_processing(video):
    t = FakeTransport([_Resp(200, {"status": "PROCESSING"})])
    step = get("linkedin").resume(PublishContext(platform="linkedin", access_token="lt",
                                                 progress={"video_urn": "urn:li:video:1", "owner": "urn:li:person:a"}),
                                  transport=t)
    assert step.status == "processing"


def test_x_chunked_upload_then_tweet(video, monkeypatch):
    from app.domains.publishing.extended.connectors import x as x_mod

    monkeypatch.setattr(x_mod, "CHUNK_BYTES", 2048)
    t = FakeTransport([
        _Resp(200, {"data": {"id": "m1"}}),
        _Resp(204), _Resp(204), _Resp(204),
        _Resp(200, {"data": {"id": "m1", "processing_info": {"state": "pending"}}}),
    ])
    ctx = PublishContext(platform="x", access_token="xt", video_path=video, text="clip")
    step = get("x").publish(ctx, transport=t)
    assert step.status == "processing" and step.progress["media_id"] == "m1"
    assert t.calls[0]["json"]["media_category"] == "tweet_video"
    assert all("/append" in c["url"] for c in t.calls[1:4])
    assert b'name="segment_index"\r\n\r\n2' in t.calls[3]["data"]
    assert t.calls[1]["headers"]["Content-Type"].startswith("multipart/form-data; boundary=")

    t2 = FakeTransport([_Resp(200, {"data": {"processing_info": {"state": "succeeded"}}}),
                        _Resp(201, {"data": {"id": "t9"}})])
    done = get("x").resume(PublishContext(platform="x", access_token="xt", text="clip", progress=step.progress),
                           transport=t2)
    assert done.done and done.url == "https://x.com/i/web/status/t9"
    assert t2.calls[1]["json"] == {"text": "clip", "media": {"media_ids": ["m1"]}}


def test_threads_container_then_publish():
    t = FakeTransport([
        _Resp(200, {"id": "c1"}),
        _Resp(200, {"status": "FINISHED"}),
        _Resp(200, {"id": "post1"}),
        _Resp(200, {"permalink": "https://www.threads.net/@me/post/abc"}),
    ])
    ctx = PublishContext(platform="threads", access_token="tt", external_account_id="u1",
                         video_url="https://r2/x.mp4", text="hi")
    step = get("threads").publish(ctx, transport=t)
    assert step.done and step.external_id == "post1"
    assert t.calls[0]["params"]["media_type"] == "VIDEO"
    assert t.calls[2]["params"]["creation_id"] == "c1"


def test_threads_error_status_fails():
    t = FakeTransport([_Resp(200, {"id": "c1"}), _Resp(200, {"status": "ERROR", "error_message": "bad codec"})])
    with pytest.raises(PublishError, match="bad codec"):
        get("threads").publish(PublishContext(platform="threads", access_token="t", external_account_id="u",
                                              video_url="https://r2/x.mp4"), transport=t)


def test_pinterest_register_upload_then_pin(video):
    t = FakeTransport([
        _Resp(201, {"media_id": "md1", "upload_url": "https://s3/upload", "upload_parameters": {"key": "k1"}}),
        _Resp(204),
        _Resp(200, {"status": "succeeded"}),
        _Resp(201, {"id": "pin1"}),
    ])
    ctx = PublishContext(platform="pinterest", access_token="pt", target_id="board9", video_path=video,
                         text="desc", title="Title")
    step = get("pinterest").publish(ctx, transport=t)
    assert step.done and step.url == "https://www.pinterest.com/pin/pin1/"
    assert b'name="key"\r\n\r\nk1' in t.calls[1]["data"]
    pin = t.calls[3]["json"]
    assert pin["board_id"] == "board9"
    assert pin["media_source"] == {"source_type": "video_id", "media_id": "md1", "cover_image_key_frame_time": 1}


def test_bluesky_session_upload_and_record(video):
    t = FakeTransport([
        _Resp(200, {"accessJwt": "jwt", "did": "did:plc:me", "handle": "me.bsky.social"}),
        _Resp(200, {"blob": {"$type": "blob", "ref": {"$link": "bafy"}, "mimeType": "video/mp4", "size": 10}}),
        _Resp(200, {"uri": "at://did:plc:me/app.bsky.feed.post/3kabc", "cid": "cid1"}),
    ])
    ctx = PublishContext(platform="bluesky", access_token="app-pass", external_account_id="did:plc:me",
                         video_path=video, text="New clip #menivor", meta={"pds": "https://bsky.social"})
    step = get("bluesky").publish(ctx, transport=t)
    assert step.done and step.url == "https://bsky.app/profile/me.bsky.social/post/3kabc"
    assert t.calls[0]["json"] == {"identifier": "did:plc:me", "password": "app-pass"}
    assert t.calls[1]["headers"]["Content-Type"] == "video/mp4"
    record = t.calls[2]["json"]["record"]
    assert record["embed"]["$type"] == "app.bsky.embed.video"
    assert record["facets"][0]["features"][0]["tag"] == "menivor"


def test_bluesky_bad_password_is_explained(video):
    t = FakeTransport([_Resp(401, {"error": "AuthenticationRequired"})])
    with pytest.raises(PublishError, match="app password"):
        get("bluesky").publish(PublishContext(platform="bluesky", access_token="x", external_account_id="me",
                                              video_path=video), transport=t)


# --------------------------------------------------------------------------- #
# OAuth URLs
# --------------------------------------------------------------------------- #
def test_x_authorize_uses_pkce(monkeypatch):
    monkeypatch.setenv("X_CLIENT_ID", "xid")
    monkeypatch.setenv("X_CLIENT_SECRET", "xsecret")
    monkeypatch.setenv("X_REDIRECT_URI", "https://menivor.test/connections")
    verifier = oauth.new_code_verifier()
    url = oauth.authorize_url("x", "st", verifier=verifier)
    q = parse_qs(urlparse(url).query)
    assert q["code_challenge_method"] == ["S256"]
    assert q["code_challenge"] == [oauth.code_challenge(verifier)]
    assert "media.write" in q["scope"][0]
    assert "xsecret" not in url


# --------------------------------------------------------------------------- #
# Services on SQLite
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

    from app.domains.publishing import native_service

    for module in (conn_service, post_service, native_service):
        monkeypatch.setattr(module, "get_session", _session)
    monkeypatch.setenv("SOCIAL_TOKEN_KEY", "unit-test-ext-key")
    for p in ("PINTEREST", "FACEBOOK", "LINKEDIN", "THREADS", "X"):
        monkeypatch.setenv(f"{p}_CLIENT_ID", f"{p.lower()}-id")
        monkeypatch.setenv(f"{p}_CLIENT_SECRET", f"{p.lower()}-secret")
    monkeypatch.setenv("PUBLISHING_OAUTH_REDIRECT_URL", "https://menivor.test/connections")
    monkeypatch.delenv("X_API_PLAN", raising=False)
    return Factory


def _user(Factory, email="a@example.com") -> str:
    with Factory() as s:
        u = User(email=email, api_key_hash=hashlib.sha256(email.encode()).hexdigest(), credits=0)
        s.add(u)
        s.commit()
        return u.id


def _job(Factory, user_id) -> str:
    with Factory() as s:
        j = Job(user_id=user_id, state=TASK_STATE_COMPLETE, result_key="results/final.mp4", params={})
        s.add(j)
        s.commit()
        return j.id


def _connect_pinterest(Factory, uid, boards):
    start = conn_service.start_oauth(uid, "pinterest")
    t = FakeTransport([
        _Resp(200, {"access_token": "pin-access", "refresh_token": "pin-refresh", "expires_in": 2592000,
                    "scope": "boards:read,pins:write"}),
        _Resp(200, {"username": "maker"}),
        _Resp(200, {"items": boards}),
    ])
    return start, t, conn_service.finish_oauth(uid, "code-1", start["state"], transport=t)


def test_oauth_connect_stores_encrypted_tokens_and_asks_for_board(db):
    uid = _user(db)
    start, t, record = _connect_pinterest(db, uid, [{"id": "b1", "name": "Ideas"}, {"id": "b2", "name": "Ads"}])
    assert start["authorize_url"].startswith("https://www.pinterest.com/oauth/?")
    assert t.calls[0]["headers"]["Authorization"].startswith("Basic ")
    assert record["state"] == "needs_target"
    assert [x["name"] for x in record["connection"]["targets"]] == ["Ideas", "Ads"]
    assert "pin-access" not in str(record)
    with db() as s:
        row = s.query(PlatformConnection).one()
        assert row.access_token_enc and "pin-access" not in row.access_token_enc
    chosen = conn_service.select_target(uid, "pinterest", "b2", transport=FakeTransport([]))
    assert chosen["state"] == "connected" and chosen["connection"]["target_name"] == "Ads"


def test_oauth_state_is_single_use_and_bound_to_the_creator(db):
    uid = _user(db)
    other = _user(db, "b@example.com")
    start = conn_service.start_oauth(uid, "pinterest")
    with pytest.raises(oauth.ConnectError, match="invalid or expired"):
        conn_service.finish_oauth(other, "code", start["state"], transport=FakeTransport([]))
    used, _, record = _connect_pinterest(db, uid, [{"id": "b1", "name": "Only"}])
    assert record["state"] == "connected"  # single board auto-selected
    with pytest.raises(oauth.ConnectError, match="invalid or expired"):
        conn_service.finish_oauth(uid, "code", used["state"], transport=FakeTransport([]))  # replay


def test_x_connect_blocked_without_paid_plan(db):
    uid = _user(db)
    with pytest.raises(oauth.ConnectError) as exc:
        conn_service.start_oauth(uid, "x")
    assert exc.value.status_code == 409 and "charges for API access" in str(exc.value)


def test_bluesky_connect_with_app_password(db):
    uid = _user(db)
    t = FakeTransport([_Resp(200, {"accessJwt": "jwt", "did": "did:plc:z", "handle": "z.bsky.social"})])
    record = conn_service.connect_bluesky(uid, "@z.bsky.social", "abcd-efgh-ijkl-mnop", transport=t)
    assert record["state"] == "connected"
    assert record["connection"]["account_name"] == "@z.bsky.social"
    assert "abcd-efgh" not in str(record)
    creds = conn_service.credentials(uid, "bluesky", transport=FakeTransport([]))
    assert creds.access_token == "abcd-efgh-ijkl-mnop" and creds.external_account_id == "did:plc:z"


def test_expired_token_refreshes_before_use(db):
    uid = _user(db)
    _connect_pinterest(db, uid, [{"id": "b1", "name": "Only"}])
    with db() as s:
        row = s.query(PlatformConnection).one()
        row.token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        s.commit()
    t = FakeTransport([_Resp(200, {"access_token": "fresh", "expires_in": 3600})])
    creds = conn_service.credentials(uid, "pinterest", transport=t)
    assert creds.access_token == "fresh"
    assert t.calls[0]["data"] == {"grant_type": "refresh_token", "refresh_token": "pin-refresh"}


def test_create_posts_reports_every_unready_platform(db):
    uid = _user(db)
    jid = _job(db, uid)
    with pytest.raises(post_service.PostError) as exc:
        post_service.create_posts(uid, jid, [post_service.PostDraft("pinterest", caption="hi"),
                                             post_service.PostDraft("x", caption="hi")])
    problems = {p["platform"]: p["message"] for p in exc.value.details}
    assert "Connect Pinterest first" in problems["pinterest"]
    assert "charges for API access" in problems["x"]
    with db() as s:
        assert s.query(PlatformPost).count() == 0  # all or nothing


def test_schedule_then_due_runner_publishes(db, monkeypatch, video):
    uid = _user(db)
    jid = _job(db, uid)
    _connect_pinterest(db, uid, [{"id": "b1", "name": "Only"}])
    monkeypatch.setattr(post_service, "_enqueue", lambda post_id: None)
    when = datetime.now(timezone.utc) + timedelta(hours=2)
    created = post_service.create_posts(uid, jid, [post_service.PostDraft("pinterest", caption="Nice reel",
                                                                          title="Reel", hashtags=("ads",))],
                                        scheduled_at=when)
    assert created[0]["status"] == "scheduled" and created[0]["can_cancel"]

    from app.domains.publishing import native_service
    import app.platform.storage.r2 as r2

    monkeypatch.setattr(native_service, "_run_content_gate",
                        lambda platform, req: SimpleNamespace(can_publish=True, decision="publish", reasons={}))
    monkeypatch.setattr(native_service, "_persist_gate_result", lambda job_id, gate: None)
    import shutil

    def _fake_download(key, job_id):
        copy = video + ".dl"
        shutil.copy(video, copy)
        return copy

    monkeypatch.setattr(native_service, "_download_temp", _fake_download)
    monkeypatch.setattr(r2, "get_r2_client", lambda: SimpleNamespace(presign_get=lambda key: "https://r2/x.mp4"))
    recorded = []
    import app.telemetry.events as events

    monkeypatch.setattr(events, "record_event", lambda *a, **k: recorded.append((a, k)))

    t = FakeTransport([
        _Resp(201, {"media_id": "md1", "upload_url": "https://s3/u", "upload_parameters": {}}),
        _Resp(204),
        _Resp(200, {"status": "processing"}),
    ])
    assert post_service.tick(now=datetime.now(timezone.utc), transport=t)["claimed"] == 0  # not due yet
    counts = post_service.tick(now=when + timedelta(seconds=1), transport=t)
    assert counts["processing"] == 1
    t2 = FakeTransport([_Resp(200, {"status": "succeeded"}), _Resp(201, {"id": "pin7"})])
    counts = post_service.tick(now=when + timedelta(minutes=5), transport=t2)
    assert counts["published"] == 1
    listing = post_service.list_for_user(uid)
    post = listing["posts"][0]
    assert post["status"] == "published" and post["url"] == "https://www.pinterest.com/pin/pin7/"
    assert t2.calls[1]["json"]["description"] == "Nice reel\n\n#ads"
    assert recorded[-1][0][2] == "native_published"
    assert recorded[-1][1]["payload"]["external_id"] == "pin7"


def test_failed_post_keeps_platform_reason_and_can_retry(db, monkeypatch, video):
    uid = _user(db)
    jid = _job(db, uid)
    _connect_pinterest(db, uid, [{"id": "b1", "name": "Only"}])
    monkeypatch.setattr(post_service, "_enqueue", lambda post_id: None)
    from app.domains.publishing import native_service
    import app.platform.storage.r2 as r2

    monkeypatch.setattr(native_service, "_run_content_gate",
                        lambda platform, req: SimpleNamespace(can_publish=True, decision="publish", reasons={}))
    monkeypatch.setattr(native_service, "_persist_gate_result", lambda job_id, gate: None)
    monkeypatch.setattr(native_service, "_download_temp", lambda key, job_id: video)
    monkeypatch.setattr(r2, "get_r2_client", lambda: SimpleNamespace(presign_get=lambda key: "https://r2/x.mp4"))
    created = post_service.create_posts(uid, jid, [post_service.PostDraft("pinterest", caption="c")])
    t = FakeTransport([_Resp(400, {"message": "Board not found"})])
    result = post_service.run_post(created[0]["id"], transport=t)
    assert result["status"] == "failed"
    post = post_service.list_for_user(uid)["posts"][0]
    assert "Board not found" in post["error"] and post["can_retry"]
    retried = post_service.retry(uid, post["id"])
    assert retried["status"] == "scheduled" and retried["attempts"] == 0


def test_cancel_only_before_start(db, monkeypatch):
    uid = _user(db)
    jid = _job(db, uid)
    _connect_pinterest(db, uid, [{"id": "b1", "name": "Only"}])
    monkeypatch.setattr(post_service, "_enqueue", lambda post_id: None)
    created = post_service.create_posts(uid, jid, [post_service.PostDraft("pinterest", caption="c")],
                                        scheduled_at=datetime.now(timezone.utc) + timedelta(days=1))
    other = _user(db, "c@example.com")
    with pytest.raises(post_service.PostError) as exc:
        post_service.cancel(other, created[0]["id"])
    assert exc.value.status_code == 404
    assert post_service.cancel(uid, created[0]["id"])["status"] == "canceled"


# --------------------------------------------------------------------------- #
# HTTP surface
# --------------------------------------------------------------------------- #
@pytest.fixture()
def client(db, monkeypatch):
    from fastapi import FastAPI
    from starlette.responses import JSONResponse
    from starlette.testclient import TestClient

    from app.domains.publishing.extended import router as router_mod
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

    monkeypatch.setattr(router_mod, "get_session", _session)
    app = FastAPI()
    app.include_router(router_mod.router)
    app.add_exception_handler(HttpException, lambda request, exc: JSONResponse(
        status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)))
    return TestClient(app)


def test_platforms_endpoint_is_token_free_and_owner_scoped(client, db):
    uid = _user(db, "owner@example.com")
    _connect_pinterest(db, uid, [{"id": "b1", "name": "Only"}])
    _user(db, "other@example.com")
    mine = client.get("/api/v1/publishing/platforms", headers={"x-api-key": "owner@example.com"})
    assert mine.status_code == 200, mine.text
    body = mine.json()["data"]
    pin = next(p for p in body["platforms"] if p["platform"] == "pinterest")
    assert pin["state"] == "connected" and pin["connection"]["target_name"] == "Only"
    assert "pin-access" not in mine.text and "pin-refresh" not in mine.text
    x = next(p for p in body["platforms"] if p["platform"] == "x")
    assert x["state"] == "plan_required"
    theirs = client.get("/api/v1/publishing/platforms", headers={"x-api-key": "other@example.com"})
    pin_other = next(p for p in theirs.json()["data"]["platforms"] if p["platform"] == "pinterest")
    assert pin_other["connection"] is None and pin_other["state"] == "not_connected"


def test_format_check_endpoint(client, db):
    _user(db, "owner@example.com")
    resp = client.post("/api/v1/publishing/format-check", headers={"x-api-key": "owner@example.com"},
                       json={"drafts": [{"platform": "threads", "caption": "a" * 700, "hashtags": ["one", "two"]}]})
    assert resp.status_code == 200, resp.text
    result = resp.json()["data"]["results"][0]
    assert result["length"] <= 500 and result["hashtags"] == ["one"]
    bad = client.post("/api/v1/publishing/format-check", headers={"x-api-key": "owner@example.com"},
                      json={"drafts": [{"platform": "myspace", "caption": "x"}]})
    assert bad.status_code == 404
