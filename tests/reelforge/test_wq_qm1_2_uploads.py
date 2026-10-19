"""Wave Q QM1.2: safe uploads (P-M5, P-M6, P-M7, P-M8; U2, U16, U44).

1. Every uploaded title passes the transcript, text-gate and keyframe check
   before it can publish: ``block`` answers 409, ``hold`` puts it in the staff
   review queue with one email to the creator.
2. A per-user quota applies whatever the plans flag says (free 2 GB and 60
   encode minutes; paid: the plan caps); over it answers 402 with an upgrade path.
3. Moving a packaged title from free to paid queues re-encryption under a new
   key; it is unwatchable until packaged and the key server refuses the old
   key version.
4. Geo rules apply only with the trusted origin marker; otherwise geo is off,
   with a startup warning.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

import app.domains.compliance.takedown  # noqa: F401  (registers takedown_reports)

from app.domains.ott import catalog_public, service as ott_service, upload_check as uc
from app.domains.ott.models import OttChannel, OttTitle
from app.domains.ott_access import geo, keys as access_keys, service as access, tokens
from app.models.db.models import User
from app.services.ott_transcode import keys, uploads
from app.services.ott_transcode import router as transcode_router
from app.services.ott_transcode.models import OttEncodeJob

from tests.reelforge.test_wp_pm2_4_ott_transcode import H, FakeStore, _client, _uid, maker  # noqa: F401

GB = 1024 ** 3


class StubCheckers:
    def __init__(self, *, text=(uc.PASS, ""), vision=(uc.PASS, ""), frames=8, transcript="hello there"):
        self.text, self.vision_answer, self.frame_count, self.transcript = text, vision, frames, transcript
        self.vision_calls = 0

    def build(self) -> uc.Checkers:
        def vision(frames):
            self.vision_calls += 1
            return self.vision_answer

        return uc.Checkers(transcribe=lambda path: self.transcript, text_gate=lambda t, title: self.text,
                           frames=lambda path, seconds: [b"jpg"] * self.frame_count, vision=vision)


def _upload_title(maker, *, decision=None) -> str:
    uid = _uid(maker)
    with maker() as s:
        channel = s.execute(select(OttChannel).where(OttChannel.user_id == uid)).scalar_one_or_none()
        if channel is None:
            channel = OttChannel(user_id=uid, handle="up", title="Up", brand_colors=[], status="published")
            s.add(channel)
            s.flush()
        title = OttTitle(channel_id=channel.id, title="My film", kind="movie", genres=[], geo_countries=[],
                         source_key=f"ott:ott-uploads/{uid}/r/film.mp4", duration_s=120.0,
                         package_status="ready", manifest_key="ott/x/master.m3u8")
        s.add(title)
        s.flush()
        row = uc.record_upload(s, title, user_id=uid, size_bytes=GB // 2, seconds=120)
        if decision:
            row.decision = decision
        s.commit()
        return title.id


# --------------------------------------------------------------------------- #
# 1. The content check (P-M5)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("stub,paid,expect", [
    (StubCheckers(), True, uc.PASS),
    (StubCheckers(text=(uc.BLOCK, "rules")), True, uc.BLOCK),
    (StubCheckers(vision=(uc.HOLD, "look")), True, uc.HOLD),
    (StubCheckers(vision=(uc.BLOCK, "nudity")), True, uc.BLOCK),
    (StubCheckers(), False, uc.HOLD),  # free plan: no automatic image check, a person reviews it
    (StubCheckers(frames=0), False, uc.PASS),  # audio-only upload: transcript and text gate only
])
def test_evaluate_takes_the_strictest_outcome(stub, paid, expect):
    verdict = uc.evaluate("My film", "/tmp/x.mp4", 60, paid=paid, checkers=stub.build())
    assert verdict.decision == expect
    assert stub.vision_calls == (1 if paid and stub.frame_count else 0)


def test_a_failed_transcript_holds_and_never_passes():
    checkers = StubCheckers().build()
    checkers.transcribe = lambda path: (_ for _ in ()).throw(RuntimeError("no model"))
    verdict = uc.evaluate("My film", "/tmp/x.mp4", 60, paid=True, checkers=checkers)
    assert verdict.decision == uc.HOLD and "transcript failed" in verdict.reasons[0]


def test_upload_check_blocks_and_holds(maker, monkeypatch):
    uid = _uid(maker)
    sent = []
    for decision_stub, expect in ((StubCheckers(text=(uc.BLOCK, "rules")), uc.BLOCK), (StubCheckers(), uc.HOLD)):
        title_id = _upload_title(maker)
        with maker() as s:
            with pytest.raises(ott_service.OttError) as exc:
                ott_service.publish_title(s, uid, title_id)
            assert exc.value.status_code == 409 and "still running" in str(exc.value)
            row = uc.run_check(s, title_id, fetch=lambda key, work: f"{work}/f.mp4", paid=False,
                               checkers=decision_stub.build(), notify=lambda r: sent.append(r.title_id) or True)
            s.commit()
            assert row.decision == expect
            with pytest.raises(ott_service.OttError) as exc:
                ott_service.publish_title(s, uid, title_id)
            assert exc.value.status_code == 409
    held = title_id
    assert sent == [held]  # one email, for the held upload only
    with maker() as s:
        s.get(User, uid).is_staff = True
        s.commit()
    client = _client(monkeypatch)
    queue = client.get("/api/v1/admin/ott/upload-checks", headers=H).json()["data"]["items"]
    assert [i["title_id"] for i in queue] == [held]
    assert client.post(f"/api/v1/admin/ott/upload-checks/{held}/review", headers=H,
                       json={"approve": True}).json()["data"]["decision"] == uc.PASS
    with maker() as s:
        assert ott_service.publish_title(s, uid, held).status == "published"
        s.commit()


def test_review_routes_are_staff_only(maker, monkeypatch):
    client = _client(monkeypatch)
    assert client.get("/api/v1/admin/ott/upload-checks", headers=H).status_code == 403


def test_upload_complete_records_a_pending_check_and_queues_it(maker, monkeypatch):
    queued = []
    client = _client(monkeypatch)
    monkeypatch.setattr(transcode_router, "enqueue_upload_check", lambda title_id: queued.append(title_id))
    started = client.post("/api/v1/ott/uploads", headers=H, json={
        "filename": "a.mp4", "size_bytes": 2 * uploads.PART_BYTES, "content_type": "video/mp4"}).json()["data"]
    done = client.post("/api/v1/ott/uploads/complete", headers=H, json={
        "key": started["key"], "upload_id": started["upload_id"], "title": "Clip", "seconds": 90,
        "short_side": 720, "size_bytes": 2 * uploads.PART_BYTES,
        "parts": [{"PartNumber": 1, "ETag": "a"}, {"PartNumber": 2, "ETag": "b"}]}).json()["data"]
    assert done["check"]["decision"] == uc.PENDING and queued == [done["title_id"]]
    with maker() as s:
        assert s.get(uc.OttUploadCheck, done["title_id"]).size_bytes == 2 * uploads.PART_BYTES


def test_relay_vision_maps_the_policy_answer():
    def chat(answer):
        return lambda body, relay_provider: {"choices": [{"message": {"content": answer}}]}

    frames = [b"\xff\xd8jpg"] * 3
    assert uc.relay_vision(frames, chat=chat('{"decision": "deny", "categories": ["sexual"]}'))[0] == uc.BLOCK
    assert uc.relay_vision(frames, chat=chat('{"decision": "flag", "categories": []}'))[0] == uc.HOLD
    assert uc.relay_vision(frames, chat=chat('{"decision": "allow", "categories": []}'))[0] == uc.PASS
    assert uc.relay_vision(frames, chat=chat("not json"))[0] == uc.HOLD
    assert uc.relay_vision(frames, chat=lambda body, relay_provider: None)[0] == uc.HOLD

    seen = {}

    def spy(body, relay_provider):
        seen.update(body=body, provider=relay_provider)
        return {"choices": [{"message": {"content": '{"decision": "allow"}'}}]}

    uc.relay_vision(frames, chat=spy)
    parts = seen["body"]["messages"][1]["content"]
    assert seen["provider"] == "anthropic" and sum(p["type"] == "image_url" for p in parts) == 3


def test_no_agpl_nudity_detector_is_used():
    from pathlib import Path

    import re

    root = Path(uc.__file__).resolve().parents[3]
    imports = re.compile(r"^\s*(?:import|from)\s+nudenet\b", re.MULTILINE | re.IGNORECASE)
    for path in root.glob("app/**/*.py"):
        assert not imports.search(path.read_text(encoding="utf-8", errors="ignore")), path
    for path in [*root.glob("requirements*.txt"), root.parents[1] / "pyproject.toml"]:
        if path.is_file():
            assert "nudenet" not in path.read_text(encoding="utf-8").lower(), path


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_fixture_mp4_goes_through_upload_check_and_frames(maker, tmp_path):
    clip = tmp_path / "fixture.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=3",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-y", str(clip)], check=True, timeout=60)
    frames = uc.extract_frames(str(clip), 3600.0)  # a false declared length is ignored: the file is probed
    assert len(frames) == uc.FRAMES and all(f[:2] == b"\xff\xd8" for f in frames)
    audio = tmp_path / "voice.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=2", "-c:a", "aac",
                    "-y", str(audio)], check=True, timeout=60)
    assert uc.extract_frames(str(audio), 2.0) == []
    title_id = _upload_title(maker)
    seen = []

    def vision(images):
        seen.append(len(images))
        return uc.PASS, ""

    checkers = uc.Checkers(transcribe=lambda path: "a calm product demo", text_gate=lambda t, title: (uc.PASS, ""),
                           frames=uc.extract_frames, vision=vision)
    with maker() as s:
        row = uc.run_check(s, title_id, fetch=lambda key, work: shutil.copy(clip, work) and f"{work}/fixture.mp4",
                           paid=True, checkers=checkers, notify=lambda r: True)
        s.commit()
        assert row.decision == uc.PASS and row.frames_checked == uc.FRAMES and seen == [uc.FRAMES]
        assert ott_service.gate(s, s.get(OttTitle, title_id)) is None


# --------------------------------------------------------------------------- #
# 2. The per-user quota (P-M6)
# --------------------------------------------------------------------------- #
def test_quota_applies_without_the_plans_flag(maker, monkeypatch):
    monkeypatch.delenv("OTT_PLANS_LIVE", raising=False)
    client = _client(monkeypatch)
    big = client.post("/api/v1/ott/uploads", headers=H, json={
        "filename": "big.mp4", "size_bytes": 3 * GB, "content_type": "video/mp4"})
    assert big.status_code == 402
    assert big.json()["data"] == {"code": "upload_quota", "upgrade_url": "/pricing"}
    long = client.post("/api/v1/ott/uploads", headers=H, json={
        "filename": "long.mp4", "size_bytes": GB // 10, "content_type": "video/mp4", "seconds": 61 * 60})
    assert long.status_code == 402 and "60 encoding minutes" in long.json()["message"]
    _upload_title(maker)  # 0.5 GB already stored
    assert client.post("/api/v1/ott/uploads", headers=H, json={
        "filename": "ok.mp4", "size_bytes": GB, "content_type": "video/mp4"}).status_code == 200
    assert client.post("/api/v1/ott/uploads", headers=H, json={
        "filename": "over.mp4", "size_bytes": 2 * GB, "content_type": "video/mp4"}).status_code == 402
    monkeypatch.setattr(transcode_router.service, "paid_plan", lambda user_id: True)
    assert client.post("/api/v1/ott/uploads", headers=H, json={
        "filename": "paid.mp4", "size_bytes": 3 * GB, "content_type": "video/mp4"}).status_code == 200


def test_complete_over_the_quota_aborts_and_keeps_nothing(maker, monkeypatch):
    class Store(FakeStore):
        def __init__(self):
            super().__init__()
            self.aborted = []

        def abort(self, key, upload_id):
            self.aborted.append(key)

    store = Store()
    client = _client(monkeypatch, store)
    started = client.post("/api/v1/ott/uploads", headers=H, json={
        "filename": "a.mp4", "size_bytes": 10, "content_type": "video/mp4"}).json()["data"]
    res = client.post("/api/v1/ott/uploads/complete", headers=H, json={
        "key": started["key"], "upload_id": started["upload_id"], "title": "Clip", "seconds": 2 * 3600,
        "short_side": 720, "parts": [{"PartNumber": 1, "ETag": "a"}]})
    assert res.status_code == 402 and store.aborted == [started["key"]] and store.completed == []


def test_quota_numbers():
    assert uploads.FREE_QUOTA_GB == 2.0 and uploads.FREE_QUOTA_ENCODE_MIN == 60.0


# --------------------------------------------------------------------------- #
# 3. Free to paid (P-M7)
# --------------------------------------------------------------------------- #
def test_free_to_paid_queues_reencryption_and_refuses_stale_keys(maker, monkeypatch):
    monkeypatch.setenv(tokens.SECRET_ENV, "t" * 40)
    uid = _uid(maker)
    title_id = _upload_title(maker, decision=uc.PASS)
    with maker() as s:
        title = s.get(OttTitle, title_id)
        title.status, title.published_at = "published", datetime.now(timezone.utc)
        keys.ensure_key(s, title_id)
        s.commit()
        old_version = keys.version(s, title_id)
        assert catalog_public.watchable(s, title)
    with maker() as s:
        ott_service.update_title(s, uid, title_id, {"access_tier": "paid"})
        s.commit()
    with maker() as s:
        title = s.get(OttTitle, title_id)
        assert title.package_status == "queued" and not catalog_public.watchable(s, title)
        jobs = s.execute(select(OttEncodeJob).where(OttEncodeJob.title_id == title_id)).scalars().all()
        assert len(jobs) == 1 and jobs[0].source_key == title.source_key
        new_version = keys.version(s, title_id)
        assert new_version == old_version + 1
        protection = transcode_router.service.protection_for(s, title, "https://api.example")
        assert protection.key_uri.endswith(f"/api/v1/ott/keys/{title_id}?kv={new_version}")
        token, _grant = tokens.issue(title_id, "device:x", "TR")
        assert access_keys.release(s, title_id, token, str(new_version)) == keys.read_key(s, title_id)
        for stale in (str(old_version), "", "junk"):
            with pytest.raises(access_keys.KeyRefused):
                access_keys.release(s, title_id, token, stale)


def test_playlist_rewrite_keeps_the_key_version():
    text = '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="https://api.example/api/v1/ott/keys/t1?kv=3",IV=0x00\n'
    out = access.rewrite_playlist(text, title_id="t1", token="tok", base="https://api.example")
    assert 'URI="https://api.example/api/v1/ott/keys/t1?t=tok&kv=3"' in out
    legacy = text.replace("?kv=3", "")
    assert 'URI="https://api.example/api/v1/ott/keys/t1?t=tok"' in access.rewrite_playlist(
        legacy, title_id="t1", token="tok", base="https://api.example")


def test_paid_to_free_or_unpackaged_titles_are_not_requeued(maker):
    uid = _uid(maker)
    title_id = _upload_title(maker, decision=uc.PASS)
    with maker() as s:
        title = s.get(OttTitle, title_id)
        title.package_status, title.manifest_key = "none", ""
        s.commit()
        ott_service.update_title(s, uid, title_id, {"access_tier": "paid"})
        s.commit()
        assert s.execute(select(OttEncodeJob)).scalars().all() == []


# --------------------------------------------------------------------------- #
# 4. Geo needs the trusted origin marker (P-M8)
# --------------------------------------------------------------------------- #
def test_geo_needs_the_trusted_origin_marker():
    secret = "s" * 32
    env = {geo.EDGE_SECRET_ENV: secret}
    assert geo.country({"CF-IPCountry": "DE"}, env) == geo.UNKNOWN  # no marker: the header is not believed
    assert geo.country({"CF-IPCountry": "DE", geo.EDGE_HEADER: "wrong"}, env) == geo.UNKNOWN
    assert geo.country({"CF-IPCountry": "DE", geo.EDGE_HEADER: secret}, env) == "DE"
    assert not geo.allowed("allow", ["TR"], geo.UNKNOWN, env)
    off = {}
    assert not geo.enabled(off) and geo.allowed("allow", ["TR"], "DE", off)  # geo is off without the secret
    assert not geo.enabled({geo.EDGE_SECRET_ENV: "short"})
    warnings = []
    assert geo.startup_check(warnings.append, off) is False and warnings == [geo.STARTUP_WARNING]
    assert geo.startup_check(warnings.append, env) is True and len(warnings) == 1


def test_api_startup_calls_the_geo_check():
    from pathlib import Path

    source = (Path(geo.__file__).resolve().parents[2] / "asgi.py").read_text(encoding="utf-8")
    assert "ott_geo.startup_check(logger.warning)" in source


# --------------------------------------------------------------------------- #
# QM verify: the quota counts stored bytes; a superseded job never repoints a title
# --------------------------------------------------------------------------- #
def test_complete_measures_the_stored_object_not_the_claimed_size(maker, monkeypatch):
    class Store(FakeStore):
        def __init__(self):
            super().__init__()
            self.deleted = []

        def size(self, key):
            return 3 * GB  # the client said 10 bytes

        def delete(self, key):
            self.deleted.append(key)

    store = Store()
    client = _client(monkeypatch, store)
    started = client.post("/api/v1/ott/uploads", headers=H, json={
        "filename": "a.mp4", "size_bytes": 10, "content_type": "video/mp4"}).json()["data"]
    res = client.post("/api/v1/ott/uploads/complete", headers=H, json={
        "key": started["key"], "upload_id": started["upload_id"], "title": "Clip", "seconds": 60,
        "short_side": 720, "size_bytes": 10, "parts": [{"PartNumber": 1, "ETag": "a"}]})
    assert res.status_code == 402
    assert store.deleted == [started["key"]]
    with maker() as s:
        assert s.execute(select(OttTitle)).scalars().all() == []
        assert s.execute(select(uc.OttUploadCheck)).scalars().all() == []


def test_complete_records_the_measured_size(maker, monkeypatch):
    class Store(FakeStore):
        def size(self, key):
            return 12345

    client = _client(monkeypatch, Store())
    started = client.post("/api/v1/ott/uploads", headers=H, json={
        "filename": "a.mp4", "size_bytes": 10, "content_type": "video/mp4"}).json()["data"]
    res = client.post("/api/v1/ott/uploads/complete", headers=H, json={
        "key": started["key"], "upload_id": started["upload_id"], "title": "Clip", "seconds": 60,
        "short_side": 720, "size_bytes": 10, "parts": [{"PartNumber": 1, "ETag": "a"}]})
    assert res.status_code == 200, res.text
    with maker() as s:
        (row,) = s.execute(select(uc.OttUploadCheck)).scalars().all()
        assert row.size_bytes == 12345


def test_quota_lock_is_a_postgres_advisory_lock(maker):
    executed = []

    class _Dialect:
        name = "postgresql"

    class _Bind:
        dialect = _Dialect()

    class _Session:
        def get_bind(self):
            return _Bind()

        def execute(self, stmt, params=None):
            executed.append((str(stmt), params))

    uploads.lock_quota(_Session(), "u1")
    assert "pg_advisory_xact_lock" in executed[0][0] and executed[0][1] == {"k": "ott-upload-quota:u1"}
    with maker() as s:  # SQLite: no-op
        uploads.lock_quota(s, "u1")


def test_a_superseded_job_does_not_repoint_the_title(maker):
    from datetime import timedelta

    from app.services.ott_transcode import service as transcode_service

    uid = _uid(maker)
    title_id = _upload_title(maker, decision=uc.PASS)
    with maker() as s:
        title = s.get(OttTitle, title_id)
        old = transcode_service.submit(s, title, source_key=title.source_key, seconds=60, short_side=720,
                                       user_id=uid)
        newer = transcode_service.submit(s, title, source_key=title.source_key, seconds=60, short_side=720,
                                         user_id=uid)
        base = datetime.now(timezone.utc)
        old.created_at, newer.created_at = base - timedelta(minutes=5), base
        title.package_status, title.manifest_key = "queued", ""
        s.flush()
        transcode_service.finish(s, old, cpu_seconds=1.0, packager_sha256="x")
        assert title.package_status == "queued" and title.manifest_key == ""
        transcode_service.finish(s, newer, cpu_seconds=1.0, packager_sha256="x")
        assert title.package_status == "ready" and title.manifest_key == newer.manifest_key
