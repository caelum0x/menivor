"""Deterministic job-DAG runner for the reel pipeline.

The reel pipeline is a directed acyclic graph of stages (script → tts → {avatar ∥
captions} → compose → upload; the film pipeline fans out per-shot). This runner
gives a pure, deterministic scheduler over that graph:

* topological order with cycle detection,
* a node runs only after ALL its dependencies COMPLETED,
* a failed node SKIPS its transitive dependents (they never run on stale inputs),
* independent branches are surfaced as "ready sets" the executor can fan out.

No Celery/threads here — the executor callback does the work; this module owns the
ordering, gating, and status bookkeeping so it is fully unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

PENDING = "PENDING"
RUNNING = "RUNNING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
SKIPPED = "SKIPPED"


class DagError(ValueError):
    """An invalid DAG (unknown dependency or a cycle)."""


@dataclass(frozen=True)
class Node:
    """One stage in the DAG."""

    id: str
    deps: tuple[str, ...] = ()


@dataclass
class NodeState:
    """Mutable execution state of a node."""

    id: str
    status: str = PENDING
    result: object = None
    error: str = ""


@dataclass
class Dag:
    """A validated DAG of :class:`Node`s."""

    nodes: dict[str, Node] = field(default_factory=dict)

    def add(self, node_id: str, deps: tuple[str, ...] | list[str] = ()) -> "Dag":
        self.nodes[node_id] = Node(id=node_id, deps=tuple(deps))
        return self

    def validate(self) -> None:
        for node in self.nodes.values():
            for dep in node.deps:
                if dep not in self.nodes:
                    raise DagError(f"node {node.id!r} depends on unknown node {dep!r}")
        self.topo_order()  # raises on cycle

    def topo_order(self) -> list[str]:
        """Kahn topological sort; raises :class:`DagError` on a cycle."""
        indeg = {nid: 0 for nid in self.nodes}
        for node in self.nodes.values():
            for _ in node.deps:
                indeg[node.id] += 1
        # Deterministic: process ready nodes in sorted id order.
        ready = sorted([nid for nid, d in indeg.items() if d == 0])
        order: list[str] = []
        while ready:
            nid = ready.pop(0)
            order.append(nid)
            for other in self.nodes.values():
                if nid in other.deps:
                    indeg[other.id] -= 1
                    if indeg[other.id] == 0:
                        ready.append(other.id)
            ready.sort()
        if len(order) != len(self.nodes):
            raise DagError("cycle detected in DAG")
        return order


def run_dag(dag: Dag, executor: Callable[[str], object]) -> dict[str, NodeState]:
    """Execute ``dag`` in dependency order, gating + skipping on failure.

    ``executor(node_id)`` performs the stage and returns its result, or raises to
    mark the node FAILED. A node whose any dependency FAILED/SKIPPED is SKIPPED
    (its transitive dependents too). Returns the final state of every node.
    """
    dag.validate()
    states: dict[str, NodeState] = {nid: NodeState(id=nid) for nid in dag.nodes}

    for nid in dag.topo_order():
        node = dag.nodes[nid]
        blocked = [d for d in node.deps if states[d].status in (FAILED, SKIPPED)]
        if blocked:
            states[nid].status = SKIPPED
            states[nid].error = f"skipped: upstream {blocked} did not complete"
            continue
        states[nid].status = RUNNING
        try:
            states[nid].result = executor(nid)
            states[nid].status = COMPLETED
        except Exception as exc:  # noqa: BLE001 - failure is a first-class outcome
            states[nid].status = FAILED
            states[nid].error = str(exc)
    return states


def ready_nodes(dag: Dag, states: dict[str, NodeState]) -> list[str]:
    """Nodes whose deps are all COMPLETED and which are still PENDING (fan-out set)."""
    out: list[str] = []
    for nid, node in dag.nodes.items():
        if states[nid].status != PENDING:
            continue
        if all(states[d].status == COMPLETED for d in node.deps):
            out.append(nid)
    return sorted(out)
