"""Wave L (M-2 + M-3): Telegram / Discord / Mastodon channels, their inbox, and the calendar.

Connector and inbox-client tests drive the real request assembly and response
parsing against a fake :class:`Transport` (the network is the only fake).
Service tests run on in-memory SQLite with the real encryption, scheduling,
due-runner, inbox sync and slot policy code.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.publishing import calendar_tools, tone
from app.domains.publishing.extended import channels
from app.domains.publishing.extended import connections as conn_service
from app.domains.publishing.extended import posts as post_service
from app.domains.publishing.extended.channel_models import SocialChannelCredential
from app.domains.publishing.extended.connectors import PublishContext, PublishError, get
from app.domains.publishing.extended.connectors import discord as dc
from app.domains.publishing.extended.connectors import mastodon as md
from app.domains.publishing.extended.connectors import telegram as tg
from app.domains.publishing.extended.models import PlatformPost
from app.domains.social_inbox import channel_inbox, replies, sync
from app.domains.social_inbox import discord_client, mastodon_client, telegram_client
from app.domains.social_inbox.capabilities import capabilities_for
from app.domains.social_inbox.models import InboxPost, InboxThread
from app.models.db.base import Base
from app.models.db.models import ScheduledPublish, User, Workspace, WorkspaceMember

BOT = "123456789:AAH" + "x" * 32
HOOK = "https://discord.com/api/webhooks/112233445566778899/" + "t" * 60


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
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def _tg(result):
    return _Resp(200, {"ok": True, "result": result})


@pytest.fixture()
def video(tmp_path):
    path = tmp_path / "reel.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 2000)
    return str(path)


# --------------------------------------------------------------------------- #
# Connectors
# --------------------------------------------------------------------------- #
def test_channel_connectors_are_registered_and_specs_resolve():
    for kind in ("telegram", "discord", "mastodon"):
        assert get(kind) is not None
    from app.domains.publishing.extended.catalog import EXTENDED_PLATFORMS, spec_for

    assert "telegram" not in EXTENDED_PLATFORMS  # keeps the OAuth overview unchanged
    assert spec_for("discord").rules.caption_max == 2000


def test_telegram_text_and_video_posts(video):
    t = FakeTransport([_tg({"message_id": 7})])
    ctx = PublishContext(platform="telegram", access_token=BOT, text="Hello", target_id="-1001234",
                         meta={"username": ""})
    step = get("telegram").publish(ctx, transport=t)
    assert step.done and step.external_id == "-1001234:7" and step.url == "https://t.me/c/1234/7"
    assert t.calls[0]["url"].endswith("/sendMessage") and t.calls[0]["json"]["text"] == "Hello"
    assert "parse_mode" not in t.calls[0]["json"]

    t2 = FakeTransport([_tg({"message_id": 8})])
    step = get("telegram").publish(PublishContext(platform="telegram", access_token=BOT, text="cap",
                                                  target_id="@mychan", video_path=video,
                                                  meta={"username": "mychan"}), transport=t2)
    assert step.url == "https://t.me/mychan/8"
    assert t2.calls[0]["url"].endswith("/sendVideo")
    assert b'name="video"' in t2.calls[0]["data"] and b'name="caption"' in t2.calls[0]["data"]


def test_telegram_transport_failure_never_leaks_the_token():
    t = FakeTransport([ConnectionError(f"https://api.telegram.org/bot{BOT}/sendMessage failed")])
    with pytest.raises(PublishError) as exc:
        get("telegram").publish(PublishContext(platform="telegram", access_token=BOT, text="x", target_id="1"),
                                transport=t)
    assert BOT not in str(exc.value) and exc.value.retryable
    assert exc.value.__cause__ is None and exc.value.__suppress_context__


def test_telegram_verify_requires_admin_in_channel():
    t = FakeTransport([_tg({"id": 999, "username": "menibot"}),
                       _tg({"id": -100555, "type": "channel", "title": "Our Games", "username": "ourgames",
                            "linked_chat_id": -100777}),
                       _tg({"status": "member"})])
    with pytest.raises(PublishError) as exc:
        tg.verify(BOT, "@ourgames", transport=t)
    assert "admin" in str(exc.value)
    assert tg.normalize_chat_id("https://t.me/ourgames") == "@ourgames"
    assert tg.normalize_chat_id("bad id!") == ""


def test_discord_webhook_validation_and_no_mass_mentions(video):
    assert dc.parse_webhook("https://evil.example/api/webhooks/1/2") is None
    assert dc.parse_webhook("http://discord.com/api/webhooks/112233445566778899/" + "t" * 60) is None
    assert dc.parse_webhook(HOOK.replace("discord.com", "discordapp.com")).url == HOOK
    t = FakeTransport([_Resp(200, {"id": "m1", "channel_id": "c1"})])
    step = get("discord").publish(PublishContext(platform="discord", access_token=HOOK, text="@everyone new game",
                                                 meta={"guild_id": "g1"}), transport=t)
    assert step.url == "https://discord.com/channels/g1/c1/m1"
    assert t.calls[0]["params"] == {"wait": "true"}
    assert t.calls[0]["json"]["allowed_mentions"] == {"parse": []}
    t2 = FakeTransport([_Resp(200, {"id": "m2", "channel_id": "c1"})])
    get("discord").publish(PublishContext(platform="discord", access_token=HOOK, text="v", video_path=video),
                           transport=t2)
    assert b'name="files[0]"' in t2.calls[0]["data"] and b'"allowed_mentions"' in t2.calls[0]["data"]


def test_mastodon_instance_guard():
    ok = md.normalize_instance("Mastodon.Social/", resolve=None)
    assert ok == "https://mastodon.social"
    for bad in ("http://mastodon.social", "https://10.0.0.1", "https://localhost", "https://m.social/path",
                "https://user:pw@m.social", "https://m.social:8443", "https://box.internal"):
        with pytest.raises(PublishError):
            md.normalize_instance(bad, resolve=None)
    with pytest.raises(PublishError):
        md.normalize_instance("mastodon.social", resolve=lambda url: False)


def test_mastodon_video_waits_for_processing_then_posts_once(video):
    ctx = PublishContext(platform="mastodon", access_token="tok" * 10, text="New level pack",
                         target_id="acc1", video_path=video,
                         meta={"instance_url": "https://m.social", "visibility": "unlisted", "post_id": "p1"})
    t = FakeTransport([_Resp(202, {"id": "media9", "url": None})])
    step = get("mastodon").publish(ctx, transport=t)
    assert step.status == "processing" and step.progress == {"media_id": "media9"}
    from dataclasses import replace

    t2 = FakeTransport([_Resp(206, {"id": "media9"})])
    assert get("mastodon").resume(replace(ctx, progress=step.progress), transport=t2).status == "processing"
    t3 = FakeTransport([_Resp(200, {"id": "media9", "url": "https://m.social/m.mp4"}),
                        _Resp(200, {"id": "s1", "url": "https://m.social/@me/s1"})])
    done = get("mastodon").resume(replace(ctx, progress=step.progress), transport=t3)
    assert done.done and done.url == "https://m.social/@me/s1"
    body = t3.calls[1]["json"]
    assert body["media_ids"] == ["media9"] and body["visibility"] == "unlisted"
    assert t3.calls[1]["headers"]["Idempotency-Key"]


# --------------------------------------------------------------------------- #
# Persistence fixtures
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

    for module in (conn_service, post_service, native_service, channels, channel_inbox, sync, replies):
        monkeypatch.setattr(module, "get_session", _session)
    monkeypatch.setattr(native_service, "_run_content_gate",
                        lambda platform, req: SimpleNamespace(can_publish=True, decision="publish", reasons={}))
    monkeypatch.setattr(native_service, "_persist_gate_result", lambda job_id, gate: None)
    monkeypatch.setattr(post_service, "_enqueue", lambda post_id: None)
    monkeypatch.setenv("SOCIAL_TOKEN_KEY", "unit-test-wave-l-key")
    import app.telemetry.events as events

    monkeypatch.setattr(events, "record_event", lambda *a, **k: None)
    return Factory


def _user(Factory, email="a@example.com") -> str:
    with Factory() as s:
        u = User(email=email, api_key_hash=hashlib.sha256(email.encode()).hexdigest(), credits=0)
        s.add(u)
        s.commit()
        return u.id


def _connect_telegram(uid, *, linked="-100777"):
    t = FakeTransport([_tg({"id": 999, "username": "menibot"}),
                       _tg({"id": -100555, "type": "channel", "title": "Our Games", "username": "ourgames",
                            "linked_chat_id": int(linked)}),
                       _tg({"status": "administrator", "can_post_messages": True})])
    return channels.connect_telegram(uid, BOT, "@ourgames", transport=t)


# --------------------------------------------------------------------------- #
# Channels service
# --------------------------------------------------------------------------- #
def test_connect_stores_encrypted_and_records_are_token_free(db):
    uid = _user(db)
    record = _connect_telegram(uid)
    assert record["kind"] == "telegram" and record["target_id"] == "-100555" and record["can_post"]
    assert BOT not in json.dumps(record)
    with db() as s:
        row = s.query(SocialChannelCredential).one()
        assert BOT not in row.credentials_enc and row.meta["linked_chat_id"] == "-100777"
        # The inbox tracks the channel as one conversation-shaped row.
        post = s.query(InboxPost).one()
        assert post.platform == "telegram" and channel_inbox.is_channel_post(post)
    other = _user(db, "b@example.com")
    assert channels.list_channels(other)["channels"] == []
    with pytest.raises(channels.ChannelError) as exc:
        channels.disconnect(other, record["id"])
    assert exc.value.status_code == 404


def test_text_post_scheduled_then_published_by_the_due_runner(db):
    uid = _user(db)
    ch = _connect_telegram(uid)
    when = datetime.now(timezone.utc) + timedelta(hours=1)
    created = channels.create_posts(uid, [channels.ChannelDraft(ch["id"], caption="Level 40 is out",
                                                                hashtags=("puzzle",))], scheduled_at=when)
    assert created[0]["status"] == "scheduled" and created[0]["target_id"] == ch["id"]
    assert created[0]["channel_label"] == "Our Games"
    t = FakeTransport([_tg({"message_id": 41})])
    counts = post_service.tick(now=when + timedelta(seconds=1), transport=t)
    assert counts["published"] == 1
    assert t.calls[0]["json"]["text"] == "Level 40 is out\n\n#puzzle" and t.calls[0]["json"]["chat_id"] == "-100555"
    post = post_service.list_for_user(uid)["posts"][0]
    assert post["status"] == "published" and post["url"] == "https://t.me/ourgames/41"


def test_send_test_posts_now_and_reports_failures(db):
    uid = _user(db)
    ch = _connect_telegram(uid)
    ok = channels.send_test(uid, ch["id"], "ping", transport=FakeTransport([_tg({"message_id": 5})]))
    assert ok["status"] == "published"
    bad = channels.send_test(uid, ch["id"], "ping", transport=FakeTransport([
        _Resp(400, {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"})]))
    assert bad["status"] == "failed" and "chat not found" in bad["error"]


def test_workspace_shared_channel_access(db):
    owner = _user(db)
    editor = _user(db, "e@example.com")
    viewer = _user(db, "v@example.com")
    with db() as s:
        ws = Workspace(name="Studio", owner_id=owner)
        s.add(ws)
        s.flush()
        s.add_all([WorkspaceMember(workspace_id=ws.id, user_id=owner, role="owner"),
                   WorkspaceMember(workspace_id=ws.id, user_id=editor, role="editor"),
                   WorkspaceMember(workspace_id=ws.id, user_id=viewer, role="viewer")])
        s.commit()
        ws_id = ws.id
    t = FakeTransport([_Resp(200, {"id": "112233445566778899", "name": "Hook", "channel_id": "c1",
                                   "guild_id": "g1"})])
    ch = channels.connect_discord(owner, HOOK, workspace_id=ws_id, transport=t)
    assert ch["shared"]
    listed = channels.list_channels(editor)["channels"]
    assert listed[0]["can_post"] and not listed[0]["can_manage"]
    assert not channels.list_channels(viewer)["channels"][0]["can_post"]
    channels.create_posts(editor, [channels.ChannelDraft(ch["id"], caption="hi")])
    with pytest.raises(channels.ChannelError) as exc:
        channels.create_posts(viewer, [channels.ChannelDraft(ch["id"], caption="hi")])
    assert exc.value.status_code == 409
    with pytest.raises(channels.ChannelError):
        channels.disconnect(editor, ch["id"])
    # Non-admins cannot share into a workspace.
    with pytest.raises(channels.ChannelError) as exc:
        channels.connect_discord(editor, HOOK, workspace_id=ws_id, transport=FakeTransport([_Resp(200, {
            "id": "112233445566778899", "channel_id": "c1", "guild_id": "g1"})]))
    assert exc.value.status_code == 403


def test_disconnect_cancels_unstarted_posts(db):
    uid = _user(db)
    ch = _connect_telegram(uid)
    channels.create_posts(uid, [channels.ChannelDraft(ch["id"], caption="later")],
                          scheduled_at=datetime.now(timezone.utc) + timedelta(days=1))
    result = channels.disconnect(uid, ch["id"])
    assert result["canceled_posts"] == 1
    with db() as s:
        assert s.query(PlatformPost).one().status == "canceled"
        assert s.query(InboxPost).count() == 0


def test_mastodon_connect_respects_instance_character_limit(db):
    uid = _user(db)
    t = FakeTransport([_Resp(200, {"id": "acc1", "username": "studio", "acct": "studio", "url": "https://m.social/@studio"}),
                       _Resp(200, {"configuration": {"statuses": {"max_characters": 100}}})])
    ch = channels.connect_mastodon(uid, "m.social", "tok" * 10, transport=t, resolve=None)
    assert ch["target_name"] == "@studio@m.social" and ch["caption_max"] == 100
    with pytest.raises(channels.ChannelError) as exc:
        channels.create_posts(uid, [channels.ChannelDraft(ch["id"], caption="x" * 150)])
    assert "100 characters" in exc.value.details[0]["message"]


# --------------------------------------------------------------------------- #
# Inbox
# --------------------------------------------------------------------------- #
def _tg_update(uid_, chat, text, *, sender=5, date=1_790_000_000, **extra):
    return {"update_id": uid_, "message": {"message_id": uid_ * 10, "date": date, "chat": chat,
                                           "from": {"id": sender, "first_name": "Ada"}, "text": text, **extra}}


def test_telegram_updates_become_dm_and_comment_threads():
    updates = [
        _tg_update(1, {"id": 5, "type": "private"}, "Is the game free?"),
        _tg_update(2, {"id": -100777, "type": "supergroup", "username": "ourgames_chat"}, "Love it",
                   message_thread_id=33),
        _tg_update(3, {"id": -100777, "type": "supergroup"}, "mirror", is_automatic_forward=True,
                   sender_chat={"type": "channel"}),
        _tg_update(4, {"id": -100999, "type": "group"}, "unrelated group"),
    ]
    threads = telegram_client.threads_from_updates(updates, channel_id="ch1", chat_id="-100555",
                                                   linked_chat_id="-100777")
    kinds = sorted((t.kind, t.external_thread_id) for t in threads)
    assert kinds == [("comment", "ch1:g:-100777:33"), ("dm", "ch1:dm:5")]
    comment = next(t for t in threads if t.kind == "comment")
    assert comment.permalink == "https://t.me/ourgames_chat/20"


def test_channel_inbox_sync_advances_cursor_and_replies(db, monkeypatch):
    uid = _user(db)
    ch = _connect_telegram(uid)
    with db() as s:
        pid = s.query(InboxPost).one().id
    t = FakeTransport([_tg([_tg_update(10, {"id": 5, "type": "private"}, "When is the update?")])])
    result = sync.sync_post(uid, pid, transport=t)
    assert result == {"post_id": pid, "state": "ok", "threads": 1}
    assert t.calls[0]["json"].get("offset") is None
    with db() as s:
        assert s.get(SocialChannelCredential, ch["id"]).meta["update_offset"] == 11
        thread = s.query(InboxThread).one()
        assert thread.kind == "dm" and thread.status == "needs_reply" and thread.platform == "telegram"
        tid = thread.id
    # Next poll resumes from the stored offset.
    t2 = FakeTransport([_tg([])])
    sync.sync_post(uid, pid, transport=t2)
    assert t2.calls[0]["json"]["offset"] == 11
    # Reply goes through the Bot API as a reply to the person's message.
    monkeypatch.setattr(replies, "publishing_open", lambda: True)
    t3 = FakeTransport([_tg({"message_id": 777})])
    row = replies.send_reply(uid, tid, "Next Friday!", transport=t3)
    assert row.status == "replied" and row.reply_external_id == "5:777"
    assert t3.calls[0]["json"]["chat_id"] == "5"
    assert t3.calls[0]["json"]["reply_parameters"]["message_id"] == 100


def test_telegram_webhook_conflict_is_reported_not_retried(db):
    uid = _user(db)
    _connect_telegram(uid)
    with db() as s:
        pid = s.query(InboxPost).one().id
    t = FakeTransport([_Resp(409, {"ok": False, "error_code": 409,
                                   "description": "Conflict: can't use getUpdates method while webhook is active"})])
    assert sync.sync_post(uid, pid, transport=t)["state"] == "not_offered"
    with db() as s:
        assert "webhook" in s.get(InboxPost, pid).state_note


def test_discord_threads_only_follow_replies_to_our_posts():
    ours = {"id": "100", "webhook_id": "W", "content": "New trailer"}
    msgs = [
        {"id": "101", "author": {"id": "u1", "username": "kai"}, "content": "Looks great",
         "message_reference": {"message_id": "100"}, "referenced_message": ours, "timestamp": "2026-09-24T10:00:00Z"},
        {"id": "102", "author": {"id": "u2", "username": "sam"}, "content": "random chat",
         "timestamp": "2026-09-24T10:01:00Z"},
        {"id": "103", "author": {"id": "u3", "username": "lee"}, "content": "+1",
         "message_reference": {"message_id": "101"}, "timestamp": "2026-09-24T10:02:00Z"},
        {"id": "104", "author": {"id": "u4", "username": "old"}, "content": "late reply",
         "message_reference": {"message_id": "050"}, "timestamp": "2026-09-24T10:03:00Z"},
        {"id": "105", "author": {"id": "u5", "username": "zed"}, "content": "unrelated reply",
         "message_reference": {"message_id": "099"}, "referenced_message": {"id": "099"},
         "timestamp": "2026-09-24T10:04:00Z"},
    ]
    threads = discord_client.threads_from_messages(msgs, webhook_id="W", bot_user_id="B", guild_id="g",
                                                   channel_id="c", known={"050": "040"})
    by_key = {t.external_thread_id: t for t in threads}
    assert set(by_key) == {"101", "040"}
    assert [m.external_id for m in by_key["101"].messages] == ["101", "103"]
    assert discord_client.newest_id(msgs, "90") == "105"


def test_mastodon_mentions_group_into_comments_and_dms():
    notes = [
        {"id": "1", "status": {"id": "s1", "in_reply_to_id": "mine", "visibility": "public",
                               "content": "<p>Is there a <b>demo</b>?</p>", "url": "https://m/s1",
                               "account": {"acct": "ada@x.y", "display_name": "Ada"},
                               "created_at": "2026-09-24T10:00:00Z"}},
        {"id": "2", "status": {"id": "s2", "in_reply_to_id": "r9", "visibility": "public", "content": "thanks",
                               "account": {"acct": "ada@x.y"}, "created_at": "2026-09-24T11:00:00Z"}},
        {"id": "3", "status": {"id": "s3", "visibility": "direct", "content": "hi",
                               "account": {"acct": "bo"}, "created_at": "2026-09-24T12:00:00Z"}},
    ]
    threads = mastodon_client.threads_from_notifications(notes, known={"r9": "s0"})
    keys = sorted((t.kind, t.external_thread_id) for t in threads)
    assert keys == [("comment", "s0"), ("comment", "s1"), ("dm", "dm:bo")]
    assert next(t for t in threads if t.external_thread_id == "s1").text == "Is there a demo?"
    t = FakeTransport([_Resp(200, {"id": "reply1"})])
    mastodon_client.reply("https://m", "tok", acct="bo", in_reply_to="s3", text="Hello", direct=True, transport=t)
    assert t.calls[0]["json"] == {"status": "@bo Hello", "visibility": "direct", "in_reply_to_id": "s3"}


def test_channel_capabilities():
    caps = capabilities_for("telegram", connected=True)
    assert caps.comments.reply == "yes" and caps.dms.read == "yes"
    assert capabilities_for("discord", connected=True).dms.read == "not_offered"


# --------------------------------------------------------------------------- #
# Calendar: unified entries + policy-checked moves
# --------------------------------------------------------------------------- #
def _native(Factory, uid, when, platforms=("tiktok",), status="pending"):
    from app.models.db.models import Job
    from app.models.const import TASK_STATE_COMPLETE

    with Factory() as s:
        job = Job(user_id=uid, state=TASK_STATE_COMPLETE, result_key="r/final.mp4", params={})
        s.add(job)
        s.flush()
        row = ScheduledPublish(user_id=uid, job_id=job.id, platforms=list(platforms), scheduled_at=when,
                               status=status)
        s.add(row)
        s.commit()
        return row.id


def test_calendar_entries_merge_native_and_channel_posts(db):
    uid = _user(db)
    ch = _connect_telegram(uid)
    base_time = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=2)
    nid = _native(db, uid, base_time)
    channels.create_posts(uid, [channels.ChannelDraft(ch["id"], caption="hello")],
                          scheduled_at=base_time + timedelta(hours=1))
    with db() as s:
        data = calendar_tools.entries(s, uid, base_time - timedelta(days=1), base_time + timedelta(days=1))
    sources = [(e["source"], e["platforms"][0]) for e in data["entries"]]
    assert sources == [("native", "tiktok"), ("post", "telegram")]
    assert data["entries"][0]["id"] == nid and data["entries"][1]["channel_label"] == "Our Games"
    assert data["best_hours_utc"]["tiktok"] == [13, 16, 19, 22]


def test_move_is_refused_on_min_gap_with_a_suggestion_then_forced(db):
    uid = _user(db)
    now = datetime(2030, 1, 10, 8, 0, tzinfo=timezone.utc)
    a = _native(db, uid, datetime(2030, 1, 12, 13, 0, tzinfo=timezone.utc))
    b = _native(db, uid, datetime(2030, 1, 14, 13, 0, tzinfo=timezone.utc))
    target = datetime(2030, 1, 12, 14, 0, tzinfo=timezone.utc)  # 1h after `a`; TikTok needs 3h
    with db() as s:
        check = calendar_tools.check_slot(s, uid, "native", b, target, now=now)
    assert not check.allow and "3 hours" in check.reason
    assert check.suggested_at == datetime(2030, 1, 12, 16, 0, tzinfo=timezone.utc)
    with db() as s, pytest.raises(calendar_tools.CalendarToolError) as exc:
        calendar_tools.move(s, uid, "native", b, target, now=now)
    assert exc.value.status_code == 409 and exc.value.details["check"]["suggested_at"]
    with db() as s:
        moved = calendar_tools.move(s, uid, "native", b, check.suggested_at, now=now)
    assert moved["entry"]["scheduled_at"].startswith("2030-01-12T16:00") and not moved["forced"]
    other = _native(db, uid, datetime(2030, 1, 20, 13, 0, tzinfo=timezone.utc))
    with db() as s:
        forced = calendar_tools.move(s, uid, "native", other, target, force=True, now=now)
    assert forced["forced"]
    with db() as s, pytest.raises(calendar_tools.CalendarToolError):
        calendar_tools.move(s, uid, "native", a, now - timedelta(hours=1), now=now)


def test_move_channel_post_ignores_other_channels_and_rejects_started_posts(db):
    uid = _user(db)
    first = _connect_telegram(uid)
    t = FakeTransport([_tg({"id": 999, "username": "menibot"}),
                       _tg({"id": -100556, "type": "channel", "title": "Second", "username": "second"}),
                       _tg({"status": "administrator"})])
    second = channels.connect_telegram(uid, BOT, "@second", transport=t)
    when = datetime.now(timezone.utc) + timedelta(days=3)
    p1 = channels.create_posts(uid, [channels.ChannelDraft(first["id"], caption="a")], scheduled_at=when)[0]
    p2 = channels.create_posts(uid, [channels.ChannelDraft(second["id"], caption="b")],
                               scheduled_at=when + timedelta(days=1))[0]
    with db() as s:
        moved = calendar_tools.move(s, uid, "post", p2["id"], when + timedelta(minutes=30))
    assert moved["entry"]["can_move"] and not moved["forced"]
    with db() as s:
        row = s.get(PlatformPost, p1["id"])
        row.attempts = 1
        s.commit()
    with db() as s, pytest.raises(calendar_tools.CalendarToolError) as exc:
        calendar_tools.move(s, uid, "post", p1["id"], when + timedelta(days=5))
    assert exc.value.status_code == 409
    stranger = _user(db, "z@example.com")
    with db() as s, pytest.raises(calendar_tools.CalendarToolError) as exc:
        calendar_tools.move(s, stranger, "post", p2["id"], when + timedelta(days=5))
    assert exc.value.status_code == 404


# --------------------------------------------------------------------------- #
# Tone preview
# --------------------------------------------------------------------------- #
def test_tones_are_deterministic_rewrites():
    assert tone.apply_tone("We do not stop. It is live.", "casual") == "We don't stop. It's live."
    assert tone.apply_tone("omg we can't wait for this AMAZING news!!! #launch", "professional") == \
        "We cannot wait for this amazing news! #launch"
    assert tone.apply_tone("Built with NASA data", "professional") == "Built with NASA data"
    assert tone.apply_tone("This is really cool. It just works. More here. #tag", "concise") == \
        "This is cool. It works. #tag"
    assert tone.apply_tone("Keep AS IS!!", "as_written") == "Keep AS IS!!"


def test_preview_fits_every_platform():
    toned, previews = tone.preview(["x", "telegram", "youtube_shorts", "mastodon"], caption="word " * 400,
                                   tone="as_written", hashtags=("a", "b"))
    by = {p.platform: p.fitted for p in previews}
    assert by["x"].length <= 280 and by["telegram"].length <= 1024 and by["mastodon"].length <= 500
    assert by["youtube_shorts"].limit == 5000
    assert all(f.text.endswith("#a #b") for f in by.values())
    with pytest.raises(ValueError):
        tone.preview(["myspace"], caption="x")


# --------------------------------------------------------------------------- #
# HTTP surface
# --------------------------------------------------------------------------- #
@pytest.fixture()
def client(db, monkeypatch):
    from fastapi import FastAPI
    from starlette.responses import JSONResponse
    from starlette.testclient import TestClient

    from app.domains.publishing import native_router
    from app.domains.publishing.extended import channels_router
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

    for module in (native_router, channels_router):
        monkeypatch.setattr(module, "get_session", _session)
    app = FastAPI()
    app.include_router(native_router.router)
    app.include_router(channels_router.router)
    app.add_exception_handler(HttpException, lambda request, exc: JSONResponse(
        status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)))
    return TestClient(app)


def test_channels_endpoint_is_token_free(client, db):
    uid = _user(db, "owner@example.com")
    _connect_telegram(uid)
    resp = client.get("/api/v1/publishing/channels", headers={"x-api-key": "owner@example.com"})
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["channels"][0]["kind"] == "telegram" and BOT not in resp.text
    assert {k["kind"] for k in body["kinds"]} == {"telegram", "discord", "mastodon"}


def test_calendar_move_conflict_returns_check_and_preview_works(client, db):
    uid = _user(db, "owner@example.com")
    base_time = (datetime.now(timezone.utc) + timedelta(days=3)).replace(hour=13, minute=0, second=0,
                                                                         microsecond=0)
    _native(db, uid, base_time)
    other = _native(db, uid, base_time + timedelta(days=2))
    headers = {"x-api-key": "owner@example.com"}
    resp = client.patch(f"/api/v1/publishing/calendar/entries/native/{other}", headers=headers,
                        json={"scheduled_at": (base_time + timedelta(hours=1)).isoformat()})
    assert resp.status_code == 409, resp.text
    assert resp.json()["data"]["check"]["suggested_at"]
    ok = client.patch(f"/api/v1/publishing/calendar/entries/native/{other}", headers=headers,
                      json={"scheduled_at": (base_time + timedelta(hours=1)).isoformat(), "force": True})
    assert ok.status_code == 200 and ok.json()["data"]["forced"]
    listing = client.get("/api/v1/publishing/calendar/entries", headers=headers,
                         params={"start": (base_time - timedelta(days=1)).isoformat(),
                                 "end": (base_time + timedelta(days=4)).isoformat()})
    assert listing.status_code == 200 and len(listing.json()["data"]["entries"]) == 2
    preview = client.post("/api/v1/publishing/calendar/preview", headers=headers,
                          json={"caption": "We do not stop", "tone": "casual", "platforms": ["discord", "tiktok"]})
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["caption"] == "We don't stop"
    assert [p["label"] for p in preview.json()["data"]["previews"]] == ["Discord", "TikTok"]
