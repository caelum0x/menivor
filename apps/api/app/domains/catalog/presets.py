"""Curated camera-motion + VFX preset catalog (Higgsfield-class creation).

Named camera moves (dolly/crane/crash-zoom/bullet-time/FPV…) and stackable VFX
presets (explosion/disintegration/earth-zoom…) a creator can apply to a reel.
Static reviewed data + pure validation (no DB); the reel-create + editor surfaces
offer these and the compose stage renders them. **Effects Mix** allows layering
several VFX in one shot, capped for sanity.
"""

from __future__ import annotations

MAX_EFFECTS_STACK = 4


def _m(pid: str, name: str, desc: str, *, tags: tuple[str, ...] = ()) -> dict:
    return {
        "id": pid,
        "name": name,
        "category": "camera",
        "description": desc,
        "intensity_default": 50,
        "intensity_min": 0,
        "intensity_max": 100,
        "tags": list(tags),
    }


# One-click camera moves with editable intensity (0..100).
CAMERA_MOTIONS: list[dict] = [
    _m("none", "None", "No virtual camera move.", tags=("default",)),
    _m("dolly_in", "Dolly In", "Push the camera toward the subject."),
    _m("dolly_out", "Dolly Out", "Pull the camera away from the subject."),
    _m("crane_up", "Crane Up", "Boom the camera upward."),
    _m("crane_down", "Crane Down", "Boom the camera downward."),
    _m("crash_zoom_in", "Crash Zoom In", "Fast punch-in on the subject.", tags=("punch",)),
    _m("crash_zoom_out", "Crash Zoom Out", "Fast pull-out from the subject.", tags=("punch",)),
    _m("orbit_360", "360 Orbit", "Rotate around the subject."),
    _m("dutch_angle", "Dutch Angle", "Tilt the horizon for tension."),
    _m("focus_change", "Focus Change", "Rack focus between planes."),
    _m("fpv_drone", "FPV Drone", "Aggressive first-person drone move.", tags=("drone",)),
    _m("hyperlapse", "Hyperlapse", "Time-compressed sweeping move.", tags=("time",)),
    _m("whip_pan", "Whip Pan", "Fast horizontal blur pan.", tags=("transition",)),
    _m("bullet_time", "Bullet Time", "Frozen-moment orbit.", tags=("hero",)),
    _m("truck_left", "Truck Left", "Slide the camera left."),
    _m("truck_right", "Truck Right", "Slide the camera right."),
    _m("pan_left", "Pan Left", "Rotate the camera left."),
    _m("pan_right", "Pan Right", "Rotate the camera right."),
    _m("tilt_up", "Tilt Up", "Rotate the camera up."),
    _m("tilt_down", "Tilt Down", "Rotate the camera down."),
]


def _v(pid: str, name: str, desc: str, *, tags: tuple[str, ...] = ()) -> dict:
    return {"id": pid, "name": name, "category": "vfx", "description": desc, "tags": list(tags)}


# Stackable cinematic VFX (Effects Mix).
VFX_PRESETS: list[dict] = [
    _v("explosion", "Explosion", "Big-budget explosion burst.", tags=("action",)),
    _v("disintegration", "Disintegration", "Subject disintegrates into particles."),
    _v("earth_zoom", "Earth Zoom", "Zoom out to orbit / in from space."),
    _v("datamosh", "Datamosh", "Compression-artifact transition.", tags=("transition",)),
    _v("light_leak", "Light Leak", "Warm analog light leaks."),
    _v("glitch", "Glitch", "Digital glitch distortion.", tags=("transition",)),
    _v("film_burn", "Film Burn", "Burning-film frame edges."),
    _v("smoke", "Smoke", "Atmospheric smoke haze."),
    _v("rain", "Rain", "Rain overlay."),
    _v("snow", "Snow", "Snow overlay."),
    _v("confetti", "Confetti", "Celebratory confetti burst.", tags=("celebration",)),
    _v("shockwave", "Shockwave", "Radial shockwave ripple.", tags=("action",)),
]

_CAMERA_BY_ID = {m["id"]: m for m in CAMERA_MOTIONS}
_VFX_BY_ID = {v["id"]: v for v in VFX_PRESETS}


class PresetError(ValueError):
    """An unknown or invalid preset selection (surfaced as a 422)."""


def get_camera_motion(pid: str) -> dict | None:
    return _CAMERA_BY_ID.get(str(pid or "").strip())


def get_vfx(pid: str) -> dict | None:
    return _VFX_BY_ID.get(str(pid or "").strip())


def validate_camera_motion(pid: str | None) -> str:
    """Return a valid camera-motion id ('none' when blank); raise on unknown."""
    value = str(pid or "").strip() or "none"
    if value not in _CAMERA_BY_ID:
        raise PresetError(f"unknown camera motion: {pid!r}")
    return value


def validate_effects_stack(effect_ids: list[str] | None, *, max_effects: int = MAX_EFFECTS_STACK) -> list[str]:
    """Normalize an Effects-Mix stack: dedup (order-preserving), cap, validate.

    Raises :class:`PresetError` for an unknown id or a stack over the cap.
    """
    if not effect_ids:
        return []
    seen: list[str] = []
    for raw in effect_ids:
        eid = str(raw or "").strip()
        if not eid or eid in seen:
            continue
        if eid not in _VFX_BY_ID:
            raise PresetError(f"unknown VFX preset: {raw!r}")
        seen.append(eid)
    if len(seen) > max_effects:
        raise PresetError(f"too many effects (max {max_effects})")
    return seen
