"""Deterministic workflow pinning (mirror of ``src/pin.ts``).

A workflow version is pinned by an FNV-1a-32 hash over its canonical identity —
slug + sorted node commits + sorted weight refs + the input contract — so the
render-farm registry, adapters, and desktop endpoint all reference one immutable
identity. Integer/string-only canon → byte-identical TS/Python.
"""

from __future__ import annotations

from typing import Any


def _canon(descriptor: dict[str, Any]) -> str:
    node_commits = descriptor.get("node_commits") or {}
    commits = ";".join(f"{k}={node_commits[k]}" for k in sorted(node_commits))
    weights = ",".join(sorted(descriptor.get("weight_refs") or []))
    slots = descriptor.get("inputs") or []
    inputs = ";".join(
        f"{s['name']}:{s['type']}:{s.get('default', '')}:{int(bool(s.get('required', False)))}"
        for s in slots
    )
    return f"{descriptor['slug']}|{descriptor['category']}|{commits}|{weights}|{inputs}"


def graph_hash(descriptor: dict[str, Any]) -> str:
    """FNV-1a-32 hex pin of a workflow descriptor (reproducibility identity)."""
    h = 0x811C9DC5
    for byte in _canon(descriptor).encode("utf-8"):
        h ^= byte
        h = (h * 0x01000193) % 0x100000000
    return format(h, "08x")


def validate_inputs(descriptor: dict[str, Any], values: dict[str, Any]) -> list[str]:
    """Validate submitted values against the workflow's input contract."""
    errors: list[str] = []
    for slot in descriptor.get("inputs") or []:
        name = slot["name"]
        present = name in values
        if slot.get("required") and not present:
            errors.append(f"missing required input {name!r}")
            continue
        if not present:
            continue
        v = values[name]
        if slot["type"] == "int":
            if not isinstance(v, int) or isinstance(v, bool):
                errors.append(f"input {name!r} must be an int")
                continue
            lo, hi = slot.get("min"), slot.get("max")
            if lo is not None and v < lo:
                errors.append(f"input {name!r} below min {lo}")
            if hi is not None and v > hi:
                errors.append(f"input {name!r} above max {hi}")
        elif slot["type"] == "string" and not isinstance(v, str):
            errors.append(f"input {name!r} must be a string")
    return errors
