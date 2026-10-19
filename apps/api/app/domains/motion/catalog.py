"""Versioned motion-preset catalog — the >=50 camera moves ReelForge exposes.

Each preset is plain data tagged with a ``render_class``:

* ``filter`` — renders now with pure FFmpeg (``services/compose/vfx``). Carries a
  ``filter`` sub-dict {camera_motion, effects}.
* ``model``  — requires the Wan camera-control provider. Carries a ``model``
  sub-dict describing the :class:`~app.domains.motion.spec.CameraControlSpec`.
* ``hybrid`` — a model move with a deterministic FFmpeg fallback (both sub-dicts).
  Surfaced to clients as ``model`` (it needs the provider) but ``render_class``
  here is the source of truth and DOES carry "hybrid".

Pure data + tiny accessors — no DB, no ffmpeg. ``validate_motion`` raises
:class:`MotionPresetError` (the router maps it to 422). ``FILTER_ALIAS`` is
re-exported from the vfx module so there is a single reconciliation table.
"""

from __future__ import annotations

from app.services.compose.vfx import FILTER_ALIAS  # single source of truth (re-exported)

CATALOG_VERSION = "2026.08.1"

# Default clip length for model presets: 5s @ 16fps -> 81 frames (k*4+1 legal).
_DEFAULT_SECONDS = 5.0
_OPEN = "open_weights"


class MotionPresetError(ValueError):
    """Raised for an unknown / invalid motion preset id (router -> 422)."""


# --------------------------------------------------------------------------- #
# Trajectory helper — a well-formed raw c2w row is 23 floats:
#   idx  fx fy cx cy  0 0  <16 c2w matrix floats>
# We synthesize a small, deterministic path (identity rotation + a translation
# ramp) so every "Custom" preset ships a valid, provider-ready trajectory.
# --------------------------------------------------------------------------- #
def _c2w(tx: float, ty: float, tz: float) -> tuple[float, ...]:
    # Row-major 4x4 camera-to-world with identity rotation and a translation.
    return (
        1.0, 0.0, 0.0, tx,
        0.0, 1.0, 0.0, ty,
        0.0, 0.0, 1.0, tz,
        0.0, 0.0, 0.0, 1.0,
    )


def _traj(deltas: tuple[tuple[float, float, float], ...]) -> tuple[tuple[float, ...], ...]:
    rows: list[tuple[float, ...]] = []
    for i, (tx, ty, tz) in enumerate(deltas):
        rows.append((float(i), 0.5, 0.5, 0.5, 0.5, 0.0, 0.0, *_c2w(tx, ty, tz)))
    return tuple(rows)


# A few reusable named trajectories (translations are unit-scaled; the provider
# multiplies by ``speed``/Wan base scale).
_TRAJ_ARC_L = _traj(((0.0, 0.0, 0.0), (-0.4, 0.0, 0.3), (-0.8, 0.0, 0.0)))
_TRAJ_ARC_R = _traj(((0.0, 0.0, 0.0), (0.4, 0.0, 0.3), (0.8, 0.0, 0.0)))
_TRAJ_FORWARD = _traj(((0.0, 0.0, 0.0), (0.0, 0.0, 0.5), (0.0, 0.0, 1.0)))
_TRAJ_DIAG_UL = _traj(((0.0, 0.0, 0.0), (-0.3, 0.3, 0.0), (-0.6, 0.6, 0.0)))
_TRAJ_DIAG_DR = _traj(((0.0, 0.0, 0.0), (0.3, -0.3, 0.0), (0.6, -0.6, 0.0)))
_TRAJ_SPIRAL = _traj(((0.0, 0.0, 0.0), (0.3, 0.3, 0.2), (-0.3, 0.6, 0.4), (0.3, 0.9, 0.6)))
_TRAJ_ORBIT_DESCEND = _traj(((0.0, 0.0, 0.0), (0.4, -0.2, 0.0), (0.0, -0.4, 0.0), (-0.4, -0.6, 0.0)))
_TRAJ_CRANE_OVER = _traj(((0.0, 0.0, 0.0), (0.0, 0.5, 0.3), (0.0, 0.8, 0.6)))
_TRAJ_ROBO = _traj(((0.0, 0.0, 0.0), (0.3, 0.2, 0.2), (-0.2, 0.4, 0.4), (0.0, 0.1, 0.6)))
_TRAJ_BULLET = _traj(((0.0, 0.0, 0.0), (0.5, 0.0, 0.0), (0.5, 0.0, 0.0), (-0.5, 0.0, 0.0)))
_TRAJ_SNORRI = _traj(((0.0, 0.0, 0.0), (0.05, 0.03, 0.0), (-0.05, -0.03, 0.0)))
_TRAJ_HANDHELD = _traj(((0.0, 0.0, 0.0), (0.04, 0.05, 0.02), (-0.05, 0.03, -0.02)))
_TRAJ_VERTIGO = _traj(((0.0, 0.0, 0.0), (0.0, 0.0, 0.5), (0.0, 0.0, 1.0)))


