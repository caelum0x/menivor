"""M1.3: best hook first, render lanes, admission control and fair share."""

from __future__ import annotations

import json
import sys
import types
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.services.reelforge import ReelForgeParams


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in (
        "MENIVOR_RENDER_LANES", "MENIVOR_QUEUE_CAP", "MENIVOR_API_KEY_CONCURRENT",
        "MENIVOR_RENDER_SLOTS", "MENIVOR_DOGFOOD_USER_IDS", "MENIVOR_ADMISSION",
        "MENIVOR_HOOK_JUDGE", "MENIVOR_FAIR_AGENCY_CONCURRENT", "MENIVOR_FAIR_FREE_DAILY",
    ):
        monkeypatch.delenv(name, raising=False)
    # Lane tests must not depend on the host's free disk: the render-space preflight
    # (10 GB floor) refused these on a full dev machine. Its refusal path is tested
    # on its own below and in test_mg8_degrade.py.
    monkeypatch.setenv("MENIVOR_MIN_FREE_DISK_GB", "0")
    from app.domains.reels import queue_eta

    monkeypatch.setattr(queue_eta, "_cache", {"at": 0.0, "value": None})


@pytest.fixture()
def factory():
    from app.models.db.base import Base

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@pytest.fixture()
def db(factory, monkeypatch):
    """Point ``get_session`` at the in-memory DB."""
    import app.models.db.base as base

    @contextmanager
    def _session():
        session = factory()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    monkeypatch.setattr(base, "get_session", _session)
    return factory


NOW = datetime.now(timezone.utc)


def _job(session, job_id, *, user="u1", state=None, created=None, batch=None, params=None, progress=0):
    from app.models.const import TASK_STATE_PROCESSING
    from app.models.db.models import Job

    job = Job(
        id=job_id, user_id=user, state=TASK_STATE_PROCESSING if state is None else state,
        progress=progress, created_at=created or NOW, updated_at=created or NOW,
        batch_id=batch, params=params or {},
    )
    session.add(job)
    session.flush()
    return job


def _measured(session, per_reel_s: int = 100, count: int = 3):
    """Completed reels with ``per_reel_s`` of measured stage work each."""
    from app.models.const import TASK_STATE_COMPLETE
    from app.models.db.models import JobEvent

    for index in range(count):
        done = _job(session, f"done{index}", user="history", state=TASK_STATE_COMPLETE,
                    created=NOW - timedelta(hours=2))
        session.add(JobEvent(job_id=done.id, stage="compose", status="complete", duration_ms=per_reel_s * 1000))
    session.flush()


def _compose_queue(task_chain) -> str | None:
    """The queue set on the compose signature inside a built chain."""
    for task in task_chain.tasks:
        body = getattr(task, "body", None)
        if body is not None and body.task.endswith("stage_compose_task"):
            return body.options.get("queue")
    return None


def _avatar_queue(task_chain) -> str | None:
    for task in task_chain.tasks:
        tasks = getattr(task, "tasks", None)
        if tasks is not None:
            for sig in tasks.tasks if hasattr(tasks, "tasks") else tasks:
                if sig.task.endswith("stage_avatar_task"):
                    return sig.options.get("queue")
    return None


# --------------------------------------------------------------------------- #
# Lane policy
# --------------------------------------------------------------------------- #
def test_lane_order_is_paid_first_free_variants_bulk():
    from app.domains.reels import policy

    assert policy.render_lane(paid=True, first_reel=True, variant_index=0) == "paid"
    assert policy.render_lane(paid=False, first_reel=True, variant_index=0) == "first"
    assert policy.render_lane(paid=False, first_reel=False, variant_index=0) == "free"
    assert policy.render_lane(paid=True, first_reel=False, variant_index=1) == "variants"
    assert policy.render_lane(paid=True, first_reel=False, variant_index=0, bulk=True) == "bulk"
    assert [policy.lane_rank(lane) for lane in policy.LANES] == [0, 1, 2, 3, 4]


def test_lanes_off_keep_every_render_on_the_render_queue(monkeypatch):
    from app.domains.reels import policy

    assert all(policy.lane_queue(lane) == "render" for lane in policy.LANES)
    monkeypatch.setenv("MENIVOR_RENDER_LANES", "on")
    assert policy.lane_queue("paid") == "render"
    assert policy.lane_queue("variants") == "render_low"
    assert policy.worker_queue_order() == "render,render_first,render_free,render_low,render_bulk"


