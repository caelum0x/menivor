"""Pure ``compile_motion(preset_id, intensity) -> MotionPlan``.

Deterministic, no DB/network. Validates the preset via ``catalog.validate_motion``
(raising :class:`~app.domains.motion.catalog.MotionPresetError` → 422 at the
router), clamps ``intensity`` to 0..100, and emits a single frozen
:class:`~app.domains.motion.spec.MotionPlan` the render worker branches on:

* ``filter`` — a :class:`FilterPlan` whose ``camera_motion`` is a vfx-recognized id.
* ``model``  — a :class:`CameraControlSpec` built from the catalog ``model`` sub-dict
  (speed + prompt phrasing scaled by intensity; length snapped via ``snap_length``).
* ``hybrid`` — BOTH: the model spec plus the deterministic FFmpeg fallback plan.
"""

from __future__ import annotations

from . import catalog
from .spec import (
    CameraControlSpec,
    FilterPlan,
    MotionPlan,
    snap_length,
)

# Model presets default to a 5s clip (snapped to a legal Wan frame count).
_DEFAULT_SECONDS = 5.0
_STEP16_WIDTH = 832
_STEP16_HEIGHT = 480


def _clamp_intensity(intensity: int) -> int:
    try:
        val = int(intensity)
    except (TypeError, ValueError):
        val = 50
    return max(0, min(100, val))


def _phrase(fragment: str, intensity: int) -> str:
    """Scale the natural-language camera phrase by intensity (deterministic)."""
    frag = fragment.strip()
    if intensity <= 33:
        return f"slow, subtle {frag}"
    if intensity >= 67:
        return f"fast, dramatic {frag}"
    return frag


def _scaled_speed(base: float, intensity: int, supports_intensity: bool) -> float:
    """Scale ``base`` speed by intensity around 1.0 (0.5x..1.5x), clamped 0..10."""
    if not supports_intensity:
        return max(0.0, min(10.0, round(float(base), 3)))
    factor = 0.5 + intensity / 100.0  # 0->0.5x, 50->1.0x, 100->1.5x
    return max(0.0, min(10.0, round(float(base) * factor, 3)))


def _build_filter(spec: dict, intensity: int) -> FilterPlan:
    return FilterPlan(
        camera_motion=str(spec.get("camera_motion", "none")),
        intensity=intensity,
        effects=tuple(spec.get("effects", ()) or ()),
    )


def _build_model(preset_id: str, model: dict, intensity: int) -> CameraControlSpec:
    length = snap_length(_DEFAULT_SECONDS, fps=16)
    param_map = tuple(sorted((str(k), str(v)) for k, v in dict(model.get("param_map", {})).items()))
    trajectory = tuple(
        tuple(float(x) for x in row) for row in model.get("pose_trajectory", ()) or ()
    )
    return CameraControlSpec(
        preset_id=preset_id,
        capability=str(model.get("capability", "image_to_video")),
        camera_pose=str(model["camera_pose"]),
        prompt_fragment=_phrase(str(model.get("prompt_fragment", "")), intensity),
        speed=_scaled_speed(
            float(model.get("speed", 1.0)), intensity, bool(model.get("supports_intensity", True))
        ),
        width=_STEP16_WIDTH,
        height=_STEP16_HEIGHT,
        length=length,
        pose_trajectory=trajectory,
        provider_hints=tuple(model.get("provider_hints", ("wan_camera",)) or ("wan_camera",)),
        param_map=param_map,
        license_class=str(model.get("license_class", "open_weights")),
        intensity=intensity,
    )


def compile_motion(preset_id: str, intensity: int = 50) -> MotionPlan:
    """Compile a preset id + intensity into a frozen :class:`MotionPlan`."""
    entry = catalog.validate_motion(preset_id)
    intensity = _clamp_intensity(intensity)
    render_class = entry["render_class"]

    if render_class == "filter":
        return MotionPlan(
            preset_id=preset_id,
            motion_class="filter",
            filter=_build_filter(entry["filter"], intensity),
        )

    if render_class == "model":
        return MotionPlan(
            preset_id=preset_id,
            motion_class="model",
            model=_build_model(preset_id, entry["model"], intensity),
        )

    # hybrid — model spec + deterministic FFmpeg fallback (used on ProviderError).
    return MotionPlan(
        preset_id=preset_id,
        motion_class="hybrid",
        model=_build_model(preset_id, entry["model"], intensity),
        filter=_build_filter(entry["filter"], intensity),
    )
