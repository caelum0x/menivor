"""Workflow canvas: graph rules, runs that only queue approvals, publish after approve, beat schedule."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domains.brand_agent import gate
from app.domains.brand_agent.models import AgentAction
from app.domains.workflows import graph as graphs
from app.domains.workflows import router as workflows_router
from app.domains.workflows import service
from tests.reelforge._wave2_support import H, OTHER, client_for, data, make_env

T0 = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)  # a Tuesday


def _g(types, edges):
    return {"nodes": [{"id": f"n{i}", "type": t, "position": {"x": i * 100, "y": 0}} for i, t in enumerate(types)],
            "edges": [{"source": f"n{a}", "target": f"n{b}"} for a, b in edges]}


def test_starter_is_the_full_chain_in_order():
    chain = [n["type"] for n in graphs.order(graphs.starter())]
    assert chain == ["brief", "script", "images", "video", "captions", "approve", "publish"]


@pytest.mark.parametrize("graph,message", [
    (_g(["script"], []), "exactly one Brief"),
    (_g(["brief", "brief"], []), "exactly one Brief"),
    (_g(["brief", "script", "approve"], [(0, 1), (1, 2), (2, 1)]), "loops"),
    (_g(["brief", "video", "publish"], [(0, 1), (1, 2)]), "Approve before"),
    (_g(["brief", "images", "captions"], [(0, 1), (1, 2)]), "after a Video"),
    (_g(["brief", "approve"], [(0, 1)]), "something to approve"),
    (_g(["brief", "script", "video"], [(0, 1)]), "Connect every step"),
    (_g(["brief", "magic"], [(0, 1)]), "Unknown step"),
    (_g(["brief", "script"], [(1, 0)]), "before the Brief"),
])
def test_graph_rules(graph, message):
    with pytest.raises(graphs.GraphError) as err:
        graphs.normalize(graph)
    assert message in err.value.message


def test_node_data_is_clamped():
    g = graphs.normalize(_g(["brief", "images", "approve", "publish"], [(0, 1), (1, 2), (2, 3)]))
    g["nodes"][1]["data"] = {"count": 99}
    assert graphs.normalize(g)["nodes"][1]["data"]["count"] == graphs.MAX_COUNT


@pytest.fixture()
def env(monkeypatch):
    return make_env(monkeypatch)


def test_run_queues_pending_actions_and_spends_nothing(env):
    with env.db.scope() as s:
        wf = service.create(s, env.uid, name="Weekly UGC")
        run = service.run(s, env.uid, wf["id"])
        assert run["status"] == "waiting_for_approval"
        by_type = {st["type"]: st for st in run["steps"]}
        assert by_type["brief"]["status"] == "done" and by_type["script"]["status"] == "done"
        assert by_type["images"]["status"] == "pending_approval" and by_type["video"]["status"] == "pending_approval"
        assert by_type["publish"]["status"] == "after_approval"
        video_action = s.get(AgentAction, by_type["video"]["action_id"])
        assert video_action.status == "pending" and video_action.payload["options"]["captions"] == "clean"
        assert s.query(AgentAction).filter_by(kind=gate.KIND_PUBLISH).count() == 0
    assert env.deps.generation.calls == []


def test_publish_is_proposed_only_after_every_approval(env):
    with env.db.scope() as s:
        wf = service.create(s, env.uid, name="Weekly UGC")
        run = service.run(s, env.uid, wf["id"])
        spend = [st["action_id"] for st in run["steps"] if st.get("action_id")]
        gate.decide(s, env.deps, env.uid, spend[0], gate.APPROVE)
        assert service.advance(s, env.uid, run["id"])["status"] == "waiting_for_approval"
        gate.decide(s, env.deps, env.uid, spend[1], gate.APPROVE)
        out = service.advance(s, env.uid, run["id"])
        assert out["status"] == "publish_pending"
        publish = next(st for st in out["steps"] if st["type"] == "publish")
        action = s.get(AgentAction, publish["action_id"])
        assert action.kind == gate.KIND_PUBLISH and action.status == "pending"
        assert action.payload["job_id"].startswith("media-")
    assert len(env.deps.publisher.calls) == 0  # proposing never publishes


def test_a_rejected_step_stops_the_run(env):
    with env.db.scope() as s:
        wf = service.create(s, env.uid, name="One image")
        g = graphs.normalize(_g(["brief", "images", "approve", "publish"], [(0, 1), (1, 2), (2, 3)]))
        service.save(s, env.uid, wf["id"], graph=g)
        run = service.run(s, env.uid, wf["id"])
        gate.decide(s, env.deps, env.uid, run["steps"][1]["action_id"], gate.REJECT)
        out = service.advance(s, env.uid, run["id"])
    assert out["status"] == "failed" and "nothing was published" in out["error"]


def test_schedule_runs_through_the_beat_once(env):
    with env.db.scope() as s:
        wf = service.create(s, env.uid, name="Mondays")
        sched = service.set_schedule(s, env.uid, wf["id"], enabled=True, weekday=0, hour=9, now=T0)
        assert sched["schedule"]["next_run_at"].startswith("2026-10-12T09:00")
        assert "Monday" in sched["schedule"]["label"]
        assert service.run_due(s, now=T0) == 0
        monday = T0 + timedelta(days=6, hours=-2)
        assert service.run_due(s, now=monday) == 1
        assert service.run_due(s, now=monday) == 0  # the same slot never runs twice
        assert len(service.list_runs(s, env.uid, wf["id"])) == 1
        assert service.list_runs(s, env.uid, wf["id"])[0]["trigger"] == "schedule"


def test_http_canvas_round_trip(env, monkeypatch):
    client = client_for(workflows_router, monkeypatch=monkeypatch, db=env.db)
    listing = data(client.get("/api/v1/workflows", headers=H))
    assert [n["type"] for n in listing["node_types"]][0] == "brief" and listing["starter"]["nodes"]
    wf = data(client.post("/api/v1/workflows", headers=H, json={"name": "Canvas"}))["workflow"]
    bad = client.put(f"/api/v1/workflows/{wf['id']}", headers=H,
                     json={"graph": _g(["brief", "video", "publish"], [(0, 1), (1, 2)])})
    assert bad.status_code == 422 and "Approve" in bad.json()["message"]
    run = data(client.post(f"/api/v1/workflows/{wf['id']}/run", headers=H))["run"]
    assert run["status"] == "waiting_for_approval"
    detail = data(client.get(f"/api/v1/workflows/{wf['id']}", headers=H))
    assert detail["runs"][0]["id"] == run["id"]
    sched = data(client.put(f"/api/v1/workflows/{wf['id']}/schedule", headers=H,
                            json={"enabled": True, "weekday": 4, "hour": 15}))
    assert sched["workflow"]["schedule"]["enabled"] is True
    assert client.get(f"/api/v1/workflows/{wf['id']}", headers=OTHER).status_code == 404
