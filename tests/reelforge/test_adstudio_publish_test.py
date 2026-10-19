"""Ad Studio "Publish and test": carriers, experiment, loop, results, remake."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.adstudio import publish_gate, publish_results, publish_test
from app.domains.adstudio.models import AdStudioProject, AdVariant
from app.domains.adstudio.repository import AdStudioRepository
from app.domains.adstudio.service import AdStudioError
from app.domains.insights.winner_loop_service import find_anchor
from app.domains.insights.winner_loop_state import read_state, write_state
from app.domains.publishing.experiment_repo import ExperimentRepository
from app.models.const import TASK_STATE_COMPLETE
from app.models.db import experiments, models  # noqa: F401 - register tables
from app.models.db.base import Base
from app.models.db.models import Job, ScheduledPublish, User

USER = "u1"
PROJECT = "p" * 32


def _angle(aid: str, kind: str, hook: str) -> dict:
    return {"id": aid, "kind": kind, "label": kind.title(), "hook": hook, "pain": "Pain.", "proof": "",
            "offer": "Now 20% off.", "cta": "Tap to shop.", "benefits": [], "script": f"{hook} Pain.", "source": "template"}


@pytest.fixture()
def factory(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with Factory.begin() as s:
        s.add(User(id=USER, email="u1@x.com"))
        s.add(User(id="u2", email="u2@x.com"))
        angles = [_angle("a1", "offer", "Stop wasting money."), _angle("a2", "demo", "Watch this in action.")]
        s.add(AdStudioProject(id=PROJECT, user_id=USER, title="Blender", source_url="https://shop.example/blender",
                              language="en", product={"title": "Blender"}, angles=angles, images=[]))
        s.flush()
        for vid, angle, status in (("v1", angles[0], "done"), ("v2", angles[1], "done"), ("v3", angles[1], "rendering")):
            s.add(AdVariant(id=vid, project_id=PROJECT, user_id=USER, angle_id=angle["id"], format="showcase",
                            aspect="9:16", status=status, script=angle["script"], spec={"angle": angle},
                            output_key=f"uploads/{vid}.mp4" if status == "done" else "", duration_ms=15000))

    @contextmanager
    def fake_get_session():
        with Factory.begin() as s:
            yield s

    monkeypatch.setattr("app.models.db.base.get_session", fake_get_session)
    monkeypatch.setattr("app.domains.insights.winner_loop_service._record", lambda *a, **k: None)
    return Factory


def _open_publishing(monkeypatch, *, pro: str = "active") -> None:
    monkeypatch.setattr(publish_test, "launch_state", lambda: {"enabled": True, "mode": "public", "pilot": False, "reason": ""})
    monkeypatch.setattr(publish_test, "pro_state", lambda user_id: {"status": pro, "reason": f"pro {pro}"})
    monkeypatch.setattr("app.domains.publishing.native_service.require_native_connections", lambda user_id, platforms: None)
    monkeypatch.setattr("app.domains.insights.winner_loop_service._publishing_open", lambda: True)


# --------------------------------------------------------------------------- #
# Start
# --------------------------------------------------------------------------- #
def test_manual_test_creates_carriers_experiment_and_zero_cap_loop(factory) -> None:
    out = publish_test.start_test(USER, PROJECT, variant_ids=[], mode="manual", platforms=[])
    batch = out["batch_id"]

    with factory.begin() as s:
        carriers = s.query(Job).filter(Job.batch_id == batch).all()
        assert {c.kind for c in carriers} == {"ad_variant"}
        assert {c.state for c in carriers} == {TASK_STATE_COMPLETE}
        assert {c.result_key for c in carriers} == {"uploads/v1.mp4", "uploads/v2.mp4"}
        meta = carriers[0].params["social_metadata"]
        assert "https://shop.example/blender" in meta["caption"]
        exp = ExperimentRepository(s).get_by_key(f"run:{batch}")
        assert exp is not None and len(ExperimentRepository(s).variants(exp.id)) == 2
        state = read_state(find_anchor(s, batch, USER))
        assert state["mode"] == "manual" and state["platforms"] == []
        assert state["spend_cap_credits"] == 0  # the reel remake can never spend credits here
        assert state["status"] == "waiting_for_posts"
        tested = {v.id: publish_test.test_of(v) for v in AdStudioRepository(s).variants(PROJECT)}
        assert tested["v1"]["batch_id"] == batch and tested["v3"] == {}


def test_publish_is_refused_while_publishing_is_closed(factory, monkeypatch) -> None:
    monkeypatch.setattr(publish_test, "launch_state", lambda: {"enabled": False, "mode": "internal_pilot", "pilot": True, "reason": "beta"})
    with pytest.raises(AdStudioError) as err:
        publish_test.start_test(USER, PROJECT, variant_ids=[], mode="publish", platforms=["tiktok"])
    assert err.value.status_code == 403
    with factory.begin() as s:
        assert s.query(Job).count() == 0


def test_publish_needs_pro(factory, monkeypatch) -> None:
    _open_publishing(monkeypatch, pro="required")
    with pytest.raises(AdStudioError) as err:
        publish_test.start_test(USER, PROJECT, variant_ids=[], mode="publish", platforms=["tiktok"])
    assert err.value.status_code == 402


def test_publish_queues_spaced_posts_on_every_platform(factory, monkeypatch) -> None:
    _open_publishing(monkeypatch)
    out = publish_test.start_test(USER, PROJECT, variant_ids=["v1", "v2"], mode="publish", platforms=["tiktok", "youtube"])
    with factory.begin() as s:
        rows = s.query(ScheduledPublish).all()
        assert len(rows) == 4
        assert {tuple(r.platforms) for r in rows} == {("tiktok",), ("youtube_shorts",)}
        tiktok = sorted(r.scheduled_at for r in rows if r.platforms == ["tiktok"])
        assert tiktok[1] - tiktok[0] >= timedelta(hours=3)  # min gap respected
        state = read_state(find_anchor(s, out["batch_id"], USER))
        assert state["status"] == "publishing"


def test_needs_two_finished_untested_ads(factory) -> None:
    publish_test.start_test(USER, PROJECT, variant_ids=[], mode="manual", platforms=[])
    with pytest.raises(AdStudioError) as err:
        publish_test.start_test(USER, PROJECT, variant_ids=[], mode="manual", platforms=[])
    assert err.value.status_code == 422
    with pytest.raises(AdStudioError) as err:
        publish_test.start_test(USER, PROJECT, variant_ids=["v1", "v2"], mode="manual", platforms=[])
    assert err.value.status_code == 409


def test_foreign_project_is_not_found(factory) -> None:
    with pytest.raises(AdStudioError) as err:
        publish_test.start_test("u2", PROJECT, variant_ids=[], mode="manual", platforms=[])
    assert err.value.status_code == 404


# --------------------------------------------------------------------------- #
# Results + remake
# --------------------------------------------------------------------------- #
def _declare_winner(factory, batch: str, *, conclusive: bool = True) -> str:
    with factory.begin() as s:
        anchor = find_anchor(s, batch, USER)
        carriers = {c.params["adstudio"]["variant_id"]: c.id for c in s.query(Job).filter(Job.batch_id == batch)}
        state = read_state(anchor)
        write_state(anchor, {
            **state, "status": "winner_ready", "winner_job_id": carriers["v2"], "conclusive": conclusive,
            "variants": [
                {"job_id": carriers["v1"], "views": 300, "engagement_rate": 0.02, "avg_watch_frac": 0.3,
                 "completion_rate": None, "source": "platform"},
                {"job_id": carriers["v2"], "views": 900, "engagement_rate": 0.05, "avg_watch_frac": 0.6,
                 "completion_rate": None, "source": "platform"},
            ],
            "ranking": {"ranked": [{"job_id": carriers["v2"], "rank": 1, "score": 0.8},
                                   {"job_id": carriers["v1"], "rank": 2, "score": 0.4}]},
            "explanation": {"headline": "The demo ad won.", "reasons": [{"text": "900 views vs 300"}],
                            "caveats": [], "confidence": "high"},
        })
        return carriers["v2"]


def test_results_map_the_loop_back_to_ads(factory) -> None:
    batch = publish_test.start_test(USER, PROJECT, variant_ids=[], mode="manual", platforms=[])["batch_id"]
    _declare_winner(factory, batch)
    with factory.begin() as s:
        tests = publish_results.project_tests(s, USER, AdStudioRepository(s).variants(PROJECT), lambda key: None)
    assert len(tests) == 1
    test = tests[0]
    assert test["winner_variant_id"] == "v2" and test["can_remake"] is True
    assert [a["variant_id"] for a in test["ads"]] == ["v2", "v1"]
    assert test["ads"][0]["metrics"]["views"] == 900
    assert test["ads"][0]["metrics"]["completion_rate"] is None  # not measured stays None
    assert test["explanation"]["headline"] == "The demo ad won."


def test_remake_winner_renders_new_hooks_once(factory, monkeypatch) -> None:
    monkeypatch.setattr("app.domains.insights.remake.hook_variants",
                        lambda hook, topic, language, count: ["See it blend.", "One button, done.", "Try this."])
    batch = publish_test.start_test(USER, PROJECT, variant_ids=[], mode="manual", platforms=[])["batch_id"]
    _declare_winner(factory, batch)

    out = publish_test.remake_winner(USER, PROJECT, batch, accept_low_confidence=False)
    assert len(out["variant_ids"]) == 3 and out["replayed"] is False
    with factory.begin() as s:
        new = [s.get(AdVariant, vid) for vid in out["variant_ids"]]
        assert {v.status for v in new} == {"queued"}
        assert {v.angle_id for v in new} == {"a2"} and {v.format for v in new} == {"showcase"}
        assert new[0].spec["angle"]["hook"] == "See it blend."
        assert new[0].spec["angle"]["script"].startswith("See it blend.")
        assert new[0].spec["remake_of"]["variant_id"] == "v2"
        assert read_state(find_anchor(s, batch, USER))["status"] == "remade"

    again = publish_test.remake_winner(USER, PROJECT, batch, accept_low_confidence=False)
    assert again["replayed"] is True and again["variant_ids"] == out["variant_ids"]


def test_low_confidence_remake_needs_confirmation(factory, monkeypatch) -> None:
    monkeypatch.setattr("app.domains.insights.remake.hook_variants", lambda hook, topic, language, count: ["New."])
    batch = publish_test.start_test(USER, PROJECT, variant_ids=[], mode="manual", platforms=[])["batch_id"]
    _declare_winner(factory, batch, conclusive=False)
    with pytest.raises(AdStudioError) as err:
        publish_test.remake_winner(USER, PROJECT, batch, accept_low_confidence=False)
    assert err.value.status_code == 409
    assert len(publish_test.remake_winner(USER, PROJECT, batch, accept_low_confidence=True)["variant_ids"]) == 1


def test_remake_before_a_winner_is_refused(factory) -> None:
    batch = publish_test.start_test(USER, PROJECT, variant_ids=[], mode="manual", platforms=[])["batch_id"]
    with pytest.raises(AdStudioError) as err:
        publish_test.remake_winner(USER, PROJECT, batch, accept_low_confidence=True)
    assert err.value.status_code == 409


# --------------------------------------------------------------------------- #
# Stop / delete / post copy
# --------------------------------------------------------------------------- #
def test_stop_cancels_unposted_posts_and_turns_the_loop_off(factory, monkeypatch) -> None:
    _open_publishing(monkeypatch)
    batch = publish_test.start_test(USER, PROJECT, variant_ids=[], mode="publish", platforms=["tiktok"])["batch_id"]
    assert publish_test.stop_test(USER, PROJECT, batch) == 2
    with factory.begin() as s:
        assert {r.status for r in s.query(ScheduledPublish)} == {"canceled"}
        assert read_state(find_anchor(s, batch, USER))["mode"] == "off"


def test_deleting_the_project_cancels_its_test_posts(factory, monkeypatch) -> None:
    _open_publishing(monkeypatch)
    publish_test.start_test(USER, PROJECT, variant_ids=[], mode="publish", platforms=["instagram"])
    with factory.begin() as s:
        repo = AdStudioRepository(s)
        repo.delete_project(repo.get_owned_project(USER, PROJECT))
    with factory.begin() as s:
        assert {r.status for r in s.query(ScheduledPublish)} == {"canceled"}


def test_scheduled_post_uses_the_ad_caption(factory, monkeypatch) -> None:
    from app.domains.publishing import native_service
    from app.models.db import base as db_base

    monkeypatch.setattr(native_service, "get_session", db_base.get_session)

    batch = publish_test.start_test(USER, PROJECT, variant_ids=[], mode="manual", platforms=[])["batch_id"]
    with factory.begin() as s:
        job_id = s.query(Job).filter(Job.batch_id == batch).first().id
    meta = native_service._social_metadata_for_job(USER, job_id, "tiktok")
    assert meta["caption"].startswith(("Stop wasting money.", "Watch this in action."))
    assert meta["hashtags"] == []


def test_readiness_explains_each_blocker(factory, monkeypatch) -> None:
    monkeypatch.setattr(publish_gate, "launch_state", lambda: {"enabled": False, "mode": "internal_pilot", "pilot": True, "reason": "beta"})
    with factory.begin() as s:
        ready = publish_gate.readiness(s, USER, ad_count=6)
    assert ready["can_publish"] is False and ready["blocker"] == "beta" and ready["can_track_manually"] is True
    tiktok = next(p for p in ready["platforms"] if p["platform"] == "tiktok")
    assert tiktok["connected"] is False and tiktok["daily_cap"] == 4 and tiktok["days_needed"] == 2

    monkeypatch.setattr(publish_gate, "launch_state", lambda: {"enabled": True, "mode": "public", "pilot": False, "reason": ""})
    monkeypatch.setattr(publish_gate, "pro_state", lambda user_id: {"status": "active", "reason": ""})
    with factory.begin() as s:
        ready = publish_gate.readiness(s, USER, ad_count=2)
    assert ready["can_publish"] is False and "Connect" in ready["blocker"]


def test_ui_launch_reason_mentions_manual_path_in_pilot(monkeypatch) -> None:
    monkeypatch.setattr("app.core.launch.policy.launch_mode", lambda: "internal_pilot")
    monkeypatch.setattr("app.core.launch.policy.publishing_enabled", lambda: False)
    state = publish_gate.launch_state()
    assert state["enabled"] is False and state["pilot"] is True and "manual test" in state["reason"]


def test_now_helper_is_timezone_aware() -> None:
    assert publish_test._now().tzinfo is timezone.utc and publish_test._now() <= datetime.now(timezone.utc)