def test_build_chain_routes_avatar_and_compose_to_the_lane(monkeypatch):
    from app.workers.pipeline import build_chain

    monkeypatch.setenv("MENIVOR_RENDER_LANES", "on")
    params = ReelForgeParams(video_subject="demo")
    chain_ = build_chain("j1", params, "", "variants")
    assert _compose_queue(chain_) == "render_low"
    assert _avatar_queue(chain_) == "render_low"
    plain = build_chain("j1", params)
    assert _compose_queue(plain) is None  # static route (render) unchanged


# --------------------------------------------------------------------------- #
# One create: v1 high lane, v2/v3 low lane
# --------------------------------------------------------------------------- #
def test_one_create_enqueues_v1_high_and_v2_v3_low(db, monkeypatch):
    from app.domains.reels import queue_eta
    from app.models.db.models import Job
    from app.workers import pipeline

    monkeypatch.setenv("MENIVOR_RENDER_LANES", "on")
    monkeypatch.setattr(queue_eta, "user_plan", lambda user_id: ("pro", True))
    captured: dict[str, object] = {}
    monkeypatch.setattr(pipeline, "_apply_chain", lambda chain_, cid: captured.setdefault(
        "chains", []).append(chain_) or types.SimpleNamespace(id="root"))

    with db() as s:
        for index in range(3):
            _job(s, f"v{index + 1}", batch="b1", created=NOW + timedelta(milliseconds=index))
        s.commit()
    params = ReelForgeParams(video_subject="demo")
    for job_id in ("v1", "v2", "v3"):
        pipeline.start_pipeline(job_id, params)

    queues = [_compose_queue(c) for c in captured["chains"]]
    assert queues == ["render", "render_low", "render_low"]
    with db() as s:
        assert [s.get(Job, j).params["_lane"] for j in ("v1", "v2", "v3")] == ["paid", "variants", "variants"]


def test_a_new_free_signup_first_reel_uses_the_first_lane(db, monkeypatch):
    from app.domains.reels import queue_eta
    from app.workers import pipeline

    monkeypatch.setenv("MENIVOR_RENDER_LANES", "on")
    monkeypatch.setattr(queue_eta, "user_plan", lambda user_id: ("free", False))
    chains = []
    monkeypatch.setattr(pipeline, "_apply_chain", lambda c, cid: chains.append(c) or types.SimpleNamespace(id="r"))
    with db() as s:
        _job(s, "old", user="u9", created=NOW - timedelta(days=2))
        _job(s, "first", user="u8")
        _job(s, "again", user="u9")
        s.commit()
    params = ReelForgeParams(video_subject="demo")
    pipeline.start_pipeline("first", params)
    pipeline.start_pipeline("again", params)
    assert [_compose_queue(c) for c in chains] == ["render_first", "render_free"]


def test_dogfood_users_render_in_bulk(db, monkeypatch):
    from app.domains.reels import queue_eta

    monkeypatch.setenv("MENIVOR_DOGFOOD_USER_IDS", "rally-bot, other")
    with db() as s:
        job = _job(s, "dog", user="rally-bot")
        assert queue_eta.resolve_lane(s, job, plan_of=lambda u: ("agency", True)) == "bulk"


def test_lanes_off_start_pipeline_skips_lane_lookup(monkeypatch):
    from app.workers import pipeline

    monkeypatch.setattr(pipeline, "assign_lane", lambda job_id: pytest.fail("lane looked up"))
    monkeypatch.setattr(pipeline, "_job_correlation_id", lambda job_id: "")
    chains = []
    monkeypatch.setattr(pipeline, "_apply_chain", lambda c, cid: chains.append(c) or types.SimpleNamespace(id="r"))
    assert pipeline.start_pipeline("j", ReelForgeParams(video_subject="d")) == "r"
    assert _compose_queue(chains[0]) is None


