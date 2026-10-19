"""Pydantic v2 DTOs + plain dict view builders for the motion HTTP surface.

No ``response_model`` — the router returns the MPT ``get_response`` envelope with
these plain dicts (mirrors the templates domain).
"""

from __future__ import annotations

from dataclasses import asdict

from pydantic import BaseModel, Field

from .spec import CameraControlSpec, FilterPlan, MotionPlan


class CompileMotionRequest(BaseModel):
    """Body for ``POST /motion/{preset_id}/compile``."""

    preset_id: str = Field(default="", description="ignored when the path param is set")
    intensity: int = Field(default=50, ge=0, le=100)


def motion_summary(entry: dict) -> dict:
    """Compact gallery card for a catalog preset."""
    return {
        "id": entry["id"],
        "name": entry["name"],
        "category": entry["category"],
        "render_class": entry["render_class"],
        "description": entry["description"],
        "intensity": entry["intensity"],
        "tags": list(entry.get("tags", ())),
        # Clients that only distinguish filter/model treat hybrid as model (it
        # needs the provider); render_class above stays the source of truth.
        "requires_provider": entry["render_class"] in ("model", "hybrid"),
    }


def motion_detail(entry: dict) -> dict:
    """Full preset detail (adds the resolved filter/model sub-specs)."""
    detail = {**motion_summary(entry)}
    if "filter" in entry:
        detail["filter"] = {
            "camera_motion": entry["filter"]["camera_motion"],
            "effects": list(entry["filter"].get("effects", ())),
        }
    if "model" in entry:
        m = entry["model"]
        detail["model"] = {
            "capability": m["capability"],
            "camera_pose": m["camera_pose"],
            "prompt_fragment": m["prompt_fragment"],
            "speed": m["speed"],
            "supports_intensity": m.get("supports_intensity", True),
            "license_class": m.get("license_class", "open_weights"),
        }
    return detail


def _filter_view(fp: FilterPlan | None) -> dict | None:
    return None if fp is None else asdict(fp)


def _model_view(cc: CameraControlSpec | None) -> dict | None:
    if cc is None:
        return None
    d = asdict(cc)
    # asdict already turns tuples into lists; keep param_map as key/value pairs.
    d["param_map"] = [list(pair) for pair in cc.param_map]
    d["pose_trajectory"] = [list(row) for row in cc.pose_trajectory]
    d["provider_hints"] = list(cc.provider_hints)
    return d


def plan_view(plan: MotionPlan) -> dict:
    """JSON-safe view of a compiled :class:`MotionPlan`."""
    return {
        "preset_id": plan.preset_id,
        "motion_class": plan.motion_class,
        "filter": _filter_view(plan.filter),
        "model": _model_view(plan.model),
    }
