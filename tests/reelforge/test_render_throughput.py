"""Render throughput: housekeeping queue isolation, x264 speed args, queue ETA."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


# --------------------------------------------------------------------------- #
# Housekeeping queue
# --------------------------------------------------------------------------- #
def test_every_beat_tick_runs_on_the_housekeeping_queue_and_expires():
    from app.workers.celery_app import HOUSEKEEPING_QUEUE, celery_app

    celery_app.loader.import_default_modules()
    schedule = celery_app.conf.beat_schedule
    assert schedule
    for name, entry in schedule.items():
        options = entry.get("options") or {}
        assert options.get("queue") == HOUSEKEEPING_QUEUE, name
        assert 15.0 <= float(options.get("expires")) <= 3600.0, name
        assert celery_app.conf.task_routes[entry["task"]] == {"queue": HOUSEKEEPING_QUEUE}, name


def test_interval_ticks_expire_after_one_period():
    from app.workers.celery_app import celery_app

    by_task = {e["task"]: e for e in celery_app.conf.beat_schedule.values()}
    assert by_task["app.workers.tasks.sweep_render_jobs_task"]["options"]["expires"] == 20.0
    assert by_task["app.workers.tasks.process_due_publishes_task"]["options"]["expires"] == 60.0
    # Daily / crontab ticks are capped at an hour in the queue.
    assert by_task["app.workers.tasks.sweep_retention_task"]["options"]["expires"] == 3600.0


def test_reel_render_stages_stay_off_the_housekeeping_queue():
    from app.workers.celery_app import HOUSEKEEPING_QUEUE, celery_app

    routes = celery_app.conf.task_routes
    assert routes["app.workers.tasks.stage_compose_task"] == {"queue": "render"}
    assert routes["app.workers.tasks.stage_avatar_task"] == {"queue": "render"}
    for stage in ("script", "tts", "captions"):
        route = routes.get(f"app.workers.tasks.stage_{stage}_task")
        assert route is None or route.get("queue") != HOUSEKEEPING_QUEUE


# --------------------------------------------------------------------------- #
# x264 speed args
# --------------------------------------------------------------------------- #
def test_x264_defaults_to_veryfast(monkeypatch):
    from app.services.compose.compose_ffmpeg import _x264_speed_args

    monkeypatch.delenv("MENIVOR_X264_PRESET", raising=False)
    monkeypatch.delenv("MENIVOR_X264_CRF", raising=False)
    assert _x264_speed_args("libx264") == ["-preset", "veryfast", "-crf", "21"]
    assert _x264_speed_args("h264_videotoolbox") == []


def test_x264_env_override_is_validated(monkeypatch):
    from app.services.compose.compose_ffmpeg import _x264_speed_args

    monkeypatch.setenv("MENIVOR_X264_PRESET", "medium")
    monkeypatch.setenv("MENIVOR_X264_CRF", "99")
    assert _x264_speed_args("libx264") == ["-preset", "medium", "-crf", "30"]
    monkeypatch.setenv("MENIVOR_X264_PRESET", "; rm -rf /")
    monkeypatch.setenv("MENIVOR_X264_CRF", "abc")
    assert _x264_speed_args("libx264") == ["-preset", "veryfast", "-crf", "21"]


def test_captions_compose_command_carries_the_speed_args(monkeypatch):
    from app.services.compose.compose_ffmpeg import _build_captions_command

    monkeypatch.delenv("MENIVOR_X264_PRESET", raising=False)
    argv = _build_captions_command("ffmpeg", "s.mp4", "a.mp3", "o.mp4", "[0:v]null[final]", "libx264", 2, 30)
    i = argv.index("-c:v")
    assert argv[i : i + 6] == ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21"]


# --------------------------------------------------------------------------- #
# Queue ETA
# --------------------------------------------------------------------------- #
def test_eta_is_none_without_measurements():
    from app.domains.reels.queue_eta import estimate_eta_s

    assert estimate_eta_s(3, 0, None, 1) is None
    assert estimate_eta_s(3, 0, 0.0, 1) is None


def test_eta_counts_rounds_through_the_render_slots():
    from app.domains.reels.queue_eta import estimate_eta_s

    assert estimate_eta_s(0, 0, 100.0, 1) == 100
    assert estimate_eta_s(2, 0, 100.0, 1) == 300
    assert estimate_eta_s(2, 0, 100.0, 2) == 200
    assert estimate_eta_s(0, 50, 100.0, 1) == 50
    assert estimate_eta_s(0, 100, 100.0, 1) == 10  # floor, never "0 s"


@pytest.fixture()
def session_factory():
    from app.models.db.base import Base

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _job(session, job_id: str, *, state: int, created: datetime, progress: int = 0):
    from app.models.db.models import Job

    job = Job(id=job_id, user_id="u1", state=state, progress=progress, created_at=created, updated_at=created)
    session.add(job)
    return job


def test_queue_status_counts_real_jobs_and_measured_time(session_factory, monkeypatch):
    from app.domains.reels import queue_eta
    from app.models.const import TASK_STATE_COMPLETE, TASK_STATE_PROCESSING
    from app.models.db.models import JobEvent, User

    monkeypatch.setattr(queue_eta, "_cache", {"at": 0.0, "value": None})
    monkeypatch.delenv("MENIVOR_RENDER_SLOTS", raising=False)
    now = datetime.now(timezone.utc)
    with session_factory() as s:
        s.add(User(id="u1", email="journey+eta@example.com"))
        s.flush()
        # Three measured reels: 60 s, 90 s, 120 s of stage work -> median 90 s.
        for index, seconds in enumerate((60, 90, 120)):
            done = _job(s, f"done{index}", state=TASK_STATE_COMPLETE, created=now - timedelta(hours=1))
            s.flush()
            s.add(JobEvent(job_id=done.id, stage="tts", status="complete", duration_ms=seconds * 400))
            s.add(JobEvent(job_id=done.id, stage="compose", status="complete", duration_ms=seconds * 600))
            s.add(JobEvent(job_id=done.id, stage="compose", status="running", duration_ms=999_000))
        _job(s, "stale", state=TASK_STATE_PROCESSING, created=now - timedelta(hours=9))
        _job(s, "ahead1", state=TASK_STATE_PROCESSING, created=now - timedelta(minutes=3), progress=40)
        _job(s, "ahead2", state=TASK_STATE_PROCESSING, created=now - timedelta(minutes=2))
        mine = _job(s, "mine", state=TASK_STATE_PROCESSING, created=now - timedelta(minutes=1))
        _job(s, "later", state=TASK_STATE_PROCESSING, created=now)
        s.commit()

        status = queue_eta.queue_status(s, mine)
        assert status == {"ahead": 2, "eta_s": 270, "slots": 1}

        monkeypatch.setenv("MENIVOR_RENDER_SLOTS", "2")
        assert queue_eta.queue_status(s, mine)["eta_s"] == 180

        finished = _job(s, "fin", state=TASK_STATE_COMPLETE, created=now)
        assert queue_eta.queue_status(s, finished) is None


def test_queue_status_without_history_has_no_eta(session_factory, monkeypatch):
    from app.domains.reels import queue_eta
    from app.models.const import TASK_STATE_PROCESSING
    from app.models.db.models import User

    monkeypatch.setattr(queue_eta, "_cache", {"at": 0.0, "value": None})
    now = datetime.now(timezone.utc)
    with session_factory() as s:
        s.add(User(id="u1", email="journey+eta2@example.com"))
        s.flush()
        mine = _job(s, "solo", state=TASK_STATE_PROCESSING, created=now)
        s.commit()
        assert queue_eta.queue_status(s, mine) == {"ahead": 0, "eta_s": None, "slots": 1}


def test_shortest_buffer_is_bounded_when_ffmpeg_supports_it(monkeypatch):
    from app.services.compose import compose_ffmpeg as cf

    monkeypatch.setattr(cf, "_supports_shortest_buf", lambda ffmpeg: True)
    argv = cf._build_captions_command("ffmpeg", "s.mp4", "a.mp3", "o.mp4", "[0:v]null[final]", "libx264", 2, 30)
    i = argv.index("-shortest")
    assert argv[i : i + 3] == ["-shortest", "-shortest_buf_duration", "1"]

    monkeypatch.setattr(cf, "_supports_shortest_buf", lambda ffmpeg: False)
    argv = cf._build_captions_command("ffmpeg", "s.mp4", "a.mp3", "o.mp4", "[0:v]null[final]", "libx264", 2, 30)
    assert "-shortest" in argv and "-shortest_buf_duration" not in argv


def test_style_scene_is_used_locally_without_an_r2_round_trip(tmp_path, monkeypatch):
    from app.services import reelforge

    track = tmp_path / "style-screen.mp4"
    track.write_bytes(b"\x00" * 64)
    monkeypatch.setattr(
        "app.services.styles.pipeline.build_style_screen", lambda *a, **k: str(track)
    )

    class _NoR2:
        def upload_file(self, *a, **k):  # pragma: no cover - must not be called
            raise AssertionError("the style track must not be uploaded")

    monkeypatch.setattr(reelforge, "_r2", lambda: _NoR2())
    params = reelforge.ReelForgeParams(video_subject="Rally", style="meme_hook")
    assert reelforge._materialize_style_scene("j1", params, {}, str(tmp_path)) == str(track)

    monkeypatch.setattr("app.services.styles.pipeline.build_style_screen", lambda *a, **k: "")
    assert reelforge._materialize_style_scene("j1", params, {}, str(tmp_path)) == ""


# --------------------------------------------------------------------------- #
# Page recording shared across variants
# --------------------------------------------------------------------------- #
def test_page_recording_is_recorded_once_per_page(tmp_path):
    from app.services.styles.recording_cache import cached_recording

    calls: list[str] = []

    def record() -> str:
        calls.append("rec")
        out = tmp_path / f"raw-{len(calls)}.webm"
        out.write_bytes(b"webm" * 16)
        return str(out)

    root = str(tmp_path / "cache")
    first = cached_recording("https://rally.example/", 1080, 680, record, root=root)
    second = cached_recording("https://rally.example/", 1080, 680, record, root=root)
    other_size = cached_recording("https://rally.example/", 960, 900, record, root=root)
    assert first == second and first.endswith("clip.webm")
    assert other_size != first
    assert calls == ["rec", "rec"]


def test_page_recording_cache_expires_and_ignores_failures(tmp_path):
    from app.services.styles import recording_cache

    clock = {"t": 1000.0}
    calls: list[int] = []

    def record() -> str:
        calls.append(1)
        out = tmp_path / f"raw-{len(calls)}.webm"
        out.write_bytes(b"x" * 8)
        return str(out)

    root = str(tmp_path / "cache")
    path = recording_cache.cached_recording("https://a.example/", 10, 10, record, root=root, now=lambda: clock["t"])
    import os

    os.utime(path, (clock["t"], clock["t"]))
    clock["t"] += recording_cache.TTL_S + 1
    recording_cache.cached_recording("https://a.example/", 10, 10, record, root=root, now=lambda: clock["t"])
    assert len(calls) == 2

    assert recording_cache.cached_recording("https://b.example/", 10, 10, lambda: "", root=root) == ""
