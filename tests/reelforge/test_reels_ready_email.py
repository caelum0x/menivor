"""M0.6: "your reels are ready" email, once per run (batch), on the first reel.

Real SQLite jobs; the in-app write, push and SMTP are faked.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.db.base as db_base
from app.models import const
from app.models.db.base import Base
from app.models.db.models import Job, User
from app.services import email_templates, mailer, notifications


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
    monkeypatch.setattr(notifications, "_emit", lambda *a, **k: "n1")
    monkeypatch.setattr(notifications, "_safe_push", lambda *a, **k: None)
    monkeypatch.delenv("MENIVOR_JOB_EMAILS", raising=False)
    sent: list[dict] = []
    monkeypatch.setattr(mailer, "send_email", lambda **kw: sent.append(kw) or True)
    with _session() as s:
        user = User(email="maker@example.com", display_name="Maker")
        s.add(user)
        s.flush()
        uid = user.id
    return _session, uid, sent


def _jobs(Session, uid, n: int, *, batch: str | None, kind: str = "avatar_reel") -> list[str]:
    ids = []
    with Session() as s:
        for index in range(n):
            job = Job(
                user_id=uid,
                kind=kind,
                batch_id=batch,
                state=const.TASK_STATE_PROCESSING,
                params={"video_subject": "Launch day"},
            )
            s.add(job)
            s.flush()
            ids.append(job.id)
    return ids


def _finish(Session, job_id: str) -> None:
    with Session() as s:
        s.get(Job, job_id).state = const.TASK_STATE_COMPLETE


def test_one_email_per_batch_on_the_first_finished_reel(env):
    Session, uid, sent = env
    ids = _jobs(Session, uid, 3, batch="b" * 32)
    for job_id in ids:
        _finish(Session, job_id)
        notifications.notify_job_complete(uid, job_id)
    assert len(sent) == 1
    mail = sent[0]
    assert mail["to"] == "maker@example.com"
    assert mail["subject"] == "Your reels are ready"
    link = mail["text"].split("/create/results?jobs=", 1)[1].split()[0]
    assert sorted(link.split(",")) == sorted(ids)
    assert "The other 2 are finishing" in mail["text"]


def test_a_second_batch_gets_its_own_email(env):
    Session, uid, sent = env
    for batch in ("a" * 32, "c" * 32):
        for job_id in _jobs(Session, uid, 2, batch=batch):
            _finish(Session, job_id)
            notifications.notify_job_complete(uid, job_id)
    assert len(sent) == 2


def test_single_reel_gets_one_email(env):
    Session, uid, sent = env
    (job_id,) = _jobs(Session, uid, 1, batch=None)
    _finish(Session, job_id)
    notifications.notify_job_complete(uid, job_id)
    notifications.notify_job_complete(uid, job_id)  # a duplicate terminal hook
    assert len(sent) == 1
    assert sent[0]["subject"] == "Your video is ready"


def test_other_job_kinds_and_unfinished_jobs_send_nothing(env):
    Session, uid, sent = env
    (clip,) = _jobs(Session, uid, 1, batch=None, kind="clipping")
    _finish(Session, clip)
    notifications.notify_job_complete(uid, clip, kind="clipping")
    (pending,) = _jobs(Session, uid, 1, batch=None)
    notifications.notify_job_complete(uid, pending)
    assert sent == []


def test_internal_accounts_get_no_reel_email(env, monkeypatch):
    Session, uid, sent = env
    monkeypatch.delenv("MENIVOR_INTERNAL_EMAIL_DOMAINS", raising=False)
    with Session() as s:
        s.get(User, uid).email = "smoke-internal@menivor.com"
    (job_id,) = _jobs(Session, uid, 1, batch=None)
    _finish(Session, job_id)
    notifications.notify_job_complete(uid, job_id)
    assert sent == []


def test_emails_can_be_switched_off(env, monkeypatch):
    Session, uid, sent = env
    monkeypatch.setenv("MENIVOR_JOB_EMAILS", "0")
    (job_id,) = _jobs(Session, uid, 1, batch=None)
    _finish(Session, job_id)
    notifications.notify_job_complete(uid, job_id)
    assert sent == []


def test_mailer_failure_never_breaks_the_notification(env, monkeypatch):
    Session, uid, sent = env

    def _boom(**kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(mailer, "send_email", _boom)
    (job_id,) = _jobs(Session, uid, 1, batch=None)
    _finish(Session, job_id)
    assert notifications.notify_job_complete(uid, job_id) == "n1"


def test_batch_template_has_no_emoji_and_names_the_reel():
    rendered = email_templates.video_ready_email(
        title="Launch day", url="https://menivor.com/create/results?jobs=a,b", batch_size=2
    )
    assert "The other one is finishing" in rendered.text
    assert all(ord(ch) < 0x2190 for ch in rendered.html + rendered.text)
