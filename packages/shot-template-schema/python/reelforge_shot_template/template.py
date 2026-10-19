"""Template + slot builders, validation, and deterministic hashing.

Mirrors ``src/{slots,template,validation,hash}.ts``. Slot times are **integer
milliseconds** so the content hash is byte-identical across TS/Python (no float
formatting drift). Feeds the ``templates/`` domain seeds + compiler.
"""

from __future__ import annotations

from typing import Any

from .roles import is_role, role_index


def make_slot(role: str, t_start_ms: int, t_end_ms: int, *, caption_preset: str = "",
              transition_out: str = "cut") -> dict[str, Any]:
    return {
        "role": role,
        "t_start_ms": int(t_start_ms),
        "t_end_ms": int(t_end_ms),
        "caption_preset": caption_preset,
        "transition_out": transition_out,
    }


def make_template(slug: str, genre: str, aspect: str, slots: list[dict]) -> dict[str, Any]:
    return {"slug": slug, "genre": genre, "aspect": aspect, "slots": slots}


def total_duration_ms(template: dict) -> int:
    slots = template.get("slots") or []
    return max((int(s["t_end_ms"]) for s in slots), default=0)


def validate_template(template: dict) -> list[str]:
    """Return a list of invariant violations (empty = valid)."""
    errors: list[str] = []
    slots = template.get("slots") or []
    if not slots:
        errors.append("template has no slots")
        return errors
    prev_end = None
    prev_role_idx = -1
    for i, s in enumerate(slots):
        role = s.get("role")
        if not is_role(str(role)):
            errors.append(f"slot {i}: unknown role {role!r}")
            continue
        ts, te = int(s["t_start_ms"]), int(s["t_end_ms"])
        if ts < 0:
            errors.append(f"slot {i}: negative t_start_ms")
        if te <= ts:
            errors.append(f"slot {i}: t_end_ms must be > t_start_ms")
        if prev_end is not None and ts < prev_end:
            errors.append(f"slot {i}: overlaps previous slot")
        if prev_end is not None and ts > prev_end:
            errors.append(f"slot {i}: gap after previous slot")
        idx = role_index(str(role))
        if idx < prev_role_idx:
            errors.append(f"slot {i}: role {role!r} out of narrative order")
        prev_end = te
        prev_role_idx = idx
    if slots and slots[0].get("role") not in ("hook", "loop"):
        errors.append("first slot should be a hook (or a single loop)")
    return errors


def _canon(template: dict) -> str:
    slots = template.get("slots") or []
    body = ";".join(
        f"{s['role']},{int(s['t_start_ms'])},{int(s['t_end_ms'])},"
        f"{s.get('caption_preset', '')},{s.get('transition_out', '')}"
        for s in slots
    )
    return f"{template['slug']}|{template['genre']}|{template['aspect']}|{body}"


def content_hash(template: dict) -> str:
    """Deterministic FNV-1a-32 hex of the canonical template (for instance pinning)."""
    h = 0x811C9DC5
    for byte in _canon(template).encode("utf-8"):
        h ^= byte
        h = (h * 0x01000193) % 0x100000000
    return format(h, "08x")
