"""Wave P PM3.4: MV10 live, MV11 live chat, MV15 FAST channels.

1. OBS-to-viewer latency is recorded (not promised); the recording becomes a
   VOD title within 10 min (target); the viewer cap (2 streams, 50 viewers
   each) is enforced; copy is gated on OTT_LIVE_LIVE.
2. Chat on Scribase Realtime with the moderation budget, slow mode and
   takedown within 60 s.
3. A 24 h schedule of 10 titles plays continuously (soak); the XMLTV guide
   validates; ad breaks come from MV14.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from sqlalchemy import select

import app.domains.ott_live.models  # noqa: F401
from app.domains.ott.models import OttTitle
from app.domains.ott_access import limits, tokens
from app.domains.ott_commerce.models import OttAd
from app.domains.ott_linear import router as linear_router, schedule, service as linear
from app.domains.ott_live import chat, router as live_router, service as live
from app.domains.ott_live.models import OttChatMessage, OttLiveStream
from app.domains.ott_viewers import auth, router as viewers_router, session as viewer_session
from app.services.ott_transcode.models import OttEncodeJob

from tests.reelforge import _wp_p3_ott as h

REPO = Path(__file__).resolve().parents[2]
HOOK = "hook-secret-0123456789abcdefghij"
ENGINE = "engine-key-0123456789abcdefghijk"


class Broadcasts:
    def __init__(self):
        self.sent = []

    def __call__(self, url, body, headers):
        assert headers["apikey"] == "service-key" and url == "https://sb.example/realtime/v1/api/broadcast"
        self.sent.extend(body["messages"])
        return 202


@pytest.fixture()
def env(monkeypatch):
    factory = h.make_factory()
    h.patch_sessions(monkeypatch, factory, (live_router, linear_router, viewers_router))
    h.enable(monkeypatch, "live", "chat", "fast", "viewers", "ads")
    monkeypatch.setenv(live.HOOK_SECRET_ENV, HOOK)
    monkeypatch.setenv(linear.ENGINE_KEY_ENV, ENGINE)
    monkeypatch.setenv(tokens.SECRET_ENV, "x" * 40)
    monkeypatch.setenv(auth.SECRET_ENV, h.AUTH_SECRET)
    monkeypatch.setenv(viewer_session.SECRET_ENV, h.VIEWER_SECRET)
    monkeypatch.setenv("SCRIBASE_REALTIME_URL", "https://sb.example/realtime/v1")
    monkeypatch.setenv("SCRIBASE_SERVICE_KEY", "service-key")
    monkeypatch.setenv("MENIVOR_PUBLIC_API_BASE", "https://api.example")
    monkeypatch.setattr(limits, "_STORE", limits.MemoryStore())
    monkeypatch.setattr(viewers_router, "enforce_rate_limit", lambda *a, **k: None)
    sent = Broadcasts()
    monkeypatch.setattr(chat, "_post", sent)
    owner = h.owner(factory)
    cid, ids = h.channel(factory, owner, "maya", titles=10, duration_s=1800.0)
    client = h.app_client(live_router.router, linear_router.router, viewers_router.router)
    return {"factory": factory, "client": client, "owner": owner, "cid": cid, "ids": ids, "broadcasts": sent}


OWNER = {"x-api-key": h.OWNER_KEY}


def _stream(env, title="Launch night", tier="free"):
    res = env["client"].post("/api/v1/ott/studio/live", json={"title": title, "access_tier": tier}, headers=OWNER)
    assert res.status_code == 200, res.text
    return res.json()["data"]


def _auth(env, action, path, query="", secret=HOOK):
    return env["client"].post(f"/api/v1/ott/live/hooks/auth?secret={secret}",
                              json={"action": action, "path": path, "query": query, "protocol": "rtmp"})


def _go_live(env, data):
    path = f"live/{data['ingest']['stream_key'].split('?')[0]}"
    key = data["ingest"]["stream_key"].split("key=")[1]
    assert _auth(env, "publish", path, f"key={key}").status_code == 200
    assert env["client"].post(f"/api/v1/ott/live/hooks/ready?secret={HOOK}&path={path}").status_code == 200
    return path, key


# --------------------------------------------------------------------------- #
# MV10
# --------------------------------------------------------------------------- #
def test_stream_key_is_shown_once_and_only_its_hash_is_kept(env):
    data = _stream(env)
    key = data["ingest"]["stream_key"].split("key=")[1]
    assert data["ingest"]["server"].endswith("/live") and key.startswith("sk_")
    with env["factory"]() as s:
        row = s.get(OttLiveStream, data["id"])
        assert key not in (row.key_hash, row.path) and len(row.key_hash) == 64
    listed = env["client"].get("/api/v1/ott/studio/live", headers=OWNER).json()["data"]
    assert key not in str(listed) and listed["max_streams"] == 2 and listed["max_viewers"] == 50
    rotated = env["client"].post(f"/api/v1/ott/studio/live/{data['id']}/key", headers=OWNER).json()["data"]
    new_key = rotated["ingest"]["stream_key"].split("key=")[1]
    path = f"live/{data['ingest']['stream_key'].split('?')[0]}"
    assert _auth(env, "publish", path, f"key={key}").status_code == 401
    assert _auth(env, "publish", path, f"key={new_key}").status_code == 200


def test_only_two_streams_go_live_at_once(env):
    first, second, third = _stream(env, "One"), _stream(env, "Two"), _stream(env, "Three")
    _go_live(env, first)
    _go_live(env, second)
    path = f"live/{third['ingest']['stream_key'].split('?')[0]}"
    key = third["ingest"]["stream_key"].split("key=")[1]
    assert _auth(env, "publish", path, f"key={key}").status_code == 429
    env["client"].post(f"/api/v1/ott/live/hooks/ended?secret={HOOK}&path=live/{first['ingest']['stream_key'].split('?')[0]}")
    assert _auth(env, "publish", path, f"key={key}").status_code == 200


def test_viewers_need_a_token_and_the_fifty_first_is_refused(env):
    data = _stream(env)
    path, _key = _go_live(env, data)
    watch = env["client"].post(f"/api/v1/ott/live/{data['id']}/watch")
    assert watch.status_code == 200 and watch.headers["cache-control"].startswith("no-store")
    url = watch.json()["data"]["hls_url"]
    assert url.startswith("https://live.menivor.com/live/") and "?t=" in url
    token = url.split("?t=")[1]
    assert _auth(env, "read", path, f"t={token}").status_code == 200
    assert _auth(env, "read", path, "t=forged").status_code == 401
    for n in range(49):
        other, _ = tokens.issue(f"live:{data['id']}", f"device:{n}", "XX")
        assert _auth(env, "read", path, f"t={other}").status_code == 200
    extra, _ = tokens.issue(f"live:{data['id']}", "device:late", "XX")
    assert _auth(env, "read", path, f"t={extra}").status_code == 429
    assert _auth(env, "read", path, f"t={token}").status_code == 200  # a viewer already in keeps watching
    assert _auth(env, "publish", path, "key=x", secret="wrong").status_code == 401


def test_paid_streams_need_membership(env):
    data = _stream(env, tier="paid")
    _go_live(env, data)
    assert env["client"].post(f"/api/v1/ott/live/{data['id']}/watch").status_code == 402
    assert env["client"].post(f"/api/v1/ott/live/{data['id']}/watch", headers=OWNER).status_code == 200


def test_the_recording_becomes_a_vod_title_right_after_the_stream(env, monkeypatch):
    from app.services.ott_transcode import router as transcode_router

    monkeypatch.setattr(transcode_router, "storage", lambda: type("S", (), {
        "presign_put": staticmethod(lambda key, ct, ttl: f"https://r2.example/{key}?put")})())
    monkeypatch.setattr(transcode_router, "enqueue_box1", lambda job_id: None)
    checks = []
    monkeypatch.setattr(transcode_router, "enqueue_upload_check", checks.append)  # Wave Q QM1.2
    data = _stream(env)
    path, _ = _go_live(env, data)
    ended_at = time.monotonic()
    env["client"].post(f"/api/v1/ott/live/hooks/ended?secret={HOOK}&path={path}")
    target = env["client"].post(f"/api/v1/ott/live/hooks/recording-url?secret={HOOK}&path={path}").json()["data"]
    assert target["key"].startswith(f"ott-uploads/{env['owner']}/live-{data['id']}/") and target["url"].endswith("?put")
    done = env["client"].post(f"/api/v1/ott/live/hooks/recording-done?secret={HOOK}", json={
        "path": path, "key": target["key"], "seconds": 3600, "short_side": 720}).json()["data"]
    elapsed = time.monotonic() - ended_at
    assert done["title_id"] and elapsed < 600
    again = env["client"].post(f"/api/v1/ott/live/hooks/recording-done?secret={HOOK}", json={
        "path": path, "key": target["key"], "seconds": 3600, "short_side": 720}).json()["data"]
    assert again["duplicate"] is True
    with env["factory"]() as s:
        title = s.get(OttTitle, done["title_id"])
        assert title.status == "draft" and title.package_status == "queued" and title.title == "Launch night"
        assert s.execute(select(OttEncodeJob).where(OttEncodeJob.title_id == title.id)).scalar_one().lane == "mac"
    assert checks == [done["title_id"]]  # the recording passes the upload content check before it can publish
    foreign = env["client"].post(f"/api/v1/ott/live/hooks/recording-done?secret={HOOK}", json={
        "path": path, "key": "ott-uploads/someone/else.mp4", "seconds": 10, "short_side": 720})
    assert foreign.status_code == 400
    view = env["client"].get("/api/v1/ott/studio/live", headers=OWNER).json()["data"]["streams"][0]
    assert view["status"] == "ended" and view["vod_title_ids"] == [done["title_id"]]


def test_latency_is_recorded_from_players(env):
    data = _stream(env)
    _go_live(env, data)
    for sample in (4.2, 5.0, 6.1):
        assert env["client"].post(f"/api/v1/ott/live/{data['id']}/latency", json={"seconds": sample}).status_code == 204
    view = env["client"].get("/api/v1/ott/studio/live", headers=OWNER).json()["data"]["streams"][0]
    assert view["latency_s"] == {"median": 5.0, "samples": 3}


def test_live_routes_404_until_the_flag_and_stale_streams_close(env, monkeypatch):
    data = _stream(env)
    _go_live(env, data)
    with env["factory"]() as s:
        s.get(OttLiveStream, data["id"]).started_at = datetime.now(timezone.utc) - timedelta(hours=13)
        s.commit()
        assert live.sweep_stale(s) == 1
    monkeypatch.delenv("OTT_LIVE_LIVE")
    assert env["client"].get("/api/v1/ott/c/maya/live").status_code == 404


# --------------------------------------------------------------------------- #
# MV11
# --------------------------------------------------------------------------- #
def _viewer(env, sub="sub-a", email="a@example.com"):
    return env["client"].post("/api/v1/ott/viewers/maya/session",
                              json={"access_token": h.auth_token(sub, email)}).json()["data"]


def test_chat_posts_broadcast_on_realtime_and_blocks_links(env):
    data = _stream(env)
    _go_live(env, data)
    viewer = _viewer(env)
    head = {"x-ott-viewer": viewer["session"]}
    assert env["client"].post(f"/api/v1/ott/live/{data['id']}/chat", json={"body": "hi"}).status_code == 401
    sent = env["client"].post(f"/api/v1/ott/live/{data['id']}/chat", json={"body": "  great   show "}, headers=head)
    assert sent.status_code == 200 and sent.json()["data"]["body"] == "great show"
    assert env["broadcasts"].sent[-1]["topic"] == f"ott-live:{data['id']}"
    assert env["broadcasts"].sent[-1]["event"] == "chat"
    link = env["client"].post(f"/api/v1/ott/live/{data['id']}/chat", json={"body": "see www.spam.example"},
                              headers=head)
    assert link.status_code == 400 and "Links" in link.json()["message"]
    read = env["client"].get(f"/api/v1/ott/live/{data['id']}/chat").json()["data"]
    assert [m["body"] for m in read["messages"]] == ["great show"]


def test_blocked_words_slow_mode_and_the_budget(env, monkeypatch):
    monkeypatch.setenv("OTT_CHAT_BLOCKED_WORDS", "badword")
    data = _stream(env)
    _go_live(env, data)
    viewer = _viewer(env)
    with env["factory"]() as s:
        stream = s.get(OttLiveStream, data["id"])
        from app.domains.ott_viewers.models import OttViewer

        account = s.get(OttViewer, viewer["viewer"]["id"])
        with pytest.raises(chat.ChatError, match="not allowed"):
            chat.post(s, stream, account, "a BadWord here")
        start = datetime.now(timezone.utc)
        for n in range(chat.VIEWER_BUDGET):
            chat.post(s, stream, account, f"message {n}", at=start + timedelta(seconds=n))
        with pytest.raises(chat.ChatError) as budget:
            chat.post(s, stream, account, "one more", at=start + timedelta(seconds=30))
        assert budget.value.code == "viewer_budget"
        assert chat.post(s, stream, account, "later", at=start + timedelta(minutes=6))["body"] == "later"
        chat.set_rules(s, stream, {"slow_mode_s": 30})
        with pytest.raises(chat.ChatError) as slow:
            chat.post(s, stream, account, "too soon", at=start + timedelta(minutes=6, seconds=10))
        assert slow.value.code == "slow_mode" and "20 s" in str(slow.value)


def test_takedown_hides_at_once_and_bans_keep_a_viewer_out(env):
    data = _stream(env)
    _go_live(env, data)
    viewer = _viewer(env)
    head = {"x-ott-viewer": viewer["session"]}
    message = env["client"].post(f"/api/v1/ott/live/{data['id']}/chat", json={"body": "hello"}, headers=head)
    mid = message.json()["data"]["id"]
    started = time.monotonic()
    hidden = env["client"].post(f"/api/v1/ott/studio/live/{data['id']}/chat/{mid}/hide", headers=OWNER)
    assert hidden.json()["data"] == {"id": mid, "hidden": True}
    assert env["client"].get(f"/api/v1/ott/live/{data['id']}/chat").json()["data"]["messages"] == []
    assert time.monotonic() - started < 60
    assert env["broadcasts"].sent[-1]["event"] == "hide" and env["broadcasts"].sent[-1]["payload"] == {"id": mid}
    env["client"].post(f"/api/v1/ott/live/{data['id']}/chat", json={"body": "again"}, headers=head)
    studio = env["client"].get(f"/api/v1/ott/studio/live/{data['id']}/chat", headers=OWNER).json()["data"]
    assert {m["viewer_id"] for m in studio["messages"]} == {viewer["viewer"]["id"]}
    env["client"].post(f"/api/v1/ott/studio/live/{data['id']}/chat/ban", json={"viewer_id": viewer["viewer"]["id"]},
                       headers=OWNER)
    banned = env["client"].post(f"/api/v1/ott/live/{data['id']}/chat", json={"body": "back"}, headers=head)
    assert banned.status_code == 403
    with env["factory"]() as s:
        assert all(m.hidden_at is not None for m in s.execute(select(OttChatMessage)).scalars())


def test_realtime_outage_never_blocks_a_message(env, monkeypatch):
    def down(url, body, headers):
        raise ConnectionError("realtime down")

    monkeypatch.setattr(chat, "_post", down)
    data = _stream(env)
    _go_live(env, data)
    viewer = _viewer(env)
    res = env["client"].post(f"/api/v1/ott/live/{data['id']}/chat", json={"body": "still here"},
                             headers={"x-ott-viewer": viewer["session"]})
    assert res.status_code == 200


# --------------------------------------------------------------------------- #
# MV15
# --------------------------------------------------------------------------- #
def _linear(env, ad_every=0):
    res = env["client"].post("/api/v1/ott/studio/linear", headers=OWNER,
                             json={"slug": "maya-tv", "name": "Maya TV", "title_ids": env["ids"],
                                   "ad_break_every": ad_every})
    assert res.status_code == 200, res.text
    return res.json()["data"]


def test_a_24_hour_schedule_of_ten_titles_plays_continuously():
    anchor = datetime(2026, 10, 5, tzinfo=timezone.utc)
    programs = [schedule.Item(kind=schedule.PROGRAM, duration_s=900 + 137 * n, title_id=f"t{n}", name=f"Show {n}")
                for n in range(10)]
    cycle = schedule.build_cycle(programs, ad_every=3)
    start = anchor + timedelta(hours=5, minutes=17, seconds=3)
    guide = schedule.slots(cycle, anchor, start, hours=24)
    assert guide[0].start <= start < guide[0].stop
    assert guide[-1].stop >= start + timedelta(hours=24)
    for previous, current in zip(guide, guide[1:]):
        assert previous.stop == current.start and current.index == previous.index + 1
    seen_programs = [s.item.title_id for s in guide if s.item.kind == schedule.PROGRAM]
    assert set(seen_programs) == {f"t{n}" for n in range(10)}
    for n, slot in enumerate(guide[:-1]):
        if slot.item.kind == schedule.AD:
            assert guide[n - 1].item.kind == schedule.PROGRAM
    moment = start
    while moment < start + timedelta(hours=24):  # every minute of the day maps to exactly one item
        index, item, offset = schedule.at(cycle, anchor, moment)
        assert 0 <= offset < item.duration_s
        moment += timedelta(minutes=1)


def test_epg_validates_as_xmltv(env):
    _linear(env)
    res = env["client"].get("/api/v1/ott/linear/maya-tv/epg.xml")
    assert res.status_code == 200 and res.headers["content-type"].startswith("application/xml")
    tv = ET.fromstring(res.content)
    assert tv.tag == "tv" and tv.find("channel").get("id") == "maya-tv.menivor"
    assert tv.find("channel/display-name").text == "Maya TV"
    programmes = tv.findall("programme")
    assert len(programmes) >= 48  # 24 h of 30-minute titles
    stamp = "%Y%m%d%H%M%S %z"
    for previous, current in zip(programmes, programmes[1:]):
        assert datetime.strptime(previous.get("stop"), stamp) == datetime.strptime(current.get("start"), stamp)
        assert current.get("channel") == "maya-tv.menivor" and current.find("title").text


def test_engine_items_step_through_programs_and_fill_ad_breaks(env, monkeypatch):
    _linear(env, ad_every=2)
    now = env["client"].get("/api/v1/ott/linear/maya-tv/now").json()["data"]
    assert now["now"]["kind"] == "program" and now["watch_url"].endswith("/channels/maya-tv/master.m3u8")
    head = {"x-engine-key": ENGINE}
    assert env["client"].get("/api/v1/ott/linear/maya-tv/items/0").status_code == 401
    first = env["client"].get("/api/v1/ott/linear/maya-tv/items/0", headers=head).json()["data"]
    assert first["kind"] == "program" and first["uri"].startswith("https://api.example/api/v1/ott/stream/")
    grant = tokens.verify(first["uri"].split("/ott/stream/")[1].split("/")[0])
    assert grant.exp - time.time() > 1800  # the engine link outlives the title
    empty_break = env["client"].get("/api/v1/ott/linear/maya-tv/items/2", headers=head).json()["data"]
    assert empty_break["kind"] == "program" and empty_break["index"] == 3  # no ad: the break is skipped
    with env["factory"]() as s:
        spot = s.get(OttTitle, env["ids"][9])
        s.add(OttAd(channel_id=env["cid"], kind="sponsor", name="Coffee week", title_id=spot.id, duration_s=30))
        s.commit()
    ad_break = env["client"].get("/api/v1/ott/linear/maya-tv/items/2", headers=head).json()["data"]
    assert ad_break["kind"] == "ad" and ad_break["title"] == "Coffee week" and ad_break["index"] == 2


def test_only_free_published_titles_can_be_scheduled(env):
    with env["factory"]() as s:
        s.get(OttTitle, env["ids"][0]).access_tier = "paid"
        s.commit()
    res = env["client"].post("/api/v1/ott/studio/linear", headers=OWNER, json={"title_ids": env["ids"]})
    assert res.status_code == 400


def test_playout_asset_manager_steps_from_now(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = tmp_path / "check.js"
    script.write_text(f"""