# --------------------------------------------------------------------------- #
# Preflight hand-off (MG8)
# --------------------------------------------------------------------------- #
def test_preflight_refusal_stops_the_enqueue(monkeypatch):
    from app.workers import pipeline

    module = types.ModuleType("app.workers.preflight")

    def refuse():
        raise RuntimeError("disk below 10 GB")

    module.preflight = refuse
    monkeypatch.setitem(sys.modules, "app.workers.preflight", module)
    # Once the real module was imported, the package attribute wins over
    # sys.modules for ``from app.workers import preflight``: patch both.
    import app.workers as workers_pkg

    monkeypatch.setattr(workers_pkg, "preflight", module, raising=False)
    monkeypatch.setattr(pipeline, "_apply_chain", lambda *a: pytest.fail("enqueued despite preflight"))
    with pytest.raises(RuntimeError, match="disk"):
        pipeline.start_pipeline("j", ReelForgeParams(video_subject="d"))


def test_preflight_uses_mg8_require_capacity_not_the_non_raising_check(monkeypatch):
    """MG8's module exposes check() (never raises) and require_capacity() (raises)."""
    from app.workers import pipeline

    module = types.ModuleType("app.workers.preflight")
    module.check = lambda: types.SimpleNamespace(ok=False)

    def require_capacity():
        raise RuntimeError("disk below 10 GB")

    module.require_capacity = require_capacity
    monkeypatch.setitem(sys.modules, "app.workers.preflight", module)
    # Once the real module was imported, the package attribute wins over
    # sys.modules for ``from app.workers import preflight``: patch both.
    import app.workers as workers_pkg

    monkeypatch.setattr(workers_pkg, "preflight", module, raising=False)
    monkeypatch.setattr(pipeline, "_apply_chain", lambda *a: pytest.fail("enqueued despite preflight"))
    with pytest.raises(RuntimeError, match="disk"):
        pipeline.start_pipeline("j", ReelForgeParams(video_subject="d"))


# --------------------------------------------------------------------------- #
# Admission: honest 429 with Retry-After and ETA
# --------------------------------------------------------------------------- #
def test_over_the_global_cap_returns_429_with_retry_after_and_eta(factory, monkeypatch):
    from app.domains.reels import queue_eta

    monkeypatch.setenv("MENIVOR_QUEUE_CAP", "4")
    monkeypatch.setattr(queue_eta, "user_plan", lambda user_id: ("pro", True))
    with factory() as s:
        _measured(s, per_reel_s=100)
        for index in range(4):
            _job(s, f"q{index}", user=f"other{index}")
        s.commit()
        with pytest.raises(queue_eta.QueueFull) as caught:
            queue_eta.admit_or_429(s, "req-1", "me", requested=1)
    err = caught.value
    assert err.status_code == 429
    assert err.data["code"] == "queue_full"
    assert err.data["eta_s"] == 500  # 4 ahead + this one, 1 slot, 100 s each
    assert err.headers["Retry-After"] == "100"
    assert err.data["ahead"] == 4


def test_admission_without_history_gives_retry_after_but_no_invented_eta(factory, monkeypatch):
    from app.domains.reels import queue_eta

    monkeypatch.setenv("MENIVOR_QUEUE_CAP", "1")
    with factory() as s:
        _job(s, "busy", user="someone")
        decision = queue_eta.admission(s, "me", plan="pro", requested=1)
    assert not decision.allowed
    assert decision.eta_s is None
    assert decision.retry_after_s == 60


def test_under_the_caps_admits_with_the_current_eta(factory):
    from app.domains.reels import queue_eta

    with factory() as s:
        _measured(s, per_reel_s=100)
        _job(s, "a", user="x")
        decision = queue_eta.admission(s, "me", plan="pro", requested=3)
    assert decision.allowed and decision.ahead == 1 and decision.eta_s == 200


def test_admission_can_be_switched_off(factory, monkeypatch):
    from app.domains.reels import queue_eta

    monkeypatch.setenv("MENIVOR_ADMISSION", "off")
    monkeypatch.setenv("MENIVOR_QUEUE_CAP", "1")
    with factory() as s:
        _job(s, "busy", user="someone")
        _job(s, "busy2", user="someone")
        assert queue_eta.admit_or_429(s, "r", "me").allowed


# --------------------------------------------------------------------------- #
# Fair share
# --------------------------------------------------------------------------- #
def test_user_concurrent_cap_follows_the_plan(factory):
    from app.domains.reels import queue_eta

    with factory() as s:
        for index in range(2):
            _job(s, f"m{index}", user="me")
        free = queue_eta.admission(s, "me", plan="free", requested=3)
        agency = queue_eta.admission(s, "me", plan="agency", requested=3)
    assert not free.allowed and free.code == "render_limit"
    assert agency.allowed


