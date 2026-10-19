"""Brand Agent chat tools, the approval gate, and routines.

Anything that spends credits or publishes becomes a ``pending`` action; the
generation / clone / publish ports run only after an explicit approve, exactly
once. Routines run on beat and only ever create pending actions.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domains.brand_agent import agent, gate, library, routines, sessions, setup_flow, spaces
from app.domains.brand_agent.models import AgentAction, AgentRoutine
from app.domains.brand_agent.ports.base import PortUnavailable
from tests.reelforge._brand_agent_support import (
    SITE_URL,
    T0,
    FakeAdClone,
    FakeGeneration,
    connect_account,
    make_deps,
    make_factory,
    make_user,
)

UTC = timezone.utc


@pytest.fixture()
def db():
    return make_factory()


@pytest.fixture()
def owner(db):
    return make_user(db)


@pytest.fixture()
def ready(db, owner):
    """A session whose brand setup is finished (Meta skipped)."""
    deps = make_deps()
    with db.scope() as s:
        space = spaces.ensure_default(s, owner)
        sid = sessions.create(s, owner, space.id).id
    with db.scope() as s:
        agent.handle_text(s, deps, owner, sid, f"set up my brand from my website: {SITE_URL}")
    for step in (setup_flow.STEP_POSITIONING, setup_flow.STEP_PRODUCT, setup_flow.STEP_MARKET,
                 setup_flow.STEP_VOICE):
        with db.scope() as s:
            agent.handle_chip(s, deps, owner, sid, step=step, choice="yes")
    with db.scope() as s:
        agent.handle_chip(s, deps, owner, sid, step=setup_flow.STEP_META, choice="skip")
    return deps, space.id, sid


def _say(db, deps, uid, sid, text):
    with db.scope() as s:
        return agent.handle_text(s, deps, uid, sid, text)


def _action_from(messages):
    for m in reversed(messages):
        if m.get("action"):
            return m["action"]
    raise AssertionError(f"no action in {messages}")


# --------------------------------------------------------------------------- #
# Text tools (no spend, no approval)
# --------------------------------------------------------------------------- #
def test_hooks_use_brand_memory_and_need_no_approval(db, owner, ready):
    deps, _, sid = ready
    out = _say(db, deps, owner, sid, "Write 5 hooks for TikTok")
    hooks = out[-1]["card"]["data"]["hooks"]
    assert len(hooks) == 5 and all(isinstance(h, str) and h for h in hooks)
    assert not out[-1].get("action")
    assert deps.generation.calls == []


def test_script_is_written_from_memory(db, owner, ready):
    deps, _, sid = ready
    out = _say(db, deps, owner, sid, "write a 30 second UGC script")
    script = out[-1]["card"]["data"]
    assert script["kind"] == "script" and script["lines"]
    assert "Basepoint" in " ".join(script["lines"])


# --------------------------------------------------------------------------- #
# Approval gate
# --------------------------------------------------------------------------- #
def test_video_request_creates_a_pending_action_and_spends_nothing(db, owner, ready):
    deps, space_id, sid = ready
    out = _say(db, deps, owner, sid, "Make a 15s video ad about flat pricing")
    action = _action_from(out)
    assert action["status"] == gate.STATUS_PENDING and action["kind"] == gate.KIND_VIDEO
    assert action["credits_estimate"] > 0
    assert [c["choice"] for c in out[-1]["chips"]] == ["approve", "reject"]
    assert deps.generation.calls == []


def test_approve_executes_once_and_lands_in_the_library(db, owner, ready):
    deps, space_id, sid = ready
    action = _action_from(_say(db, deps, owner, sid, "make an image ad for the launch"))
    with db.scope() as s:
        done = gate.decide(s, deps, owner, action["id"], gate.APPROVE)
    assert done["status"] == gate.STATUS_EXECUTED
    assert len(deps.generation.calls) == 1 and deps.generation.calls[0]["kind"] == "image"
    assert "Basepoint" in deps.generation.calls[0]["prompt"]
    with db.scope() as s:
        again = gate.decide(s, deps, owner, action["id"], gate.APPROVE)
        items = library.list_items(s, owner, space_id)
    assert again["status"] == gate.STATUS_EXECUTED
    assert len(deps.generation.calls) == 1  # idempotent
    assert [i["ref"] for i in items] == ["media-1"]
    with db.scope() as s, pytest.raises(gate.GateError) as err:
        gate.decide(s, deps, owner, action["id"], gate.REJECT)
    assert err.value.status_code == 409


def test_reject_never_executes(db, owner, ready):
    deps, _, sid = ready
    action = _action_from(_say(db, deps, owner, sid, "make a video"))
    with db.scope() as s:
        out = gate.decide(s, deps, owner, action["id"], gate.REJECT)
    assert out["status"] == gate.STATUS_REJECTED
    assert deps.generation.calls == []


def test_another_user_cannot_decide(db, owner, ready):
    deps, _, sid = ready
    action = _action_from(_say(db, deps, owner, sid, "make a video"))
    other = make_user(db, "other@example.com")
    with db.scope() as s, pytest.raises(gate.GateError) as err:
        gate.decide(s, deps, other, action["id"], gate.APPROVE)
    assert err.value.status_code == 404
    assert deps.generation.calls == []


def test_failed_execution_is_recorded_and_retryable(db, owner, ready):
    deps, _, sid = ready
    deps.generation.fail = RuntimeError("upstream api_key=sk-live-123 exploded")
    action = _action_from(_say(db, deps, owner, sid, "make a video"))
    with db.scope() as s:
        out = gate.decide(s, deps, owner, action["id"], gate.APPROVE)
    assert out["status"] == gate.STATUS_FAILED and "sk-live-123" not in out["error"]
    deps.generation.fail = None
    with db.scope() as s:
        out = gate.decide(s, deps, owner, action["id"], gate.APPROVE)
    assert out["status"] == gate.STATUS_EXECUTED


def test_clone_from_link_goes_through_the_gate_and_the_ad_clone_port(db, owner, ready):
    deps, space_id, sid = ready
    out = _say(db, deps, owner, sid, "clone this ad https://www.tiktok.com/@brand/video/7300000000000000000")
    action = _action_from(out)
    assert action["kind"] == gate.KIND_CLONE and deps.ad_clone.calls == []
    with db.scope() as s:
        done = gate.decide(s, deps, owner, action["id"], gate.APPROVE)
    assert done["status"] == gate.STATUS_EXECUTED
    assert deps.ad_clone.calls == [(owner, "https://www.tiktok.com/@brand/video/7300000000000000000", space_id)]


def test_clone_port_missing_fails_with_its_reason(db, owner, ready):
    deps, _, sid = ready
    deps.ad_clone.error = PortUnavailable("Ad Clone is not installed on this server yet.")
    action = _action_from(_say(db, deps, owner, sid, "clone https://www.tiktok.com/@a/video/1"))
    with db.scope() as s:
        out = gate.decide(s, deps, owner, action["id"], gate.APPROVE)
    assert out["status"] == gate.STATUS_FAILED and "Ad Clone is not installed" in out["error"]


def test_publish_always_needs_approval(db, owner, ready):
    deps, space_id, sid = ready
    connect_account(db, owner, "tiktok")
    with db.scope() as s:
        library.add_item(s, user_id=owner, space_id=space_id, action_id=None, kind="video", ref="job-1",
                         title="Launch video")
    action = _action_from(_say(db, deps, owner, sid, "publish my latest video to TikTok"))
    assert action["status"] == gate.STATUS_PENDING
    assert action["kind"] == gate.KIND_PUBLISH and deps.publisher.calls == []
    with db.scope() as s:
        gate.decide(s, deps, owner, action["id"], gate.APPROVE)
    assert len(deps.publisher.calls) == 1


def test_gate_rejects_unknown_kinds(db, owner, ready):
    deps, space_id, sid = ready
    with db.scope() as s, pytest.raises(gate.GateError):
        gate.propose(s, owner, space_id, sid, kind="wire_money", title="x", payload={})


def test_every_spending_or_publishing_kind_is_gated():
    assert gate.GATED_KINDS == {gate.KIND_IMAGE, gate.KIND_VIDEO, gate.KIND_CLONE, gate.KIND_PUBLISH,
                                gate.KIND_ROUTINE_BATCH}


# --------------------------------------------------------------------------- #
# Routines
# --------------------------------------------------------------------------- #
def test_parse_weekly_routine_text():
    rule = routines.parse_schedule("3 new ad variations every Monday")
    assert rule == {"count": 3, "weekday": 0, "hour": 9, "skill": "ad_variations"}
    assert routines.parse_schedule("5 hook variations every friday at 14:00")["hour"] == 14
    assert routines.parse_schedule("daily 2 ugc scripts")["weekday"] is None
    assert routines.parse_schedule("hello there") is None


def test_next_run_is_the_next_matching_slot():
    monday = routines.next_run(weekday=0, hour=9, after=T0)  # T0 = Tuesday 12:00 UTC
    assert monday == datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
    daily = routines.next_run(weekday=None, hour=9, after=T0)
    assert daily == datetime(2026, 10, 7, 9, 0, tzinfo=UTC)


def test_chat_schedules_a_routine(db, owner, ready):
    deps, space_id, sid = ready
    out = _say(db, deps, owner, sid, "Make 3 new ad variations every Monday")
    routine = out[-1]["card"]["data"]
    assert routine["count"] == 3 and routine["weekday"] == 0
    assert routine["next_run_at"].startswith("2026-10-12T09:00")
    assert "approve" in out[-1]["content"].lower()
    assert deps.generation.calls == []


def test_beat_tick_creates_pending_actions_only_once(db, owner, ready):
    deps, space_id, sid = ready
    with db.scope() as s:
        r = routines.create(s, owner, space_id, name="Monday variations", skill="ad_variations", count=3,
                            weekday=0, hour=9, now=T0)
    due = datetime(2026, 10, 12, 9, 5, tzinfo=UTC)
    with db.scope() as s:
        assert routines.run_due(s, now=due) == 1
    with db.scope() as s:
        assert routines.run_due(s, now=due) == 0  # already advanced
        actions = s.query(AgentAction).filter_by(kind=gate.KIND_ROUTINE_BATCH).all()
        row = s.get(AgentRoutine, r["id"])
        assert len(actions) == 1 and actions[0].status == gate.STATUS_PENDING
        assert actions[0].payload["count"] == 3
        assert row.next_run_at.replace(tzinfo=UTC) == datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
    assert deps.generation.calls == []


def test_approved_routine_batch_generates_count_variations(db, owner, ready):
    deps, space_id, sid = ready
    with db.scope() as s:
        routines.create(s, owner, space_id, name="Mon", skill="ad_variations", count=3, weekday=0, hour=9, now=T0)
    with db.scope() as s:
        routines.run_due(s, now=T0 + timedelta(days=7))
    with db.scope() as s:
        action = s.query(AgentAction).filter_by(kind=gate.KIND_ROUTINE_BATCH).one()
        gate.decide(s, deps, owner, action.id, gate.APPROVE)
    assert len(deps.generation.calls) == 3


def test_disabled_routines_do_not_run(db, owner, ready):
    deps, space_id, _ = ready
    with db.scope() as s:
        r = routines.create(s, owner, space_id, name="x", skill="ad_variations", count=1, weekday=None, hour=9,
                            now=T0)
        routines.update(s, owner, r["id"], enabled=False)
    with db.scope() as s:
        assert routines.run_due(s, now=T0 + timedelta(days=3)) == 0


def test_routine_validation():
    with pytest.raises(routines.RoutineError):
        routines.validate(count=0, hour=9, weekday=0, skill="ad_variations")
    with pytest.raises(routines.RoutineError):
        routines.validate(count=3, hour=24, weekday=0, skill="ad_variations")
    with pytest.raises(routines.RoutineError):
        routines.validate(count=3, hour=9, weekday=0, skill="mine_bitcoin")


def test_beat_schedule_is_exposed():
    from app.domains.brand_agent import tasks

    entry = tasks.BEAT_SCHEDULE["brand-agent-routines"]
    assert entry["task"] == "app.domains.brand_agent.tasks.brand_agent_routines_tick"


def test_inspiration_link_from_chat_feeds_clone(db, owner, ready):
    deps, space_id, sid = ready
    out = _say(db, deps, owner, sid, "save this as inspiration https://www.tiktok.com/@x/video/42")
    assert "Inspirations" in out[-1]["content"]
    from app.domains.brand_agent import inspirations

    with db.scope() as s:
        items = inspirations.list_items(s, owner, space_id)
    assert items[0]["url"] == "https://www.tiktok.com/@x/video/42" and items[0]["kind"] == "tiktok"


def test_fake_generation_type_is_used():
    assert isinstance(make_deps().generation, FakeGeneration)
    assert isinstance(make_deps().ad_clone, FakeAdClone)
