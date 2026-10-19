"""Pure motion orchestration (no DB).

Mirrors ``templates/service.py`` purity: the router calls these and does its own
best-effort persistence around them. Nothing here touches the database or network.
"""

from __future__ import annotations

from . import catalog
from .compiler import compile_motion
from .schemas import plan_view
from .spec import MotionPlan


def list_motions() -> tuple[dict, ...]:
    """All catalog presets (curated order)."""
    return catalog.list_motions()


def get_motion(preset_id: str) -> dict | None:
    """Raw catalog entry for ``preset_id`` (or ``None``)."""
    return catalog.get_motion(preset_id)


def compile(preset_id: str, intensity: int = 50) -> MotionPlan:
    """Compile a preset id + intensity into a frozen :class:`MotionPlan`."""
    return compile_motion(preset_id, intensity)


def resolve_for_render(preset_id: str, intensity: int = 50) -> dict:
    """Compile and return the JSON-safe plan view the render worker consumes."""
    return plan_view(compile_motion(preset_id, intensity))