# --------------------------------------------------------------------------- #
# Entry builders
# --------------------------------------------------------------------------- #
def _filter(
    pid: str, name: str, category: str, desc: str, *,
    camera_motion: str, effects: tuple[str, ...] = (), tags: tuple[str, ...] = (),
    intensity: int = 50,
) -> dict:
    return {
        "id": pid, "name": name, "category": category, "render_class": "filter",
        "description": desc, "intensity": intensity, "tags": tags,
        "filter": {"camera_motion": camera_motion, "effects": effects},
    }


def _model_dict(
    *, camera_pose: str, prompt_fragment: str, speed: float = 1.0,
    capability: str = "image_to_video", supports_intensity: bool = True,
    param_map: dict[str, str] | None = None,
    pose_trajectory: tuple[tuple[float, ...], ...] = (),
    license_class: str = _OPEN,
) -> dict:
    return {
        "capability": capability,
        "camera_pose": camera_pose,
        "prompt_fragment": prompt_fragment,
        "speed": speed,
        "supports_intensity": supports_intensity,
        "param_map": dict(param_map or {}),
        "pose_trajectory": pose_trajectory,
        "license_class": license_class,
    }


def _model(
    pid: str, name: str, category: str, desc: str, *,
    model: dict, tags: tuple[str, ...] = (), intensity: int = 50,
) -> dict:
    return {
        "id": pid, "name": name, "category": category, "render_class": "model",
        "description": desc, "intensity": intensity, "tags": tags, "model": model,
    }


def _hybrid(
    pid: str, name: str, category: str, desc: str, *,
    model: dict, fallback_camera_motion: str, tags: tuple[str, ...] = (),
    intensity: int = 50,
) -> dict:
    return {
        "id": pid, "name": name, "category": category, "render_class": "hybrid",
        "description": desc, "intensity": intensity, "tags": tags, "model": model,
        "filter": {"camera_motion": fallback_camera_motion, "effects": ()},
    }


