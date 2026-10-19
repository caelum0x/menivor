"""M1.5: stage metrics (p50/p90), owner alerts, canary and the daily economics email."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.domains.observability import render_metrics as rm
from app.models import const

T0 = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


def _ev(job, stage, status, sec, dur_ms=0, cost=0.0):
    return rm.EventRow(job, stage, status, T0 + timedelta(seconds=sec), dur_ms, cost)


def _reel(job_id, *, wait_compose, compose_s, state=const.TASK_STATE_COMPLETE, canary=False):
    """A reel created at T0: script 0-10 s, tts 10-20 s, compose after a slot wait."""
    job = rm.JobRow(job_id, T0, state, canary=canary)
    start = 20 + wait_compose
    evs = [
        _ev(job_id, "script", "running", 1),
        _ev(job_id, "script", "complete", 10, 9000),
        _ev(job_id, "tts", "running", 10),
        _ev(job_id, "tts", "complete", 20, 10000, cost=0.0),
        _ev(job_id, "compose", "running", start),
    ]
    if state == const.TASK_STATE_COMPLETE:
        evs.append(_ev(job_id, "compose", "complete", start + compose_s, compose_s * 1000))
    return job, evs


def _fixture():
    jobs, events = {}, []
    for i, (wait, dur) in enumerate([(0, 60), (30, 70), (60, 80), (90, 90), (120, 100)]):
        job, evs = _reel(f"j{i}", wait_compose=wait, compose_s=dur)
        jobs[job.id] = job
        events += evs
    return jobs, events


def test_percentile_matches_linear_interpolation():
    assert rm.percentile([], 50) is None
    assert rm.percentile([5.0], 90) == 5.0
    assert rm.percentile([1, 2, 3, 4, 5], 50) == 3.0
    assert rm.percentile([1, 2, 3, 4, 5], 90) == pytest.approx(4.6)
    assert rm.percentile([10, 20], 50) == 15.0


def test_p50_p90_from_fixture_events():
    jobs, events = _fixture()
    s = rm.summarize(events, jobs, T0, T0 + timedelta(hours=1))
    assert s.stage_seconds["compose"] == rm.Dist(5, 80.0, 96.0)
    assert s.stage_seconds["script"] == rm.Dist(5, 9.0, 9.0)
    # Compose waits 0/30/60/90/120 s for a slot after tts completes.
    assert s.queue_wait_seconds["compose"] == rm.Dist(5, 60.0, 108.0)
    assert s.render_queue_wait == rm.Dist(5, 60.0, 108.0)
    # Script waits 1 s after creation.
    assert s.queue_wait_seconds["script"].p50 == 1.0
    # Time to reel = 20 + wait + compose: 80, 120, 160, 200, 240.
    assert s.time_to_reel == rm.Dist(5, 160.0, 224.0)
    assert s.reels_finished == 5 and s.reels_failed == 0
    assert s.failure_rate == 0.0


def test_canary_is_excluded_from_customer_metrics():
    jobs, events = _fixture()
    canary, cevs = _reel("canary", wait_compose=5000, compose_s=900, canary=True)
    jobs[canary.id] = canary
    s = rm.summarize(events + cevs, jobs, T0, T0 + timedelta(hours=1))
    assert s.render_queue_wait.count == 5
    assert s.canary_reels == 1
    assert s.reels_finished == 5


def test_retry_does_not_count_twice():
    job, evs = _reel("r", wait_compose=10, compose_s=50)
    evs.append(_ev("r", "compose", "running", 400))
    waits = rm.queue_waits(evs, {"r": job})
    assert waits["compose"] == [10.0]


# --------------------------------------------------------------------------- #
# Alerts
# --------------------------------------------------------------------------- #
def _summary(**over):
    base = dict(
        since=T0,
        until=T0,
        stage_seconds={},
        queue_wait_seconds={},
        render_queue_wait=rm.Dist(0, None, None),
        time_to_reel=rm.Dist(0, None, None),
        reels_finished=10,
        reels_failed=0,
        provider_spend_usd=0.0,
    )
    base.update(over)
    return rm.Summary(**base)


def test_no_alerts_when_healthy():
    assert rm.evaluate(_summary(), [], 0.5, rm.Thresholds()) == []


def test_queue_wait_p90_over_10_minutes_alerts():
    s = _summary(render_queue_wait=rm.Dist(8, 120.0, 601.0))
    keys = [a.key for a in rm.evaluate(s, [], 0.0, rm.Thresholds())]
    assert keys == ["queue_wait"]


def test_failure_rate_over_10_percent_alerts_only_with_enough_reels():
    th = rm.Thresholds()
    assert [a.key for a in rm.evaluate(_summary(reels_finished=8, reels_failed=2), [], 0, th)] == [
        "failure_rate"
    ]
    assert rm.evaluate(_summary(reels_finished=9, reels_failed=1), [], 0, th) == []  # exactly 10%
    assert rm.evaluate(_summary(reels_finished=1, reels_failed=1), [], 0, th) == []  # too few


def test_stuck_and_spend_alerts():
    alerts = rm.evaluate(_summary(), ["a", "b"], 7.5, rm.Thresholds(daily_budget_usd=5.0))
    assert [a.key for a in alerts] == ["stuck", "spend"]
    assert "$7.50" in alerts[1].message


def test_thresholds_from_env():
    th = rm.Thresholds.from_env(
        {"MENIVOR_ALERT_QUEUE_WAIT_P90_S": "300", "MENIVOR_DAILY_PROVIDER_BUDGET_USD": "bad"}
    )
    assert th.queue_wait_p90_s == 300.0
    assert th.daily_budget_usd == 5.0


def test_notify_dedups_and_retries_failed_sends():
    store = rm._LocalDedup()
    sent: list[str] = []
    alert = rm.Alert("queue_wait", "t", "m")
    assert rm.notify([alert], store=store, sender=lambda a: sent.append(a.key) or True) == ["queue_wait"]
    assert rm.notify([alert], store=store, sender=lambda a: True) == []  # deduped
    store2 = rm._LocalDedup()
    assert rm.notify([alert], store=store2, sender=lambda a: False) == []
    assert rm.notify([alert], store=store2, sender=lambda a: True) == ["queue_wait"]  # retried


def test_send_ntfy_posts_to_the_menivor_topic():
    seen = {}

    def post(url, body, headers):
        seen.update(url=url, body=body, headers=headers)
        return 200

    env = {"NTFY_URL_MENIVOR": "https://ntfy.sh/abc", "NTFY_URL": "https://ntfy.sh/box", "NTFY_TOKEN": "tk"}
    assert rm.send_ntfy(rm.Alert("k", "Title", "Body"), env=env, post_fn=post)
    assert seen["url"] == "https://ntfy.sh/abc"
    assert seen["headers"]["Authorization"] == "Bearer tk"
    assert seen["body"] == b"Body"
    assert not rm.send_ntfy(rm.Alert("k", "T", "B"), env={}, post_fn=post)
    assert not rm.send_ntfy(rm.Alert("k", "T", "B"), env=env, post_fn=lambda *a: 500)


# --------------------------------------------------------------------------- #
# Canary
# --------------------------------------------------------------------------- #
def _job(state, minutes_ago, **kw):
    return SimpleNamespace(
        id="c1", state=state, created_at=T0 - timedelta(minutes=minutes_ago), failed_stage="", error="", **kw
    )


def test_canary_alert_fires_when_render_exceeds_10_minutes():
    from app.workers import tasks_canary as tc

    max_s = 600.0
    assert tc.canary_verdict(_job(const.TASK_STATE_PROCESSING, 9), T0, max_s) is None
    alert = tc.canary_verdict(_job(const.TASK_STATE_PROCESSING, 11), T0, max_s)
    assert alert is not None and alert.key == "canary_slow:c1"
    assert "11.0 min" in alert.message
    assert tc.canary_verdict(_job(const.TASK_STATE_COMPLETE, 30), T0, max_s) is None


def test_canary_failure_alerts():
    from app.workers import tasks_canary as tc

    job = _job(const.TASK_STATE_FAILED, 3)
    job.failed_stage, job.error = "compose", "ffmpeg exited 1"
    alert = tc.canary_verdict(job, T0, 600.0)
    assert alert.key == "canary_failed:c1" and "compose" in alert.message


def test_check_canary_sends_the_alert(monkeypatch):
    from contextlib import contextmanager

    from app.workers import tasks_canary as tc

    monkeypatch.setenv("MENIVOR_CANARY_USER_ID", "u-canary")
    monkeypatch.setattr(tc, "latest_canary", lambda s, now: _job(const.TASK_STATE_PROCESSING, 15))

    @contextmanager
    def fake_session():
        yield object()

    got: list = []
    out = tc.check_canary(T0, session_factory=fake_session, notify=lambda a: got.extend(a) or ["x"])
    assert out["status"] == "alert" and out["sent"] is True
    assert got[0].key == "canary_slow:c1"


def test_canary_skipped_without_account(monkeypatch):
    from app.workers import tasks_canary as tc

    monkeypatch.delenv("MENIVOR_CANARY_USER_ID", raising=False)
    assert tc.start_canary()["status"] == "not_configured"
    monkeypatch.setenv("MENIVOR_CANARY", "off")
    assert tc.start_canary()["status"] == "disabled"


def test_canary_params_are_free_and_unpublished():
    from app.services.reelforge import _is_faceless_tts
    from app.workers import tasks_canary as tc

    p = tc.canary_params()
    assert p.platforms == ()
    assert not p.voice_name.startswith("elevenlabs:")
    assert p.video_script  # fixed script: no LLM call
    assert _is_faceless_tts(p)


def test_start_canary_creates_and_enqueues(monkeypatch):
    from contextlib import contextmanager

    from app.workers import tasks_canary as tc

    monkeypatch.setenv("MENIVOR_CANARY_USER_ID", "u-canary")
    monkeypatch.delenv("MENIVOR_RENDER_LANES", raising=False)
    created = {}

    class FakeRepo:
        def __init__(self, session):
            pass

        def create(self, user_id, kind, params, batch_id=None):
            created.update(user_id=user_id, kind=kind, params=params)
            return SimpleNamespace(id="job-c")

    monkeypatch.setattr("app.models.db.repositories.JobRepository", FakeRepo)

    class S:
        def get(self, *_a):
            return None

    @contextmanager
    def fake_session():
        yield S()

    calls = []
    out = tc.start_canary(session_factory=fake_session, start_fn=lambda *a: calls.append(a) or "task-1")
    assert out == {"status": "started", "job_id": "job-c"}
    assert created["params"][rm.CANARY_PARAM] is True
    assert created["user_id"] == "u-canary"
    assert calls[0][0] == "job-c" and calls[0][2] == ""  # lanes off: historical render queue


# --------------------------------------------------------------------------- #
# Celery wiring
# --------------------------------------------------------------------------- #
def test_beat_has_canary_alerts_and_economics_on_housekeeping():
    from app.workers.celery_app import HOUSEKEEPING_QUEUE, celery_app

    beat = celery_app.conf.beat_schedule
    for name, every in (
        ("menivor-canary-reel", 6 * 3600.0),
        ("menivor-canary-check", 300.0),
        ("menivor-render-alerts", 300.0),
    ):
        assert beat[name]["schedule"] == every
        assert beat[name]["options"]["queue"] == HOUSEKEEPING_QUEUE
    assert beat["menivor-economics-daily"]["options"]["queue"] == HOUSEKEEPING_QUEUE
    assert "app.workers.tasks_canary" in celery_app.conf.include


def test_erasure_module_registered_only_when_present():
    import importlib.util

    from app.workers import celery_app as mod

    present = importlib.util.find_spec("app.workers.tasks_erasure") is not None
    assert ("app.workers.tasks_erasure" in mod.celery_app.conf.include) is present
    assert "app.workers.tasks_erasure" in mod._OPTIONAL_TASK_MODULES


# --------------------------------------------------------------------------- #
# Daily economics email
# --------------------------------------------------------------------------- #
def test_economics_text_is_plain_and_honest():
    from app.services.funnel import weekly

    jobs, events = _fixture()
    s = rm.summarize(events, jobs, T0, T0 + timedelta(days=1))
    text = weekly.economics_text(
        "2026-09-27", s, {"bought": 100, "spent": 40, "refunded": 2, "granted": 9}, 1.25
    )
    assert "Finished: 5" in text
    assert "Provider spend per finished reel: $0.250" in text
    assert "Create to playable reel: p50 2.7 min, p90 3.7 min" in text
    assert "Bought: 100" in text
    assert "not money" in text


def test_economics_with_no_reels_says_so():
    from app.services.funnel import weekly

    s = rm.summarize([], {}, T0, T0)
    text = weekly.economics_text("2026-09-27", s, {"bought": 0, "spent": 0, "refunded": 0, "granted": 0}, 0.0)
    assert "no finished reels" in text
    assert "p50 no data" in text


def test_daily_economics_sends_once(monkeypatch):
    from contextlib import contextmanager

    from app.services import mailer
    from app.services.funnel import weekly

    store = rm._LocalDedup()
    monkeypatch.setattr(rm, "_dedup_store", lambda: store)

    @contextmanager
    def fake_session():
        yield object()

    monkeypatch.setattr("app.models.db.base.get_session", fake_session)
    monkeypatch.setattr(rm, "summary_for", lambda *a: rm.summarize([], {}, T0, T0))
    monkeypatch.setattr(rm, "provider_spend", lambda *a: 0.0)
    monkeypatch.setattr(weekly, "_credit_totals", lambda *a: {"bought": 0, "spent": 0, "refunded": 0, "granted": 0})
    sent = []
    monkeypatch.setattr(mailer, "send_email", lambda **kw: sent.append(kw) or True)
    assert weekly.run_daily_economics(T0)["status"] == "sent"
    assert weekly.run_daily_economics(T0)["status"] == "already_sent"
    assert len(sent) == 1 and "2026-09-27" in sent[0]["subject"]


# --------------------------------------------------------------------------- #
# DB path (SQLite test DB)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.models.db.base import Base

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with factory() as s:
        yield s


def test_summary_and_stuck_from_db(db):
    from app.models.db.models import Job, JobEvent, User

    now = datetime.now(timezone.utc)
    user = User(email="m15@example.com")
    db.add(user)
    db.flush()
    done = Job(user_id=user.id, kind="avatar_reel", state=const.TASK_STATE_COMPLETE, params={})
    stuck = Job(user_id=user.id, kind="avatar_reel", state=const.TASK_STATE_PROCESSING, params={})
    canary = Job(
        user_id=user.id, kind="avatar_reel", state=const.TASK_STATE_PROCESSING, params={"_canary": True}
    )
    db.add_all([done, stuck, canary])
    db.flush()
    db.add_all(
        [
            JobEvent(job_id=done.id, stage="compose", status="complete", duration_ms=42000),
            JobEvent(job_id=done.id, stage="compose", status="cost", cost_usd=0.25),
        ]
    )
    stuck.updated_at = now - timedelta(hours=3)
    canary.updated_at = now - timedelta(hours=3)
    db.commit()

    window = (now - timedelta(hours=1), now + timedelta(minutes=1))
    s = rm.summary_for(db, *window)
    assert s.stage_seconds["compose"] == rm.Dist(1, 42.0, 42.0)
    assert s.reels_finished == 1 and s.canary_reels == 1
    assert rm.provider_spend(db, *window) == pytest.approx(0.25)
    assert rm.stuck_reels(db, now, 90) == [stuck.id]
