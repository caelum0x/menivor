"""P6 event/outbox bus + job-DAG runner."""

from __future__ import annotations

import pytest

from app.events import (
    JOB_COMPLETED,
    Dag,
    DagError,
    Event,
    EventBus,
    Outbox,
    ready_nodes,
    run_dag,
)
from app.events import dag as dagmod


# --------------------------------------------------------------------------- #
# EventBus
# --------------------------------------------------------------------------- #
def test_bus_routes_by_type_and_isolates_failures():
    bus = EventBus()
    seen = []

    @bus.on(JOB_COMPLETED)
    def good(ev):
        seen.append(ev.key)

    @bus.on(JOB_COMPLETED)
    def bad(ev):
        raise RuntimeError("handler boom")

    failures = bus.emit(Event(type=JOB_COMPLETED, key="job1"))
    assert seen == ["job1"]  # good handler still ran
    assert len(failures) == 1 and failures[0].handler == "bad"


def test_bus_only_delivers_subscribed_type():
    bus = EventBus()
    hits = []
    bus.subscribe("a", lambda ev: hits.append(ev.type))
    bus.emit(Event(type="b", key="k"))
    assert hits == []


# --------------------------------------------------------------------------- #
# Outbox — at-least-once + idempotent
# --------------------------------------------------------------------------- #
def test_outbox_stage_assigns_idempotency_key():
    box = Outbox()
    e = box.stage(Event(type=JOB_COMPLETED, key="j"))
    assert e.idempotency_key.startswith("job.completed:j:")
    assert len(box.pending) == 1


def test_outbox_drains_once_and_never_redelivers():
    bus = EventBus()
    delivered = []
    bus.subscribe(JOB_COMPLETED, lambda ev: delivered.append(ev.idempotency_key))
    box = Outbox()
    box.stage(Event(type=JOB_COMPLETED, key="j1"))
    box.stage(Event(type=JOB_COMPLETED, key="j2"))
    box.drain(bus)
    assert len(delivered) == 2
    # A second drain delivers nothing (already delivered) and clears pending.
    box.drain(bus)
    assert len(delivered) == 2
    assert box.pending == ()


def test_outbox_keeps_failed_event_for_retry():
    bus = EventBus()
    calls = {"n": 0}

    def flaky(ev):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")

    bus.subscribe(JOB_COMPLETED, flaky)
    box = Outbox()
    box.stage(Event(type=JOB_COMPLETED, key="j"))
    failures = box.drain(bus)
    assert failures and len(box.pending) == 1  # kept for retry
    # Second drain succeeds and clears it.
    assert box.drain(bus) == []
    assert box.pending == ()


# --------------------------------------------------------------------------- #
# DAG runner
# --------------------------------------------------------------------------- #
def _reel_dag() -> Dag:
    # script -> tts -> {avatar, captions} -> compose -> upload
    return (
        Dag()
        .add("script")
        .add("tts", ["script"])
        .add("avatar", ["tts"])
        .add("captions", ["tts"])
        .add("compose", ["avatar", "captions"])
        .add("upload", ["compose"])
    )


def test_topo_order_respects_dependencies():
    order = _reel_dag().topo_order()
    assert order.index("script") < order.index("tts") < order.index("compose")
    assert order.index("avatar") < order.index("compose")
    assert order.index("compose") < order.index("upload")


def test_run_dag_all_success():
    ran = []
    states = run_dag(_reel_dag(), lambda nid: ran.append(nid) or nid)
    assert all(s.status == dagmod.COMPLETED for s in states.values())
    assert ran.index("tts") > ran.index("script")


def test_run_dag_failure_skips_dependents():
    def executor(nid):
        if nid == "tts":
            raise RuntimeError("tts died")
        return nid

    states = run_dag(_reel_dag(), executor)
    assert states["script"].status == dagmod.COMPLETED
    assert states["tts"].status == dagmod.FAILED
    # Everything downstream of tts is skipped, not run on stale input.
    for nid in ("avatar", "captions", "compose", "upload"):
        assert states[nid].status == dagmod.SKIPPED


def test_ready_nodes_fanout_set():
    dag = _reel_dag()
    states = {nid: dagmod.NodeState(id=nid) for nid in dag.nodes}
    assert ready_nodes(dag, states) == ["script"]
    states["script"].status = dagmod.COMPLETED
    states["tts"].status = dagmod.COMPLETED
    # With tts done, avatar + captions are the parallel fan-out set.
    assert ready_nodes(dag, states) == ["avatar", "captions"]


def test_cycle_detected():
    dag = Dag().add("a", ["b"]).add("b", ["a"])
    with pytest.raises(DagError):
        dag.validate()


def test_unknown_dependency_rejected():
    dag = Dag().add("a", ["ghost"])
    with pytest.raises(DagError):
        dag.validate()
