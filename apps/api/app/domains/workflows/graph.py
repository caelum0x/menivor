"""Workflow graphs: node types, validation and run order (pure; no DB).

A graph is ``{"nodes": [{id, type, position: {x, y}, data}], "edges": [{source, target}]}``
(the React Flow shape). Rules, each with a plain message:

* one ``brief`` node, with nothing before it; every other node is reachable from it;
* no cycles, no self loops, at most 30 nodes;
* ``captions`` comes after a ``video``; ``approve`` comes after something to approve
  (script, images or video); ``publish`` always has an ``approve`` before it.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

NODE_TYPES: dict[str, dict[str, Any]] = {
    "brief": {"label": "Brief", "spends": False, "help": "What to make, grounded in your Brain."},
    "script": {"label": "Script", "spends": False, "help": "Hook and lines written from the brief."},
    "images": {"label": "Images", "spends": True, "help": "Ad images (credits, after approval)."},
    "video": {"label": "Video", "spends": True, "help": "A UGC-style video (credits, after approval)."},
    "captions": {"label": "Captions", "spends": False, "help": "Burned captions on the video."},
    "approve": {"label": "Approve", "spends": False, "help": "Nothing after this runs until you approve."},
    "publish": {"label": "Publish", "spends": False, "help": "Schedule to your connected accounts."},
}
MAX_NODES = 30
MAX_COUNT = 5
PLATFORMS = ("tiktok", "instagram", "youtube_shorts")


class GraphError(ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = 422


def _data(kind: str, raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    if kind == "brief":
        out["request"] = " ".join(str(raw.get("request") or "").split())[:500]
    if kind == "script":
        out["seconds"] = max(10, min(int(raw.get("seconds") or 30), 90))
    if kind in ("images", "video"):
        out["count"] = max(1, min(int(raw.get("count") or 1), MAX_COUNT))
    if kind == "captions":
        out["style"] = "bold" if raw.get("style") == "bold" else "clean"
    if kind == "publish":
        wanted = [p for p in (raw.get("platforms") or ["tiktok"]) if p in PLATFORMS]
        out["platforms"] = wanted or ["tiktok"]
    return out


def normalize(graph: Any) -> dict[str, Any]:
    if not isinstance(graph, dict):
        raise GraphError("The workflow is empty.")
    nodes_in, edges_in = graph.get("nodes") or [], graph.get("edges") or []
    if not nodes_in:
        raise GraphError("Add a Brief to start the workflow.")
    if len(nodes_in) > MAX_NODES:
        raise GraphError(f"A workflow has at most {MAX_NODES} steps.")
    nodes, ids = [], set()
    for n in nodes_in:
        nid, kind = str((n or {}).get("id") or "")[:40], str((n or {}).get("type") or "")
        if not nid or nid in ids:
            raise GraphError("Every step needs its own id.")
        if kind not in NODE_TYPES:
            raise GraphError(f"Unknown step: {kind or 'empty'}.")
        pos = (n or {}).get("position") or {}
        nodes.append({"id": nid, "type": kind, "position": {"x": float(pos.get("x") or 0), "y": float(pos.get("y") or 0)},
                      "data": _data(kind, (n or {}).get("data"))})
        ids.add(nid)
    edges, seen = [], set()
    for e in edges_in:
        src, dst = str((e or {}).get("source") or ""), str((e or {}).get("target") or "")
        if src not in ids or dst not in ids:
            raise GraphError("A connection points at a missing step.")
        if src == dst:
            raise GraphError("A step cannot connect to itself.")
        if (src, dst) not in seen:
            seen.add((src, dst))
            edges.append({"id": f"{src}->{dst}", "source": src, "target": dst})
    out = {"nodes": nodes, "edges": edges}
    order(out)  # raises on any rule
    return out


def _ancestors(graph: dict[str, Any]) -> dict[str, set[str]]:
    parents: dict[str, set[str]] = defaultdict(set)
    for e in graph["edges"]:
        parents[e["target"]].add(e["source"])
    memo: dict[str, set[str]] = {}

    def walk(nid: str) -> set[str]:
        if nid not in memo:
            memo[nid] = set()
            for p in parents[nid]:
                memo[nid] |= {p} | walk(p)
        return memo[nid]

    return {n["id"]: walk(n["id"]) for n in graph["nodes"]}


def order(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Topological order (Kahn). Raises :class:`GraphError` for any broken rule."""
    by_id = {n["id"]: n for n in graph["nodes"]}
    briefs = [n for n in graph["nodes"] if n["type"] == "brief"]
    if len(briefs) != 1:
        raise GraphError("Use exactly one Brief.")
    indeg = {nid: 0 for nid in by_id}
    children: dict[str, list[str]] = defaultdict(list)
    for e in graph["edges"]:
        indeg[e["target"]] += 1
        children[e["source"]].append(e["target"])
    if indeg[briefs[0]["id"]]:
        raise GraphError("Nothing can come before the Brief.")
    queue = deque(sorted(nid for nid, d in indeg.items() if d == 0))
    out: list[str] = []
    while queue:
        nid = queue.popleft()
        out.append(nid)
        for c in sorted(children[nid]):
            indeg[c] -= 1
            if indeg[c] == 0:
                queue.append(c)
    if len(out) != len(by_id):
        raise GraphError("The workflow loops back on itself; remove the loop.")
    roots = [nid for nid in by_id if not any(e["target"] == nid for e in graph["edges"])]
    if roots != [briefs[0]["id"]]:
        raise GraphError("Connect every step to the Brief.")
    anc = _ancestors(graph)
    types = {nid: by_id[nid]["type"] for nid in by_id}
    for nid, kind in types.items():
        before = {types[a] for a in anc[nid]}
        if kind == "captions" and "video" not in before:
            raise GraphError("Captions go after a Video.")
        if kind == "approve" and not before & {"script", "images", "video"}:
            raise GraphError("Approve goes after something to approve.")
        if kind == "publish" and "approve" not in before:
            raise GraphError("Publish needs an Approve before it.")
    return [by_id[nid] for nid in out]


def starter() -> dict[str, Any]:
    """The default chain: brief -> script -> images -> video -> captions -> approve -> publish."""
    chain = ["brief", "script", "images", "video", "captions", "approve", "publish"]
    nodes = [{"id": f"n{i + 1}", "type": t, "position": {"x": 40 + i * 220, "y": 120 if i % 2 == 0 else 220},
              "data": {}} for i, t in enumerate(chain)]
    edges = [{"source": f"n{i + 1}", "target": f"n{i + 2}"} for i in range(len(chain) - 1)]
    return normalize({"nodes": nodes, "edges": edges})


__all__ = ["GraphError", "MAX_NODES", "NODE_TYPES", "normalize", "order", "starter"]