# --------------------------------------------------------------------------- #
# FILTER-class presets (pure FFmpeg).
# --------------------------------------------------------------------------- #
_FILTER_PRESETS: tuple[dict, ...] = (
    _filter("none", "None", "static", "No virtual camera move (identity).",
            camera_motion="none", tags=("static",), intensity=0),
    _filter("dolly_in", "Dolly In", "zoom", "Push toward the subject.",
            camera_motion="dolly_in", tags=("push", "zoom")),
    _filter("dolly_out", "Dolly Out", "zoom", "Pull away from the subject.",
            camera_motion="dolly_out", tags=("pull", "zoom")),
    _filter("push_in", "Push In", "zoom", "Legacy push-in (reconciles to dolly_in).",
            camera_motion="dolly_in", tags=("push", "legacy")),
    _filter("pull_out", "Pull Out", "zoom", "Legacy pull-out (reconciles to dolly_out).",
            camera_motion="dolly_out", tags=("pull", "legacy")),
    _filter("ken_burns", "Ken Burns", "zoom", "Slow zoom-in with a gentle diagonal pan.",
            camera_motion="ken_burns_fx", tags=("slow", "pan", "zoom")),
    _filter("crash_zoom_in", "Crash Zoom In", "zoom", "Fast punch-in on the subject.",
            camera_motion="crash_zoom_in", tags=("fast", "zoom"), intensity=70),
    _filter("crash_zoom_out", "Crash Zoom Out", "zoom", "Fast pull-out.",
            camera_motion="crash_zoom_out", tags=("fast", "zoom"), intensity=70),
    _filter("zoom_punch_in", "Zoom Punch In", "zoom", "Aggressive snap zoom-in.",
            camera_motion="zoom_punch_in", tags=("fast", "punch"), intensity=80),
    _filter("zoom_punch_out", "Zoom Punch Out", "zoom", "Aggressive snap zoom-out.",
            camera_motion="zoom_punch_out", tags=("fast", "punch"), intensity=80),
    _filter("slow_zoom_in", "Slow Zoom In", "zoom", "Gentle continuous zoom-in.",
            camera_motion="slow_zoom_in", tags=("slow", "zoom"), intensity=30),
    _filter("slow_zoom_out", "Slow Zoom Out", "zoom", "Gentle continuous zoom-out.",
            camera_motion="slow_zoom_out", tags=("slow", "zoom"), intensity=30),
    _filter("bullet_time_hold", "Bullet-Time Hold", "hold", "Frozen punch-in hold.",
            camera_motion="bullet_time_hold", tags=("hold", "freeze")),
    _filter("dutch_angle", "Dutch Angle", "tilt", "Tilted horizon.",
            camera_motion="dutch_angle", tags=("tilt",)),
    _filter("dutch_left", "Dutch Left", "tilt", "Dutch tilt leaning left.",
            camera_motion="dutch_left", tags=("tilt", "left")),
    _filter("dutch_right", "Dutch Right", "tilt", "Dutch tilt leaning right.",
            camera_motion="dutch_right", tags=("tilt", "right")),
    _filter("pan_left", "Pan Left", "pan", "Horizontal drift left.",
            camera_motion="pan_left", tags=("pan", "left")),
    _filter("pan_right", "Pan Right", "pan", "Horizontal drift right.",
            camera_motion="pan_right", tags=("pan", "right")),
    _filter("truck_left", "Truck Left", "pan", "Slide left.",
            camera_motion="truck_left", tags=("truck", "left")),
    _filter("truck_right", "Truck Right", "pan", "Slide right.",
            camera_motion="truck_right", tags=("truck", "right")),
    _filter("drift_left", "Drift Left", "pan", "Slow low-amplitude lateral drift left.",
            camera_motion="drift_left", tags=("drift", "left"), intensity=30),
    _filter("drift_right", "Drift Right", "pan", "Slow low-amplitude lateral drift right.",
            camera_motion="drift_right", tags=("drift", "right"), intensity=30),
    _filter("tilt_up", "Tilt Up", "tilt", "Vertical drift up.",
            camera_motion="tilt_up", tags=("tilt", "up")),
    _filter("tilt_down", "Tilt Down", "tilt", "Vertical drift down.",
            camera_motion="tilt_down", tags=("tilt", "down")),
    _filter("crane_up", "Crane Up", "crane", "Boom up.",
            camera_motion="crane_up", tags=("crane", "up")),
    _filter("crane_down", "Crane Down", "crane", "Boom down.",
            camera_motion="crane_down", tags=("crane", "down")),
    _filter("orbit_360_fake", "Fake Orbit 360", "orbit", "Rotate+zoom pseudo-orbit (2D).",
            camera_motion="orbit_360_fake", tags=("orbit", "fake")),
    _filter("fpv_drone_shake", "FPV Drone Shake", "drone", "High-freq rotate jitter FPV feel (2D).",
            camera_motion="fpv_drone_shake", tags=("drone", "shake")),
    _filter("handheld_shake", "Handheld Shake", "handheld", "Subtle handheld jitter via crop.",
            camera_motion="handheld_shake", tags=("handheld", "shake"), intensity=40),
    _filter("hyperlapse", "Hyperlapse", "time", "Time-compress via setpts.",
            camera_motion="hyperlapse", tags=("time", "speed")),
    _filter("speed_ramp", "Speed Ramp", "time", "Variable setpts speed ramp.",
            camera_motion="speed_ramp", tags=("time", "ramp")),
    _filter("whip_pan", "Whip Pan", "pan", "Fast blur pan transition.",
            camera_motion="whip_pan", tags=("whip", "pan"), intensity=80),
    _filter("focus_change", "Focus Change", "focus", "Rack-focus blur ease-out.",
            camera_motion="focus_change", tags=("focus",)),
    _filter("rack_focus", "Rack Focus", "focus", "Rack-focus (alias of focus_change).",
            camera_motion="rack_focus", tags=("focus", "legacy")),
    _filter("vignette_punch", "Vignette Punch", "zoom", "Zoom-in with tightening vignette.",
            camera_motion="vignette_punch", tags=("zoom", "vignette")),
    _filter("glow_bloom", "Glow Bloom", "look", "Dreamy glow bloom look.",
            camera_motion="none", effects=("glow",), tags=("glow", "look")),
)