def test_api_key_concurrent_cap(factory, monkeypatch):
    from app.domains.reels import queue_eta

    monkeypatch.setenv("MENIVOR_API_KEY_CONCURRENT", "2")
    with factory() as s:
        _job(s, "k1", user="me", params={"_api_key_id": "key-a"})
        _job(s, "k2", user="me", params={"_api_key_id": "key-a"})
        by_a = queue_eta.admission(s, "me", plan="agency", requested=1, api_key_id="key-a")
        by_b = queue_eta.admission(s, "me", plan="agency", requested=1, api_key_id="key-b")
    assert not by_a.allowed and by_a.code == "api_key_render_limit"
    assert by_b.allowed


def test_daily_cap_is_rolling_24h_and_says_when_to_retry(factory, monkeypatch):
    from app.domains.reels import queue_eta
    from app.models.const import TASK_STATE_COMPLETE

    monkeypatch.setenv("MENIVOR_FAIR_FREE_DAILY", "3")
    with factory() as s:
        for index in range(3):
            _job(s, f"d{index}", user="me", state=TASK_STATE_COMPLETE,
                 created=NOW - timedelta(hours=20 - index))
        _job(s, "yesterday", user="me", state=TASK_STATE_COMPLETE, created=NOW - timedelta(hours=30))
        decision = queue_eta.admission(s, "me", plan="free", requested=1, now=NOW)
    assert not decision.allowed and decision.code == "daily_render_limit"
    assert 3.9 * 3600 <= decision.retry_after_s <= 4.1 * 3600


def test_agency_flood_cannot_push_another_paid_first_reel_past_its_eta(factory, monkeypatch):
    """A yearly Agency buyer fires 100 creates of 3 variants; a Pro user then creates."""
    from app.domains.reels import policy, queue_eta

    monkeypatch.setenv("MENIVOR_RENDER_LANES", "on")
    monkeypatch.setenv("MENIVOR_QUEUE_CAP", "500")
    with factory() as s:
        _measured(s, per_reel_s=120)
        admitted = refused = 0
        for batch in range(100):
            decision = queue_eta.admission(s, "agency-user", plan="agency", requested=3)
            if not decision.allowed:
                refused += 1
                continue
            admitted += 1
            for variant in range(3):
                lane = policy.render_lane(paid=True, first_reel=False, variant_index=variant)
                _job(s, f"ag{batch}-{variant}", user="agency-user", batch=f"agb{batch}",
                     created=NOW + timedelta(seconds=batch, milliseconds=variant), params={"_lane": lane})
        s.commit()
        assert admitted == policy.fair_share("agency").concurrent // 3
        assert refused == 100 - admitted

        mine = _job(s, "pro-first", user="pro-user", created=NOW + timedelta(minutes=5),
                    params={"_lane": policy.render_lane(paid=True, first_reel=True, variant_index=0)})
        status = queue_eta.queue_status(s, mine)
    # Only the agency user's variant-1 renders (same lane, earlier) run first.
    assert status["ahead"] == admitted
    assert status["eta_s"] <= (admitted + 1) * 120


def test_without_lanes_ahead_counts_every_earlier_job(factory):
    from app.domains.reels import queue_eta

    with factory() as s:
        for index in range(5):
            _job(s, f"e{index}", user="a", created=NOW - timedelta(minutes=5 - index), params={"_lane": "variants"})
        mine = _job(s, "mine", user="b", params={"_lane": "paid"})
        assert queue_eta.jobs_ahead(s, mine) == 5


# --------------------------------------------------------------------------- #
# Editor export refund on worker failure (MN1 hand-off)
# --------------------------------------------------------------------------- #
def test_editor_export_failure_refunds_once(monkeypatch):
    from app.domains.reels import charge
    from app.workers import tasks

    calls: list[str] = []
    monkeypatch.setattr(tasks, "_report_failure", lambda job_id, stage, exc: calls.append(f"fail:{job_id}"))
    monkeypatch.setattr(charge, "refund_failed_job_once", lambda job_id: calls.append(f"refund:{job_id}") or 1)
    task = tasks.export_editor_cut_task
    task.on_failure(RuntimeError("ffmpeg died"), "tid", ({"job_id": "ex1"},), {}, None)
    assert calls == ["fail:ex1", "refund:ex1"]


