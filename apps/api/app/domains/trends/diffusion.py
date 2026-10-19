"""Deterministic expected-reach forecast over an independent-cascade graph.

The model is a planning instrument, not a claim about platform algorithms. Each
edge probability is a user-owned assumption. At every step, only newly active
source probability can activate a target; already-active probability remains
absorbing. This avoids counting the same audience exposure on every round.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import prod


@dataclass(frozen=True)
class DiffusionNode:
    node_id: str
    audience_size: int
    label: str = ""


@dataclass(frozen=True)
class DiffusionEdge:
    source: str
    target: str
    probability: float


def forecast_diffusion(
    nodes: tuple[DiffusionNode, ...],
    edges: tuple[DiffusionEdge, ...],
    seeds: tuple[str, ...],
    *,
    steps: int = 6,
) -> dict:
    node_map = {node.node_id: node for node in nodes}
    if not node_map:
        raise ValueError("at least one node is required")
    if len(node_map) != len(nodes):
        raise ValueError("node ids must be unique")
    if any(node.audience_size < 0 for node in nodes):
        raise ValueError("audience sizes cannot be negative")
    if any(seed not in node_map for seed in seeds):
        raise ValueError("every seed must reference a node")
    if any(edge.source not in node_map or edge.target not in node_map for edge in edges):
        raise ValueError("every edge must reference known nodes")
    if any(not 0 <= edge.probability <= 1 for edge in edges):
        raise ValueError("edge probabilities must be between 0 and 1")

    horizon = max(1, min(int(steps), 20))
    incoming: dict[str, list[DiffusionEdge]] = {node_id: [] for node_id in node_map}
    for edge in edges:
        incoming[edge.target].append(edge)

    active = {node_id: (1.0 if node_id in seeds else 0.0) for node_id in node_map}
    newly_active = dict(active)
    timeline = [_snapshot(0, nodes, active)]

    for step in range(1, horizon + 1):
        next_new: dict[str, float] = {}
        for node_id in node_map:
            attempts = [
                newly_active[edge.source] * edge.probability
                for edge in incoming[node_id]
            ]
            activation = (1.0 - active[node_id]) * (
                1.0 - prod(1.0 - attempt for attempt in attempts)
            ) if attempts else 0.0
            next_new[node_id] = max(0.0, min(1.0 - active[node_id], activation))
        for node_id, addition in next_new.items():
            active[node_id] = min(1.0, active[node_id] + addition)
        newly_active = next_new
        timeline.append(_snapshot(step, nodes, active))

    total_audience = sum(node.audience_size for node in nodes)
    expected_reach = timeline[-1]["expected_reach"]
    return {
        "model": "independent-cascade-mean-field-v1",
        "steps": horizon,
        "total_audience": total_audience,
        "expected_reach": expected_reach,
        "adoption_fraction": round(expected_reach / total_audience, 6) if total_audience else 0.0,
        "timeline": timeline,
        "assumption_notice": "Forecast uses the submitted audience sizes and edge probabilities; it is not observed platform reach.",
    }


def _snapshot(step: int, nodes: tuple[DiffusionNode, ...], active: dict[str, float]) -> dict:
    segments = [
        {
            "node_id": node.node_id,
            "label": node.label or node.node_id,
            "activation_probability": round(active[node.node_id], 6),
            "expected_reach": round(active[node.node_id] * node.audience_size),
        }
        for node in nodes
    ]
    return {
        "step": step,
        "expected_reach": sum(segment["expected_reach"] for segment in segments),
        "segments": segments,
    }
