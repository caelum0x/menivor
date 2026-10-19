"""Swipe-to-approve: creatives feed the approvals feed; approve / reject / regenerate with reason chips."""

from __future__ import annotations

import pytest

from app.domains.approvals import service as approvals
from app.domains.brand_agent import gate, library, spaces
from app.domains.brand_agent.models import AgentAction
from app.domains.creative_review import router as review_router
from app.domains.creative_review import service
from app.domains.creative_review.models import CreativeReview
from tests.reelforge._wave2_support import H, OTHER, client_for, data, make_env


@pytest.fixture()
def env(monkeypatch):
    env = make_env(monkeypatch)
    monkeypatch.setattr(approvals, "_publishing_open", lambda: True)
    with env.db.scope() as s:
        space = spaces.ensure_default(s, env.uid)
        env.space_id = space.id
        env.image = library.add_item(s, user_id=env.uid, space_id=space.id, action_id=None, kind="image",
                                     ref="media-1", url="https://cdn.test/1.png", title="Summer hook A")["id"]
        env.video = library.add_item(s, user_id=env.uid, space_id=space.id, action_id=None, kind="video",
                                     ref="media-2", url="https://cdn.test/2.mp4", title="UGC video B")["id"]
        library.add_item(s, user_id=env.uid, space_id=space.id, action_id=None, kind="clone", ref="plan:x",
                         title="A clone plan")
    return env


def _queue(env):
    return service.queue(env.uid)


def _item_for(env, library_id):
    return next(i for i in _queue(env)["items"] if i["external_ref"] == library_id)


def test_generated_images_and_videos_enter_the_approvals_feed(env):
    q = _queue(env)
    refs = {i["external_ref"] for i in q["items"]}
    assert refs == {env.image, env.video}  # clone plans are not creatives
    first = _item_for(env, env.video)
    assert first["source"] == "creative_review" and first["risk"] == "low"
    assert first["payload"]["media_url"] == "https://cdn.test/2.mp4"
    assert first["payload"]["regenerate_credits"] == gate.CREDIT_ESTIMATES[gate.KIND_VIDEO]
    assert [c["id"] for c in q["reasons"]["approve"]] == ["on_brand", "strong_hook", "ready_to_post"]
    # The same items are in the general approvals feed (Rally hub reads it).
    feed = approvals.list_items(env.uid, source="creative_review")
    assert feed["pending_by_source"]["creative_review"] == 2


def test_approve_with_reason_is_recorded_and_idempotent(env):
    item = _item_for(env, env.image)
    out = service.decide(env.uid, item["id"], "approve", reason="on_brand")
    assert out["item"]["status"] == "executed" and out["review"]["status"] == "approved"
    assert out["review"]["reason_label"] == "On brand"
    again = service.decide(env.uid, item["id"], "approve", reason="on_brand")
    assert again["idempotent"] is True
    assert {i["external_ref"] for i in _queue(env)["items"]} == {env.video}
    stats = service.stats(env.uid)
    assert stats["by_status"]["approved"] == 1 and stats["top_reasons"][0]["id"] == "on_brand"


def test_reject_needs_a_fix_chip_and_never_spends(env):
    item = _item_for(env, env.image)
    with pytest.raises(service.ReviewError):
        service.decide(env.uid, item["id"], "reject", reason="on_brand")  # approve chip on reject
    out = service.decide(env.uid, item["id"], "reject", reason="weak_hook", note="hook is slow")
    assert out["review"]["status"] == "rejected" and out["regenerate_action"] is None
    with env.db.scope() as s:
        assert s.query(AgentAction).count() == 0
    with pytest.raises(service.ReviewError) as err:
        service.decide(env.uid, item["id"], "approve")
    assert err.value.status_code == 409


def test_regenerate_without_confirm_only_queues_a_pending_action(env):
    item = _item_for(env, env.video)
    with pytest.raises(service.ReviewError):
        service.decide(env.uid, item["id"], "regenerate")  # a reason is required
    out = service.decide(env.uid, item["id"], "regenerate", reason="too_long", deps_factory=lambda: env.deps)
    action = out["regenerate_action"]
    assert action["status"] == "pending" and action["kind"] == gate.KIND_VIDEO
    assert "Make it shorter and tighter" in action["payload"]["prompt"]
    assert env.deps.generation.calls == []  # nothing generated, nothing spent
    assert out["review"]["status"] == "regenerated"


def test_regenerate_with_confirm_runs_once(env):
    item = _item_for(env, env.image)
    out = service.decide(env.uid, item["id"], "regenerate", reason="off_brand", confirm_spend=True,
                         deps_factory=lambda: env.deps)
    assert out["regenerate_action"]["status"] == "executed"
    assert len(env.deps.generation.calls) == 1
    again = service.decide(env.uid, item["id"], "regenerate", reason="off_brand", confirm_spend=True,
                           deps_factory=lambda: env.deps)
    assert again["regenerate_action"]["id"] == out["regenerate_action"]["id"]
    assert len(env.deps.generation.calls) == 1  # a repeated tap never pays twice
    # The regenerated creative is new library item -> it shows up in the queue for review.
    assert len(_queue(env)["items"]) == 2


def test_other_users_cannot_decide(env):
    item = _item_for(env, env.image)
    with pytest.raises(service.ReviewError) as err:
        service.decide(env.other, item["id"], "approve")
    assert err.value.status_code == 404
    with env.db.scope() as s:
        assert s.query(CreativeReview).filter_by(status="approved").count() == 0


def test_http_queue_and_decide(env, monkeypatch):
    monkeypatch.setattr(review_router, "build_deps", lambda: env.deps)
    client = client_for(review_router, monkeypatch=monkeypatch, db=env.db)
    q = data(client.get("/api/v1/review/queue", headers=H))
    assert q["pending"] == 2
    item_id = q["items"][0]["id"]
    out = data(client.post(f"/api/v1/review/{item_id}/decide", headers=H,
                           json={"decision": "approve", "reason": "ready_to_post"}))
    assert out["review"]["status"] == "approved"
    bad = client.post(f"/api/v1/review/{item_id}/decide", headers=H, json={"decision": "ship"})
    assert bad.status_code == 422
    assert client.post(f"/api/v1/review/{item_id}/decide", headers=OTHER,
                       json={"decision": "approve"}).status_code == 404
    assert data(client.get("/api/v1/review/queue", headers=OTHER))["pending"] == 0
