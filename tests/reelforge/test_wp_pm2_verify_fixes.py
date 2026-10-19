"""Wave P2 Menivor verifier fixes.

1. Box 1 never trusts the client-declared length or resolution of an upload:
   the real source is probed on box 1 before any encode, and a source over the
   box 1 limits (or over the byte cap) goes back to the Mac/burst queue.
2. A running box 1 job is not stolen by the stale-claim sweep (box 1 sends no
   node heartbeats); a box 1 job that really died is re-enqueued, not stranded.
3. An uploaded OTT title (no source job) can be reported and taken down: a
   report naming the title id blocks it, hides it at once and the owner cannot
   republish it while the block stands.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.db.base as db_base
from app.domains.compliance import takedown
from app.domains.ott import catalog_public
from app.domains.ott import service as ott_service
from app.domains.ott.models import OttChannel, OttTitle
from app.models.db.base import Base
from app.models.db.models import User
from app.services.ott_transcode import ladder, service
from app.services.ott_transcode.models import OttEncodeJob


@pytest.fixture()
def maker(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
                           future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr(db_base, "get_session", _session)
    monkeypatch.setattr(service, "paid_plan", lambda user_id: False)
    with factory() as s:
        s.add(User(email="ott-verify@example.com", api_key_hash=hashlib.sha256(b"k").hexdigest()))
        s.commit()
    return factory


def _uid(maker) -> str:
    with maker() as s:
        return s.query(User).one().id


def _upload_title(maker, *, published: bool = False) -> str:
    uid = _uid(maker)
    with maker() as s:
        channel = OttChannel(user_id=uid, handle="up", title="Up", brand_colors=[],
                             status="published" if published else "draft")
        s.add(channel)
        s.flush()
        title = OttTitle(channel_id=channel.id, title="My film", source_key="ott:ott-uploads/u/x/f.mp4",
                         genres=[], geo_countries=[], duration_s=30,
                         status="published" if published else "draft",
                         package_status="ready" if published else "queued",
                         manifest_key="ott/c/t/j/master.m3u8" if published else "")
        s.add(title)
        s.commit()
        return title.id


def _box1_job(maker, title_id: str, *, seconds: float = 6, short_side: int = 720) -> str:
    with maker() as s:
        job = service.submit(s, s.get(OttTitle, title_id), source_key="ott:ott-uploads/u/x/f.mp4",
                             seconds=seconds, short_side=short_side, user_id=_uid(maker))
        assert job.lane == "box1"
        s.commit()
        return job.id


# --------------------------------------------------------------------------- #
# 1. Box 1 probes the real source
# --------------------------------------------------------------------------- #
def test_a_lying_upload_is_rerouted_off_box1_before_any_encode(maker, monkeypatch):
    from app.services.ott_package import packager
    from app.services.ott_transcode import pipeline
    from app.workers import tasks_ott

    title_id = _upload_title(maker)
    job_id = _box1_job(maker, title_id, seconds=6, short_side=720)  # the client said 6 s at 720p
    monkeypatch.setattr(packager, "verify_binary", lambda binary, platform: "0" * 64)
    ran, uploaded = [], []
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: ran.append(1))
    view = tasks_ott.package_on_box1(
        job_id, download=lambda url, dest: open(dest, "wb").close(), upload_dir=lambda *a: uploaded.append(a),
        source_url=lambda key: "https://r2/x", packager_bin="/bin/true",
        probe=lambda path: ladder.Source(3840, 2160, 30.0, 3600.0, True))  # it is an hour of 4K
    assert ran == [] and uploaded == []
    assert view["lane"] == "mac" and view["status"] == "queued" and view["node_id"] is None
    with maker() as s:
        job = s.get(OttEncodeJob, job_id)
        assert job.source_seconds == 3600.0 and job.source_height == 2160 and job.attempts == 0
        assert s.get(OttTitle, title_id).package_status == "queued"


def test_an_honest_short_source_still_runs_on_box1(maker, monkeypatch):
    from app.services.ott_package import packager
    from app.services.ott_transcode import pipeline
    from app.workers import tasks_ott

    title_id = _upload_title(maker)
    job_id = _box1_job(maker, title_id)
    monkeypatch.setattr(packager, "verify_binary", lambda binary, platform: "0" * 64)
    monkeypatch.setattr(pipeline, "run", lambda src, work, **k: pipeline.Result(out_dir=work, files=["master.m3u8"],
                                                                               cpu_seconds=1.5))
    view = tasks_ott.package_on_box1(
        job_id, download=lambda url, dest: open(dest, "wb").close(), upload_dir=lambda *a: None,
        source_url=lambda key: "https://r2/x", packager_bin="/bin/true",
        probe=lambda path: ladder.Source(720, 1280, 30.0, 6.0, True))
    assert view["lane"] == "box1" and view["status"] == "done"


def test_box1_download_stops_at_the_byte_cap(monkeypatch, tmp_path):
    from app.workers import tasks_ott

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, size):
            for _ in range(10):
                yield b"x" * 1024

    import requests

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse())
    with pytest.raises(tasks_ott.SourceTooLarge):
        tasks_ott._download("https://r2/x", str(tmp_path / "src"), max_bytes=4096)
    tasks_ott._download("https://r2/x", str(tmp_path / "ok"), max_bytes=20 * 1024)
    assert (tmp_path / "ok").stat().st_size == 10 * 1024


def test_an_oversized_download_is_rerouted_off_box1(maker, monkeypatch):
    from app.services.ott_package import packager
    from app.workers import tasks_ott

    title_id = _upload_title(maker)
    job_id = _box1_job(maker, title_id)
    monkeypatch.setattr(packager, "verify_binary", lambda binary, platform: "0" * 64)

    def too_big(url, dest):
        raise tasks_ott.SourceTooLarge("over the box 1 byte cap")

    view = tasks_ott.package_on_box1(job_id, download=too_big, upload_dir=lambda *a: None,
                                     source_url=lambda key: "https://r2/x", packager_bin="/bin/true",
                                     probe=lambda path: pytest.fail("never probed"))
    assert view["lane"] == "mac" and view["status"] == "queued" and view["attempts"] == 0


# --------------------------------------------------------------------------- #
# 2. The stale sweep and box 1
# --------------------------------------------------------------------------- #
def test_the_stale_sweep_leaves_a_running_box1_job_alone(maker):
    title_id = _upload_title(maker)
    with maker() as s:
        job = OttEncodeJob(title_id=title_id, user_id="u", source_key="ott:a", lane="box1", status="claimed",
                           node_id="box1", claimed_at=datetime.now(timezone.utc) - timedelta(minutes=10),
                           heartbeat_at=datetime.now(timezone.utc) - timedelta(minutes=10), output_prefix="p")
        s.add(job)
        s.commit()
        assert service.requeue_stale(s) == 0
        assert job.status == "claimed" and job.attempts == 0


def test_a_dead_box1_job_is_requeued_and_re_enqueued(maker, monkeypatch):
    from app.workers import tasks_ott

    title_id = _upload_title(maker)
    with maker() as s:
        job = OttEncodeJob(title_id=title_id, user_id="u", source_key="ott:a", lane="box1", status="claimed",
                           node_id="box1", claimed_at=datetime.now(timezone.utc) - timedelta(hours=2),
                           heartbeat_at=datetime.now(timezone.utc) - timedelta(hours=2), output_prefix="p")
        s.add(job)
        s.commit()
        job_id = job.id
    sent = []
    monkeypatch.setattr(tasks_ott.package_on_box1_task, "apply_async", lambda *a, **k: sent.append(k["args"]))
    assert tasks_ott.requeue_stale_task() == 1
    assert sent == [[job_id]]
    with maker() as s:
        assert s.get(OttEncodeJob, job_id).status == "queued"


# --------------------------------------------------------------------------- #
# 3. Takedown of an uploaded title
# --------------------------------------------------------------------------- #
def test_an_uploaded_title_can_be_reported_and_taken_down(maker, monkeypatch):
    monkeypatch.setattr(takedown, "_alert_owner", lambda *a, **k: True)
    title_id = _upload_title(maker, published=True)
    with maker() as s:
        assert catalog_public.watchable(s, s.get(OttTitle, title_id))
        report = takedown.create_report(s, content_ref=f"https://menivor.com/c/up/{title_id}", reason="copyright",
                                        details="my film", reporter_email="owner@example.com")
        assert report.job_id == title_id
        takedown.block(s, report.id, "staff:1")
        s.commit()
    with maker() as s:
        title = s.get(OttTitle, title_id)
        assert title.status == "hidden" and title.hidden_reason == "takedown"
        assert not catalog_public.watchable(s, title)
        with pytest.raises(ott_service.OttError) as held:
            ott_service.publish_title(s, _uid(maker), title_id)
        assert held.value.code == "compliance_gate"


def test_a_blocked_upload_title_stays_unwatchable_even_if_status_is_forced(maker):
    title_id = _upload_title(maker, published=True)
    with maker() as s:
        s.add(takedown.TakedownReport(job_id=title_id, content_ref=title_id, reason="copyright",
                                      reporter_email="r@example.com", status=takedown.STATUS_BLOCKED))
        s.commit()
    with maker() as s:
        title = s.get(OttTitle, title_id)
        assert title.status == "published"
        assert not catalog_public.watchable(s, title)
        assert ott_service.gate(s, title) is not None