const {{ MenivorSchedule }} = require({str(REPO / 'deploy/menivor-fast/schedule.js')!r});
const calls = [];
const fetchImpl = async (url, init) => {{
  calls.push([url, init && init.headers && init.headers['x-engine-key']]);
  if (url.endsWith('/now')) return {{ ok: true, json: async () => ({{ data: {{ index: 7 }} }}) }};
  const n = Number(url.split('/').pop());
  return {{ ok: true, json: async () => ({{ data: {{ index: n === 8 ? 9 : n, id: 't' + n, title: 'T', uri: 'https://u/' + n }} }}) }};
}};
(async () => {{
  const s = new MenivorSchedule({{ api: 'https://api.example/api/v1/', engineKey: 'k', fetchImpl }});
  const a = await s.next('ch:1', 'maya-tv');
  const b = await s.next('ch:1', 'maya-tv');
  const c = await s.next('ch:1', 'maya-tv');
  if (a.uri !== 'https://u/7' || b.uri !== 'https://u/8' || c.uri !== 'https://u/10') throw new Error(JSON.stringify([a, b, c]));
  if (calls[1][1] !== 'k') throw new Error('engine key missing');
  console.log('ok');
}})().catch((e) => {{ console.error(e); process.exit(1); }});
""")
    out = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and out.stdout.strip() == "ok", out.stderr
