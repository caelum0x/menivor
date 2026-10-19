"""M0.4: stuck-reel reaper (retry once, then stop + refund exactly once + email).

Real SQLite jobs and credit ledger; Celery enqueue, revoke, notifications and
SMTP are faked.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.db.base as db_base
from app.domains.reels import queue_eta, refunds
from app.models import const
from app.models.db.base import Base
from app.models.db.models import CreditLedger, Job, User
from app.models.db.repositories import CreditRepository
from app.workers import tasks_reaper

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
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

    monkeypatch.setattr(db_base, "get_session", _session)
    monkeypatch.setattr(queue_eta, "_cache", {"at": 0.0, "value": None})
    monkeypatch.delenv("MENIVOR_REAPER", raising=False)
    monkeypatch.delenv("MENIVOR_JOB_EMAILS", raising=False)

    calls = {"retry": [], "revoke": [], "notify": [], "mail": []}

    from app.workers import pipeline

    def _retry(job_id, params, stage):
        calls["retry"].append((job_id, stage))
        return f"task-{len(calls['retry'])}"

    monkeypatch.setattr(pipeline, "retry_pipeline", _retry)
    monkeypatch.setattr(refunds, "_revoke_celery", lambda task_id: calls["revoke"].append(task_id))
    from app.services import mailer, notifications

    monkeypatch.setattr(
        notifications, "notify_job_failed", lambda user_id, job_id, error: calls["notify"].append((job_id, error))
    )
    monkeypatch.setattr(mailer, "send_email", lambda **kw: calls["mail"].append(kw) or True)

    with _session() as s:
        user = User(email="reaper@example.com", display_name="Reaper")
        s.add(user)
        s.flush()
        CreditRepository(s).grant(user.id, 5, "purchase:test")
        uid = user.id
    return _session, uid, calls


def _stuck_job(Session, uid, *, stages, idle: timedelta, created_ago: timedelta = timedelta(hours=1)) -> str:
    with Session() as s:
        job = Job(
            user_id=uid,
            kind="avatar_reel",
            state=const.TASK_STATE_PROCESSING,
            stages=stages,
            params={"video_subject": "Test", "layout": "captions_only", "_correlation_id": "x"},
            celery_task_id="old-task",
            created_at=NOW - created_ago,
        )
        s.add(job)
        s.flush()
        CreditRepository(s).debit(uid, 1, job.id, "job")
        job_id = job.id
    # Set the last-progress time with SQL (an ORM write would bump it again).
    with Session() as s:
        s.execute(Job.__table__.update().where(Job.id == job_id).values(updated_at=NOW - idle))
    return job_id


def _refund_rows(Session, job_id) -> list[CreditLedger]:
    with Session() as s:
        return list(
            s.execute(select(CreditLedger).where(CreditLedger.job_id == job_id, CreditLedger.delta > 0))
            .scalars()
            .all()
        )


def test_stall_limit_is_twice_the_stage_limit_plus_a_fair_queue_wait():
    assert tasks_reaper.stall_limit_s("compose", running=True, ahead=5, slots=1, per_reel_s=100) == 1320
    assert tasks_reaper.stall_limit_s("compose", running=False, ahead=0, slots=1, per_reel_s=100) == 1320
    assert tasks_reaper.stall_limit_s("compose", running=False, ahead=3, slots=1, per_reel_s=100) == 1620
    assert tasks_reaper.stall_limit_s("compose", running=False, ahead=3, slots=2, per_reel_s=None) == 1320 + 2 * 660


def test_current_stage_prefers_the_running_stage():
    assert tasks_reaper.current_stage({"script": "complete", "tts": "running"}) == ("tts", True)
    assert tasks_reaper.current_stage({"script": "complete", "tts": "complete"}) == ("avatar", False)
    assert tasks_reaper.current_stage({}) == ("script", False)


def test_progressing_job_is_left_alone(env):
    Session, uid, calls = env
    job_id = _stuck_job(Session, uid, stages={"script": "running"}, idle=timedelta(seconds=200))
    assert tasks_reaper.reap_stalled_reels(NOW)["retried"] == 0
    assert calls["retry"] == []
    with Session() as s:
        assert s.get(Job, job_id).state == const.TASK_STATE_PROCESSING


def test_first_stall_retries_once_from_the_stuck_stage(env):
    Session, uid, calls = env
    job_id = _stuck_job(
        Session, uid, stages={"script": "complete", "tts": "running"}, idle=timedelta(minutes=10)
    )
    summary = tasks_reaper.reap_stalled_reels(NOW)
    assert summary["retried"] == 1 and summary["stopped"] == 0
    assert calls["retry"] == [(job_id, "tts")]
    assert calls["revoke"] == ["old-task"]
    with Session() as s:
        job = s.get(Job, job_id)
        assert job.state == const.TASK_STATE_PROCESSING
        assert job.celery_task_id == "task-1"
        assert job.stages[tasks_reaper.REAPER_MARKER]["stage"] == "tts"
        assert job.stages["tts"] == const.REELFORGE_STAGE_PENDING
    assert _refund_rows(Session, job_id) == []  # a retry is the same paid run


def test_second_stall_stops_refunds_exactly_once_and_emails(env):
    Session, uid, calls = env
    job_id = _stuck_job(
        Session,
        uid,
        stages={"script": "complete", "tts": "running", tasks_reaper.REAPER_MARKER: {"stage": "tts"}},
        idle=timedelta(minutes=10),
    )
    first = tasks_reaper.reap_stalled_reels(NOW)
    second = tasks_reaper.reap_stalled_reels(NOW + timedelta(minutes=5))
    assert first["stopped"] == 1 and second["stopped"] == 0
    with Session() as s:
        job = s.get(Job, job_id)
        assert job.state == const.TASK_STATE_FAILED
        assert "returned your credit" in job.error
    refunds_written = _refund_rows(Session, job_id)
    assert len(refunds_written) == 1 and refunds_written[0].delta == 1
    # A later stage failure hook for the same job (racing worker) refunds nothing.
    assert refunds.refund_failed_reel_once(job_id) == 0
    assert len(_refund_rows(Session, job_id)) == 1
    assert [job for job, _ in calls["notify"]] == [job_id]
    assert len(calls["mail"]) == 1
    mail = calls["mail"][0]
    assert mail["to"] == "reaper@example.com"
    assert f"/create/results?jobs={job_id}" in mail["text"]


def test_very_old_reel_is_stopped_without_a_retry(env):
    Session, uid, calls = env
    job_id = _stuck_job(
        Session, uid, stages={"compose": "running"}, idle=timedelta(hours=1), created_ago=timedelta(hours=8)
    )
    assert tasks_reaper.reap_stalled_reels(NOW)["stopped"] == 1
    assert calls["retry"] == []
    assert len(_refund_rows(Session, job_id)) == 1


def test_failed_retry_enqueue_stops_and_refunds(env, monkeypatch):
    Session, uid, calls = env
    from app.workers import pipeline

    def _boom(*args, **kwargs):
        raise RuntimeError("broker down")

    monkeypatch.setattr(pipeline, "retry_pipeline", _boom)
    job_id = _stuck_job(Session, uid, stages={"script": "running"}, idle=timedelta(minutes=10))
    assert tasks_reaper.reap_stalled_reels(NOW)["stopped"] == 1
    assert len(_refund_rows(Session, job_id)) == 1


def test_reaper_can_be_switched_off(env, monkeypatch):
    Session, uid, calls = env
    monkeypatch.setenv("MENIVOR_REAPER", "0")
    _stuck_job(Session, uid, stages={"script": "running"}, idle=timedelta(hours=1))
    assert tasks_reaper.reap_stalled_reels(NOW) == {"examined": 0, "retried": 0, "stopped": 0}


def test_reaper_tick_is_on_the_housekeeping_queue():
    from app.workers.celery_app import HOUSEKEEPING_QUEUE, celery_app

    entry = celery_app.conf.beat_schedule["menivor-reap-stalled-reels"]
    assert entry["task"] == "app.workers.tasks_reaper.reap_stalled_reels_task"
    assert entry["options"] == {"queue": HOUSEKEEPING_QUEUE, "expires": 60.0}