# --------------------------------------------------------------------------- #
# MODEL-class presets (Wan camera-control).
# --------------------------------------------------------------------------- #
def _named(pose: str, phrase: str, **kw) -> dict:
    return _model_dict(camera_pose=pose, prompt_fragment=phrase, **kw)


def _custom(phrase: str, traj: tuple[tuple[float, ...], ...], **kw) -> dict:
    return _model_dict(camera_pose="Custom", prompt_fragment=phrase, pose_trajectory=traj, **kw)


_MODEL_PRESETS: tuple[dict, ...] = (
    _model("orbit_left_360", "Orbit Left 360", "orbit",
           "True 3D orbit counter-clockwise around the subject.",
           model=_named("Anti Clockwise", "a smooth 360-degree orbit counter-clockwise around the subject with real parallax"),
           tags=("orbit", "3d")),
    _model("orbit_right_360", "Orbit Right 360", "orbit",
           "True 3D orbit clockwise around the subject.",
           model=_named("ClockWise", "a smooth 360-degree orbit clockwise around the subject with real parallax"),
           tags=("orbit", "3d")),
    _model("arc_left", "Arc Left", "orbit",
           "90-degree arc left with real parallax.",
           model=_custom("a 90-degree arcing move to the left revealing depth around the subject", _TRAJ_ARC_L),
           tags=("arc", "3d")),
    _model("arc_right", "Arc Right", "orbit",
           "90-degree arc right with real parallax.",
           model=_custom("a 90-degree arcing move to the right revealing depth around the subject", _TRAJ_ARC_R),
           tags=("arc", "3d")),
    _model("product_360_spin", "Product 360 Spin", "product",
           "Product turntable full 360 spin.",
           model=_named("ClockWise", "a slow product turntable spinning a full 360 degrees", speed=0.6, supports_intensity=False),
           tags=("product", "spin")),
    _model("bullet_time_freeze", "Bullet-Time Freeze", "hero",
           "Frozen-moment multi-angle orbit.",
           model=_custom("a frozen bullet-time moment orbiting around the subject from multiple angles", _TRAJ_BULLET),
           tags=("bullet", "hero")),
    _model("robo_arm", "Robo Arm", "rig",
           "Programmed robotic-arm swoop path.",
           model=_custom("a precise programmed robotic-arm camera swoop weaving toward the subject", _TRAJ_ROBO),
           tags=("rig", "swoop")),
    _model("drone_flythrough", "Drone Fly-Through", "drone",
           "FPV drone fly-through with true depth.",
           model=_custom("an FPV drone flying forward through the scene with true depth and a slight bank", _TRAJ_FORWARD),
           tags=("drone", "fpv")),
    _model("drone_orbit", "Drone Orbit", "drone",
           "Aerial orbit descend.",
           model=_custom("an aerial drone orbiting the subject while gently descending", _TRAJ_ORBIT_DESCEND),
           tags=("drone", "orbit")),
    _model("flyover", "Flyover", "crane",
           "High crane flyover reveal.",
           model=_custom("a high crane flyover sweeping over and revealing the scene", _TRAJ_CRANE_OVER),
           tags=("crane", "reveal")),
    _model("dolly_zoom_vertigo", "Dolly Zoom (Vertigo)", "hero",
           "True dolly-zoom / Hitchcock vertigo.",
           model=_custom("a Hitchcock dolly-zoom vertigo effect pushing in while the background stretches", _TRAJ_VERTIGO,
                         param_map={"counter_zoom": "true"}),
           tags=("vertigo", "hero"), intensity=60),
    _model("crane_up_reveal", "Crane Up Reveal", "crane",
           "Crane boom up revealing scene depth.",
           model=_named("Pan Up", "a crane boom rising up to reveal the depth of the scene"),
           tags=("crane", "reveal")),
    _model("crane_down_reveal", "Crane Down Reveal", "crane",
           "Crane boom down.",
           model=_named("Pan Down", "a crane boom lowering down through the scene"),
           tags=("crane", "reveal")),
    _model("pan_up_reveal", "Pan Up Reveal", "pan",
           "Tilt-up reveal with parallax.",
           model=_named("Pan Up", "a tilt-up reveal with real depth parallax"),
           tags=("pan", "reveal")),
    _model("pan_down_reveal", "Pan Down Reveal", "pan",
           "Tilt-down reveal.",
           model=_named("Pan Down", "a tilt-down reveal with real depth parallax"),
           tags=("pan", "reveal")),
    _model("pan_left_parallax", "Pan Left Parallax", "pan",
           "Lateral pan left with real depth.",
           model=_named("Pan Left", "a lateral pan to the left with real depth parallax"),
           tags=("pan", "parallax")),
    _model("pan_right_parallax", "Pan Right Parallax", "pan",
           "Lateral pan right with real depth.",
           model=_named("Pan Right", "a lateral pan to the right with real depth parallax"),
           tags=("pan", "parallax")),
    _model("zoom_in_parallax", "Zoom In Parallax", "zoom",
           "Dolly zoom-in with parallax.",
           model=_named("Zoom In", "a dolly zoom-in pushing toward the subject with real parallax"),
           tags=("zoom", "parallax")),
    _model("zoom_out_reveal", "Zoom Out Reveal", "zoom",
           "Dolly zoom-out reveal.",
           model=_named("Zoom Out", "a dolly zoom-out pulling back to reveal the wider scene"),
           tags=("zoom", "reveal")),
    _model("push_in_parallax", "Push In Parallax", "zoom",
           "Slow push-in with real 3D depth.",
           model=_named("Zoom In", "a slow cinematic push-in toward the subject with real 3D depth", speed=0.5),
           tags=("push", "parallax"), intensity=30),
    _model("pull_back_reveal", "Pull Back Reveal", "zoom",
           "Pull-back big reveal.",
           model=_named("Zoom Out", "a dramatic pull-back revealing the full environment", speed=1.4),
           tags=("pull", "reveal"), intensity=70),
    _model("diagonal_pan_up_left", "Diagonal Pan Up-Left", "pan",
           "Compound diagonal up-left.",
           model=_custom("a compound diagonal camera move drifting up and to the left with parallax", _TRAJ_DIAG_UL),
           tags=("diagonal", "pan")),
    _model("diagonal_pan_down_right", "Diagonal Pan Down-Right", "pan",
           "Compound diagonal down-right.",
           model=_custom("a compound diagonal camera move drifting down and to the right with parallax", _TRAJ_DIAG_DR),
           tags=("diagonal", "pan")),
    _model("spiral_ascend", "Spiral Ascend", "orbit",
           "Spiral ascending orbit.",
           model=_custom("a spiral orbit ascending around the subject with real depth", _TRAJ_SPIRAL),
           tags=("spiral", "orbit")),
    _model("through_object", "Through Object", "hero",
           "Fly through a window/doorway into the scene.",
           model=_custom("the camera flying forward through a window or doorway into the scene", _TRAJ_FORWARD),
           tags=("through", "hero")),
    _model("snorricam", "SnorriCam", "rig",
           "Subject-locked body-mounted rig look.",
           model=_custom("a subject-locked body-mounted SnorriCam rig where the world sways around the fixed subject", _TRAJ_SNORRI),
           tags=("rig", "locked")),
    _model("handheld_follow", "Handheld Follow", "handheld",
           "Handheld follow-cam with organic sway.",
           model=_custom("a handheld follow-cam tracking the subject with organic low-amplitude sway", _TRAJ_HANDHELD),
           tags=("handheld", "follow"), intensity=40),
)