# --------------------------------------------------------------------------- #
# Hook judge
# --------------------------------------------------------------------------- #
SCRIPT = "Here is a tool I like.\n\nIt writes your emails.\n\nTry it today."


def _fake_llm(candidates: list[str], scores: list[float]):
    calls: list[str] = []

    def generate(prompt: str) -> str:
        calls.append(prompt)
        if "opening lines, each under" in prompt:
            return json.dumps({"hooks": candidates})
        return "```json\n" + json.dumps({"scores": scores}) + "\n```"

    return generate, calls


def test_judge_scores_five_hooks_and_the_winner_opens_the_script():
    from app.services.script.hook_judge import best_hook_script

    generate, calls = _fake_llm(
        ["You are losing 3 hours a week to email.", "Stop writing emails by hand.",
         "What if your inbox answered itself?", "I deleted my email templates."],
        [4, 9, 6, 7, 5],
    )
    script, verdict = best_hook_script(SCRIPT, subject="Rally", language="en", angle="pov", generate=generate)
    assert len(calls) == 2
    assert "Keep this angle: pov" in calls[0]
    assert len(verdict.hooks) == 5 and verdict.winner == 1
    assert script == "You are losing 3 hours a week to email.\n\nIt writes your emails.\n\nTry it today."


def test_judge_tie_keeps_the_writers_hook():
    from app.services.script.hook_judge import best_hook_script

    generate, _ = _fake_llm(["A.", "B.", "C.", "D."], [8, 8, 1, 1, 1])
    script, verdict = best_hook_script(SCRIPT, subject="Rally", generate=generate)
    assert verdict.winner == 0 and script == SCRIPT


def test_llm_down_never_replaces_the_hook():
    from app.services.script.hook_judge import best_hook_script

    script, verdict = best_hook_script(SCRIPT, subject="Rally", generate=lambda p: "Error: relay down")
    assert script == SCRIPT
    assert verdict.source == "heuristic" and verdict.candidates_source == "templates"
    assert len(verdict.hooks) == 5


def test_bad_judge_output_falls_back_without_replacing():
    from app.services.script.hook_judge import best_hook_script

    generate, _ = _fake_llm(["A one.", "B two.", "C three.", "D four."], [1, 2])  # wrong length
    script, verdict = best_hook_script(SCRIPT, subject="Rally", generate=generate)
    assert script == SCRIPT and verdict.source == "heuristic"


def test_judge_can_be_switched_off(monkeypatch):
    from app.services.script.hook_judge import best_hook_script

    monkeypatch.setenv("MENIVOR_HOOK_JUDGE", "off")
    script, verdict = best_hook_script(SCRIPT, subject="Rally", generate=lambda p: pytest.fail("called"))
    assert script == SCRIPT and verdict is None


def test_heuristic_prefers_short_direct_lines():
    from app.services.script.hook_judge import heuristic_score, replace_hook

    assert heuristic_score("You lose 3 hours a week to email?") > heuristic_score(
        "So today in this video I want to talk about a few things that I have been thinking about lately"
    )
    assert heuristic_score("") == 0.0
    assert replace_hook("Old.", "New.") == "New."


def test_stage_script_uses_the_judged_hook(monkeypatch):
    from app.services import reelforge
    from app.services.script import hook_judge, ugc

    monkeypatch.setattr(ugc, "generate_ugc_script", lambda **kw: {"full_text": SCRIPT})
    monkeypatch.setattr(reelforge, "_persist_script", lambda job_id, text: None)
    generate, _ = _fake_llm(["Win line one.", "B.", "C.", "D."], [1, 9, 2, 2, 2])
    real = hook_judge.best_hook_script
    monkeypatch.setattr(hook_judge, "best_hook_script", lambda script, **kw: real(script, generate=generate, **kw))
    events = []
    monkeypatch.setattr("app.telemetry.events.record_event", lambda *a, **kw: events.append((a, kw)))
    out = reelforge.stage_script("j1", ReelForgeParams(video_subject="Rally"), {})
    assert out["script"].startswith("Win line one.")
    assert events and events[0][0][2] == "hook_judge"
