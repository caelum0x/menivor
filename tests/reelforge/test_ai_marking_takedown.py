"""MN5: AI-content marking and takedown.

* Every final MP4 carries the provenance tag, written by a metadata-only remux
  (the audio/video packets are unchanged: no re-encode). ffprobe checks it.
* The pipeline's compose callback tags before the job completes.
* Native publishes set each platform's AI flag (TikTok ``is_aigc``, YouTube
  ``containsSyntheticMedia``; Upload-Post fields for all three).
* A report creates a ticket, alerts ntfy, and can soft-block the video's media
  (staff action, or automatically after 24 h). Blocked media is not served.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.domains.compliance import takedown
from app.models.db.base import Base
from app.models.db.models import Job, ShareLink, User
from app.models.exception import HttpException
from app.services import provenance
from app.utils import utils

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed",
)


# --------------------------------------------------------------------------- #
# Provenance tag
# --------------------------------------------------------------------------- #
def _make_mp4(path: str) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=440", "-t", "1", "-c:v", "libx264",
         "-c:a", "aac", "-shortest", path],
        check=True,
    )


def _stream_md5(path: str) -> str:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-map", "0", "-c", "copy", "-f", "md5", "-"],
        capture_output=True, check=True,
    )
    return out.stdout.decode().strip()


@needs_ffmpeg
def test_final_mp4_carries_provenance_tag_without_reencode(tmp_path):
    video = str(tmp_path / "final.mp4")
    _make_mp4(video)
    before = _stream_md5(video)

    provenance.tag(video, "job123")
    provenance.tag(video, "job123")  # idempotent: re-tagging on retry is safe

    tags = provenance.read_tags(video)
    assert tags["ai_generated"] == "true"
    assert tags["generator"] == "Menivor"
    assert tags["digital_source_type"] == "trainedAlgorithmicMedia"
    assert tags["menivor_content_id"] == "job123"
    assert "AI-generated" in tags["comment"]
    assert ";" not in tags.get("major_brand", "")  # brand keys do not pile up
    assert _stream_md5(video) == before  # packets copied bit for bit
    assert provenance.is_tagged(video)


def test_tag_refuses_a_missing_file(tmp_path):
    with pytest.raises(provenance.ProvenanceError):
        provenance.tag(str(tmp_path / "nope.mp4"), "j")


@needs_ffmpeg
def test_tag_final_replaces_the_stored_copy(tmp_path, monkeypatch):
    video = str(tmp_path / "final.mp4")
    _make_mp4(video)
    uploads: list[tuple[str, str]] = []

    class _R2:
        def upload_file(self, path, key, content_type):  # noqa: ANN001
            assert provenance.is_tagged(path)
            uploads.append((key, content_type))

    monkeypatch.setattr("app.services.storage.r2.get_r2_client", lambda: _R2())
    ctx = {"final_video": video, "final_key": "jobs/j1/final.mp4"}
    assert provenance.tag_final("j1", ctx) is ctx
    assert uploads == [("jobs/j1/final.mp4", "video/mp4")]


def test_compose_stage_tags_before_the_job_completes(monkeypatch):
    from app.workers import tasks_provenance

    calls: list[str] = []
    monkeypatch.setattr(
        "app.services.reelforge.stage_compose",
        lambda job_id, params, ctx: calls.append("compose") or {"final_key": "k", "final_video": "v"},
    )
    monkeypatch.setattr(
        provenance, "tag_final", lambda job_id, ctx: calls.append("tag") or ctx
    )
    out = tasks_provenance.compose_with_provenance("j1", object(), {})
    assert calls == ["compose", "tag"]
    assert out["final_key"] == "k"


def test_pipeline_uses_the_tagging_compose_callback():
    from app.services.reelforge import ReelForgeParams
    from app.workers import pipeline, tasks_provenance

    chain = pipeline.build_retry_chain("j1", ReelForgeParams(video_subject="t"), "compose", {"x": 1})
    assert chain.tasks[0].task == tasks_provenance.COMPOSE_TASK_NAME
    assert tasks_provenance.stage_compose_task.name.endswith("stage_compose_task")


# --------------------------------------------------------------------------- #
# Platform AI flags
# --------------------------------------------------------------------------- #
def test_native_connectors_set_platform_ai_flags():
    from app.domains.publishing.connectors.base import PublishRequest
    from app.domains.publishing.connectors.tiktok import TikTokConnector
    from app.domains.publishing.connectors.youtube import YouTubeConnector

    tiktok = TikTokConnector()._init_body(PublishRequest(platform="tiktok", access_token="t"))
    assert tiktok["post_info"]["is_aigc"] is True
    youtube = YouTubeConnector()._snippet_status(PublishRequest(platform="youtube", access_token="t"))
    assert youtube["status"]["containsSyntheticMedia"] is True


@pytest.mark.parametrize("name", ["TikTokPublisher", "YouTubePublisher", "InstagramPublisher"])
def test_publishers_send_the_ai_disclosure(name):
    import app.services.publishers as pubs

    seen: dict = {}

    class _Client:
        def upload(self, provider, access_token, video_url, *, caption="", **options):  # noqa: ANN001
            seen.update(options)
            return {"id": "1"}

    getattr(pubs, name)(_Client()).publish(access_token="t", video_url="u", extra={"x": 1})
    assert seen["extra"] == {"x": 1, "ai_generated": True}


def test_upload_post_sets_each_platform_field():
    from app.services.upload_post import ai_disclosure_fields

    assert ai_disclosure_fields(["tiktok", "instagram", "youtube"]) == [
        ("is_aigc", "true"),
        ("is_ai_generated", "true"),
        ("containsSyntheticMedia", "true"),
    ]
    assert ai_disclosure_fields([]) == []


# --------------------------------------------------------------------------- #
# Takedown
# --------------------------------------------------------------------------- #
@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture()
def ntfy(monkeypatch):
    posts: list[dict] = []

    class _Resp:
        status_code = 200

    def _post(url, data=None, timeout=None, headers=None):  # noqa: ANN001
        posts.append({"url": url, "text": data.decode("utf-8"), "headers": headers})
        return _Resp()

    monkeypatch.setenv("MENIVOR_OWNER_NTFY_URL", "https://ntfy.example/menivor")
    monkeypatch.setattr("requests.post", _post)
    return posts


@contextmanager
def _gs(factory):
    s = factory()
    try:
        yield s
        s.commit()
    finally:
        s.close()


def _job(s) -> str:
    user = User(email="owner@example.com", credits=0, api_key_hash=hashlib.sha256(b"owner").hexdigest())
    s.add(user)
    s.flush()
    job = Job(user_id=user.id, kind="avatar_reel", params={}, result_key="jobs/x/final.mp4")
    s.add(job)
    s.flush()
    return job.id


def test_report_creates_ticket_alerts_ntfy_and_resolves_the_video(factory, ntfy):
    with factory() as s:
        job_id = _job(s)
        report = takedown.create_report(
            s, content_ref=f"https://menivor.com/reels/{job_id}", reason="impersonation",
            details="uses my face", reporter_email="me@example.com",
        )
        assert report.id and report.status == "open" and report.job_id == job_id
    assert len(ntfy) == 1
    assert report.id in ntfy[0]["text"] and ntfy[0]["headers"]["Priority"] == "high"


def test_report_resolves_a_public_share_link(factory, ntfy):
    with factory() as s:
        job_id = _job(s)
        job = s.get(Job, job_id)
        s.add(ShareLink(token="tok_abcdefgh123", job_id=job_id, user_id=job.user_id))
        s.flush()
        assert takedown.resolve_job_id(s, "see https://menivor.com/r/tok_abcdefgh123") == job_id
        assert takedown.resolve_job_id(s, "no id here") is None


@pytest.mark.parametrize(
    ("ref", "reason", "email"),
    [("", "other", "a@b.co"), ("x", "nonsense", "a@b.co"), ("x", "other", "not-an-email")],
)
def test_bad_reports_are_refused(factory, ntfy, ref, reason, email):
    with factory() as s, pytest.raises(takedown.TakedownError):
        takedown.create_report(s, content_ref=ref, reason=reason, details="", reporter_email=email)
    assert ntfy == []


def test_block_and_restore_toggle_media(factory, ntfy):
    with factory() as s:
        job_id = _job(s)
        r = takedown.create_report(s, content_ref=job_id, reason="copyright", details="", reporter_email="a@b.co")
        assert not takedown.is_blocked_in_session(s, job_id)
        takedown.block(s, r.id, "staff:1")
        assert takedown.is_blocked_in_session(s, job_id)
        takedown.restore(s, r.id, "staff:1")
        assert not takedown.is_blocked_in_session(s, job_id)
        assert s.get(takedown.TakedownReport, r.id) is not None  # never deleted


def test_open_report_is_soft_blocked_after_24h(factory, ntfy):
    with factory() as s:
        job_id = _job(s)
        r = takedown.create_report(s, content_ref=job_id, reason="privacy", details="", reporter_email="a@b.co")
        assert takedown.auto_block_overdue(s) == 0
        later = datetime.now(timezone.utc) + timedelta(hours=takedown.AUTO_BLOCK_HOURS, minutes=1)
        assert takedown.auto_block_overdue(s, now=later) == 1
        assert s.get(takedown.TakedownReport, r.id).resolved_by == takedown.AUTO_BLOCK_ACTOR
        assert takedown.is_blocked_in_session(s, job_id)
    assert len(ntfy) == 2  # the report, then the 24 h block


def test_blocked_media_is_not_served(factory, ntfy, monkeypatch):
    import importlib

    reels_router = importlib.import_module("app.domains.reels.router")

    monkeypatch.setattr(takedown, "is_blocked", lambda job_id: job_id == "blocked")

    class _J:
        id = "blocked"
        result_key = "jobs/blocked/final.mp4"
        poster_key = "p"
        preview_key = "v"
        cover_key = ""

    data: dict = {}
    reels_router._presign_job_artifacts(_J(), data, "rid")
    assert data == {"media_blocked": True, "media_blocked_message": takedown.BLOCKED_MESSAGE}


def test_blocked_share_link_is_gone(factory, ntfy, monkeypatch):
    from app.services import share

    with factory() as s:
        job_id = _job(s)
        job = s.get(Job, job_id)
        s.add(ShareLink(token="tok_zzzzzzzz999", job_id=job_id, user_id=job.user_id))
        s.flush()
        monkeypatch.setattr(takedown, "is_blocked", lambda jid: jid == job_id)
        with pytest.raises(LookupError):
            share.public_view(s, "tok_zzzzzzzz999", presign=lambda k: "u")


def _client(factory, monkeypatch):
    from app.domains.compliance import takedown_router

    @contextmanager
    def _session():
        with _gs(factory) as s:
            yield s

    monkeypatch.setattr(takedown_router, "get_session", _session)
    monkeypatch.setattr(takedown_router, "_require_db", lambda rid: None)
    limited: list[str] = []
    monkeypatch.setattr(
        takedown_router, "enforce_rate_limit",
        lambda request, bucket, limit, window_s: limited.append(bucket),
    )
    monkeypatch.setattr(takedown_router, "_limited", limited, raising=False)
    app = FastAPI()
    app.include_router(takedown_router.router)

    def _handler(request, exc: HttpException):
        return JSONResponse(status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message))

    app.add_exception_handler(HttpException, _handler)
    return TestClient(app)


def test_public_report_api_and_staff_actions(factory, ntfy, monkeypatch):
    client = _client(factory, monkeypatch)
    with factory() as s:
        job_id = _job(s)
        staff = User(email="staff@example.com", credits=0, is_staff=True,
                     api_key_hash=hashlib.sha256(b"staff").hexdigest())
        s.add(staff)
        s.commit()

    res = client.post("/api/v1/legal/reports", json={
        "content": job_id, "reason": "harmful", "details": "", "email": "r@example.com"})
    assert res.status_code == 200, res.text
    ticket = res.json()["data"]["ticket_id"]
    from app.domains.compliance import takedown_router

    assert takedown_router._limited[0] == "legal:report"  # public route is rate-limited
    assert res.json()["data"]["video_found"] is True

    bad = client.post("/api/v1/legal/reports", json={
        "content": job_id, "reason": "harmful", "details": "", "email": "nope"})
    assert bad.status_code == 400

    owner = {"x-api-key": "owner"}
    assert client.post(f"/api/v1/admin/takedown/reports/{ticket}/block", headers=owner).status_code == 403
    staff_h = {"x-api-key": "staff"}
    blocked = client.post(f"/api/v1/admin/takedown/reports/{ticket}/block", headers=staff_h)
    assert blocked.status_code == 200 and blocked.json()["data"]["status"] == "blocked"
    listed = client.get("/api/v1/admin/takedown/reports?status=blocked", headers=staff_h)
    assert [r["id"] for r in listed.json()["data"]] == [ticket]
    with factory() as s:
        assert takedown.is_blocked_in_session(s, job_id)


def test_blocked_video_cannot_be_published(factory, monkeypatch):
    """Verifier fix: a soft-blocked video is refused by both publish paths."""
    from app.domains.publishing import native_service
    from app.models import const
    from app.services import publish

    with _gs(factory) as s:
        job_id = _job(s)
        job = s.get(Job, job_id)
        job.state = const.TASK_STATE_COMPLETE
        owner = str(job.user_id)

    @contextmanager
    def _session():
        with _gs(factory) as s:
            yield s

    monkeypatch.setattr(native_service, "get_session", _session)
    monkeypatch.setattr(publish, "get_session", _session)
    monkeypatch.setattr(takedown, "is_blocked", lambda jid: jid == job_id)

    with pytest.raises(native_service.NativePublishError) as native_err:
        native_service._resolve_final_key(owner, job_id)
    assert native_err.value.status_code == 409
    assert takedown.BLOCKED_MESSAGE in str(native_err.value)
    with pytest.raises(publish.PublishError, match="paused while we review"):
        publish._load_job_snapshot(job_id)

    monkeypatch.setattr(takedown, "is_blocked", lambda jid: False)
    assert native_service._resolve_final_key(owner, job_id)[0] == "jobs/x/final.mp4"
    assert publish._load_job_snapshot(job_id)["final_key"] == "jobs/x/final.mp4"