# --------------------------------------------------------------------------- #
# HYBRID presets — model move + deterministic FFmpeg fallback.
# --------------------------------------------------------------------------- #
_HYBRID_PRESETS: tuple[dict, ...] = (
    _hybrid("crash_zoom_3d", "Crash Zoom 3D", "zoom",
            "Model crash-zoom with real parallax; FFmpeg crash_zoom_in fallback.",
            model=_named("Zoom In", "an aggressive crash zoom-in punching toward the subject with real 3D parallax", speed=1.6),
            fallback_camera_motion="crash_zoom_in", tags=("crash", "hybrid"), intensity=80),
    _hybrid("orbit_hero", "Orbit Hero", "hero",
            "Model bullet-time hero orbit; FFmpeg orbit_360_fake fallback.",
            model=_custom("a heroic bullet-time orbit sweeping around the subject", _TRAJ_BULLET),
            fallback_camera_motion="orbit_360_fake", tags=("orbit", "hybrid")),
    _hybrid("vertigo_hybrid", "Vertigo Hybrid", "hero",
            "Model dolly-zoom vertigo; FFmpeg slow_zoom_in fallback.",
            model=_custom("a dolly-zoom vertigo push-in with the background stretching", _TRAJ_VERTIGO,
                          param_map={"counter_zoom": "true"}),
            fallback_camera_motion="slow_zoom_in", tags=("vertigo", "hybrid"), intensity=60),
)


MOTION_PRESETS: tuple[dict, ...] = _FILTER_PRESETS + _MODEL_PRESETS + _HYBRID_PRESETS
_BY_ID: dict[str, dict] = {m["id"]: m for m in MOTION_PRESETS}


def list_motions() -> tuple[dict, ...]:
    """All presets in curated (filter → model → hybrid) order."""
    return MOTION_PRESETS


def get_motion(preset_id: str) -> dict | None:
    """Return the raw catalog entry for ``preset_id`` (or ``None`` if unknown)."""
    return _BY_ID.get(str(preset_id or ""))


def validate_motion(preset_id: str) -> dict:
    """Return the entry for ``preset_id`` or raise :class:`MotionPresetError`."""
    entry = get_motion(preset_id)
    if entry is None:
        raise MotionPresetError(f"unknown motion preset {preset_id!r}")
    return entry


__all__ = [
    "CATALOG_VERSION",
    "MOTION_PRESETS",
    "FILTER_ALIAS",
    "MotionPresetError",
    "list_motions",
    "get_motion",
    "validate_motion",
]
