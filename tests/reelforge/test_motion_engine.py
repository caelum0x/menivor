"""Wave-1 ReelForge motion/camera engine — pure catalog + compiler + spec.

Covers the MOTION half of the shared Wave-1 contract:

  * SPEC (``app.domains.motion.spec``) — frozen ``FilterPlan`` / ``CameraControlSpec``
    / ``MotionPlan`` dataclasses, the ``to_wan_request`` provider request builder,
    and the ``snap_length`` frame-count helper (all pure, no DB/network).
  * CATALOG (``app.domains.motion.catalog``) — >=50 versioned presets, each tagged
    with a ``render_class`` in {filter, model, hybrid}; ``validate_motion`` raises
    ``MotionPresetError`` for unknown ids.
  * COMPILER (``app.domains.motion.compiler``) — pure ``compile_motion(pid, intensity)``
    → ``MotionPlan``: every preset compiles; filter presets resolve to non-empty
    real FFmpeg fragments; model/hybrid presets emit a well-formed camera spec.
  * VFX RECONCILIATION (``app.services.compose.vfx``) — new fragments render, legacy
    aliases resolve, model-only ids never emit geometry, existing ids unchanged.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.domains.motion import catalog, compiler, service, spec
from app.domains.motion.catalog import MotionPresetError
from app.domains.motion.spec import (
    CameraControlSpec,
    FilterPlan,
    MotionPlan,
    snap_length,
    to_wan_request,
)
from app.services.compose import vfx

_WAN_POSES = {
    "Static", "Pan Up", "Pan Down", "Pan Left", "Pan Right",
    "Zoom In", "Zoom Out", "Anti Clockwise", "ClockWise",
}
_ALL_POSES = _WAN_POSES | {"Custom"}
_CAPS = {"image_to_video", "text_to_video"}


# --------------------------------------------------------------------------- #
# Catalog shape
# --------------------------------------------------------------------------- #
def test_catalog_has_at_least_50_presets_and_version():
    ids = [m["id"] for m in catalog.list_motions()]
    assert len(ids) >= 50
    assert len(ids) == len(set(ids)), "preset ids must be unique"
    assert isinstance(catalog.CATALOG_VERSION, str) and catalog.CATALOG_VERSION


def test_every_render_class_is_valid():
    for m in catalog.list_motions():
        assert m["render_class"] in ("filter", "model", "hybrid")


def test_validate_motion_rejects_unknown():
    with pytest.raises(MotionPresetError):
        catalog.validate_motion("does_not_exist")


def test_get_motion_unknown_returns_none():
    assert catalog.get_motion("nope") is None


# --------------------------------------------------------------------------- #
# snap_length + to_wan_request (shared helpers)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "seconds, fps, expected",
    [(5.0, 16, 81), (1.0, 16, 17), (0.0, 16, 5), (3.0, 16, 49), (10.0, 16, 161)],
)
def test_snap_length_is_valid_k4plus1(seconds, fps, expected):
    got = snap_length(seconds, fps)
    assert got == expected
    assert got >= 5 and (got - 1) % 4 == 0


def test_snap_length_always_legal_for_any_input():
    for s in [x / 3 for x in range(0, 100)]:
        n = snap_length(s)
        assert n >= 5 and (n - 1) % 4 == 0


def test_to_wan_request_exact_shape():
    s = CameraControlSpec(
        preset_id="orbit_left_360",
        capability="image_to_video",
        camera_pose="Anti Clockwise",
        prompt_fragment="slow 3d orbit around the subject",
        speed=1.0,
        length=81,
        param_map=(("cfg", "6"), ("motion_bucket", "127")),
        pose_trajectory=((0.0, 0.5, 0.5, 0.5, 0.5),),
    )
    req = to_wan_request(s, start_image_url="r2://a.png", prompt="A hero shot", aspect_ratio="9:16")
    assert req["capability"] == "image_to_video"
    assert req["prompt"] == "A hero shot. slow 3d orbit around the subject"
    assert req["start_image_url"] == "r2://a.png"
    assert req["aspect_ratio"] == "9:16"
    assert req["num_frames"] == 81
    assert req["estimated_seconds"] == max(1, round(81 / 16))
    cam = req["camera"]
    assert cam["camera_pose"] == "Anti Clockwise"
    assert cam["length"] == 81 and cam["width"] == 832 and cam["height"] == 480
    assert cam["pose_trajectory"] == [[0.0, 0.5, 0.5, 0.5, 0.5]]
    # param_map is merged flat into the camera dict.
    assert cam["cfg"] == "6" and cam["motion_bucket"] == "127"


def test_to_wan_request_prompt_trims_when_empty():
    s = CameraControlSpec(
        preset_id="p", capability="image_to_video", camera_pose="Zoom In",
        prompt_fragment="push in",
    )
    assert to_wan_request(s, prompt="").get("prompt") == "push in"


# --------------------------------------------------------------------------- #
# Compiler — every preset compiles to a valid MotionPlan
# --------------------------------------------------------------------------- #
def _all_ids():
    return [m["id"] for m in catalog.list_motions()]


@pytest.mark.parametrize("pid", _all_ids())
def test_every_preset_compiles(pid):
    plan = compiler.compile_motion(pid, intensity=50)
    assert isinstance(plan, MotionPlan)
    assert plan.preset_id == pid
    assert plan.motion_class == catalog.get_motion(pid)["render_class"]
    if plan.motion_class == "filter":
        assert plan.filter is not None and plan.model is None
    elif plan.motion_class == "model":
        assert plan.model is not None and plan.filter is None
    else:  # hybrid carries BOTH the model spec and the deterministic FFmpeg fallback
        assert plan.model is not None and plan.filter is not None


@pytest.mark.parametrize(
    "pid",
    [m["id"] for m in catalog.list_motions() if m["render_class"] == "filter" and m["id"] != "none"],
)
def test_filter_presets_emit_nonempty_fragment(pid):
    plan = compiler.compile_motion(pid, intensity=60)
    frags = vfx.build_vfx_filters(
        plan.filter.camera_motion, list(plan.filter.effects), intensity=plan.filter.intensity
    )
    assert frags, f"filter preset {pid} produced no FFmpeg fragment"
    assert all(f and isinstance(f, str) for f in frags)


def test_identity_none_preset_emits_nothing():
    plan = compiler.compile_motion("none", intensity=50)
    assert plan.motion_class == "filter"
    assert vfx.build_vfx_filters(plan.filter.camera_motion, list(plan.filter.effects)) == []


@pytest.mark.parametrize(
    "pid",
    [m["id"] for m in catalog.list_motions() if m["render_class"] in ("model", "hybrid")],
)
def test_model_presets_emit_wellformed_spec(pid):
    plan = compiler.compile_motion(pid, intensity=50)
    m = plan.model
    assert isinstance(m, CameraControlSpec)
    assert m.preset_id == pid
    assert m.capability in _CAPS
    assert m.camera_pose in _ALL_POSES
    assert m.prompt_fragment.strip()
    assert 0.0 <= m.speed <= 10.0
    assert m.length >= 5 and (m.length - 1) % 4 == 0
    assert m.width % 16 == 0 and m.height % 16 == 0
    assert m.provider_hints and m.provider_hints[0] == "wan_camera"
    assert m.license_class in spec.PAID_SAFE_LICENSES
    # param_map is a hashable, sorted tuple of str/str pairs.
    assert isinstance(m.param_map, tuple)
    assert list(m.param_map) == sorted(m.param_map)
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in m.param_map)
    # Custom poses must ship a real trajectory; each row carries the full 23 floats.
    if m.camera_pose == "Custom":
        assert m.pose_trajectory, f"{pid}: Custom pose needs a trajectory"
        for row in m.pose_trajectory:
            assert len(row) == 23
            assert all(isinstance(x, float) for x in row)
    # to_wan_request round-trips into a valid provider payload.
    req = to_wan_request(m, start_image_url="r2://x.png", prompt="hi")
    assert req["num_frames"] == m.length


def test_hybrid_fallback_fragment_renders():
    hybrids = [m["id"] for m in catalog.list_motions() if m["render_class"] == "hybrid"]
    assert hybrids, "expected at least one hybrid preset"
    for pid in hybrids:
        plan = compiler.compile_motion(pid, intensity=50)
        frags = vfx.build_vfx_filters(plan.filter.camera_motion, list(plan.filter.effects))
        assert frags, f"hybrid {pid} FFmpeg fallback must render"


# --------------------------------------------------------------------------- #
# Compiler — determinism, clamping, validation
# --------------------------------------------------------------------------- #
def test_compile_is_deterministic():
    a = compiler.compile_motion("orbit_left_360", intensity=70)
    b = compiler.compile_motion("orbit_left_360", intensity=70)
    assert a == b


@pytest.mark.parametrize("raw, clamped", [(-20, 0), (0, 0), (50, 50), (100, 100), (250, 100)])
def test_intensity_is_clamped(raw, clamped):
    plan = compiler.compile_motion("dolly_in", intensity=raw)
    assert plan.filter.intensity == clamped


def test_compile_unknown_raises():
    with pytest.raises(MotionPresetError):
        compiler.compile_motion("totally_unknown_move")


# --------------------------------------------------------------------------- #
# Frozen dataclasses — immutability guarantee
# --------------------------------------------------------------------------- #
def test_dataclasses_are_frozen():
    fp = FilterPlan(camera_motion="dolly_in")
    with pytest.raises(dataclasses.FrozenInstanceError):
        fp.camera_motion = "x"  # type: ignore[misc]
    mp = MotionPlan(preset_id="none", motion_class="filter", filter=fp)
    with pytest.raises(dataclasses.FrozenInstanceError):
        mp.motion_class = "model"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# vfx.py reconciliation — new fragments, aliases, model guard, no regressions
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "pid, needle",
    [
        ("ken_burns_fx", "zoompan"),
        ("slow_zoom_in", "zoompan"),
        ("slow_zoom_out", "zoompan"),
        ("zoom_punch_in", "zoompan"),
        ("zoom_punch_out", "zoompan"),
        ("dutch_left", "rotate"),
        ("dutch_right", "rotate"),
        ("drift_left", "crop"),
        ("drift_right", "crop"),
        ("handheld_shake", "crop"),
        ("speed_ramp", "setpts"),
        ("vignette_punch", "vignette"),
    ],
)
def test_new_camera_fragments_render(pid, needle):
    frags = vfx.build_vfx_filters(pid, [], intensity=50)
    assert len(frags) == 1 and needle in frags[0]


@pytest.mark.parametrize(
    "alias, canonical",
    [
        ("rack_focus", "focus_change"),
        ("bullet_time_hold", "bullet_time"),
        ("orbit_360_fake", "orbit_360"),
        ("fpv_drone_shake", "fpv_drone"),
    ],
)
def test_filter_aliases_resolve_to_canonical_output(alias, canonical):
    assert vfx.build_vfx_filters(alias, [], intensity=50) == vfx.build_vfx_filters(
        canonical, [], intensity=50
    )
    assert vfx.build_vfx_filters(alias, [], intensity=50), "alias must render"


@pytest.mark.parametrize("legacy_id", ["ken_burns", "push_in", "pull_out"])
def test_legacy_precompose_ids_emit_no_compose_fragment(legacy_id):
    # Owned by the pre-compose editing pass — the compose VFX path must stay
    # silent so the move is never applied twice.
    assert vfx.build_vfx_filters(legacy_id, [], intensity=50) == []


@pytest.mark.parametrize(
    "pid, resolved",
    [("push_in", "dolly_in"), ("pull_out", "dolly_out"), ("ken_burns", "ken_burns_fx")],
)
def test_motion_catalog_reconciles_legacy_ids_to_compose_safe_fragments(pid, resolved):
    # The MOTION engine routes these through compose-safe ids so path A renders.
    plan = compiler.compile_motion(pid, intensity=50)
    assert plan.filter.camera_motion == resolved
    assert vfx.build_vfx_filters(plan.filter.camera_motion, [], intensity=50)


def test_glow_bloom_maps_to_glow_effect_not_geometry():
    # glow_bloom compiles to an effect (look), never a camera geometry fragment.
    plan = compiler.compile_motion("glow_bloom", intensity=50)
    assert "glow" in plan.filter.effects
    frags = vfx.build_vfx_filters(plan.filter.camera_motion, list(plan.filter.effects))
    assert any("gblur" in f for f in frags)


@pytest.mark.parametrize(
    "model_id",
    ["orbit_left_360", "arc_left", "drone_flythrough", "dolly_zoom_vertigo", "robo_arm"],
)
def test_model_only_ids_never_emit_geometry(model_id):
    # A stray model-only id fed to the FILTER path must produce NO fragment.
    assert vfx.build_vfx_filters(model_id, [], intensity=50) == []


def test_existing_camera_ids_unchanged():
    # Regression guard: legacy filter ids keep byte-identical output.
    assert vfx.build_vfx_filters("dolly_in", [], intensity=50) == [
        vfx._zoompan_in((0.0008 + 0.004 * 0.5) * 0.5, 1.12, 1080, 1920, 30)
    ]
    assert vfx.build_vfx_filters("none", ["glow"], intensity=50)[0].startswith("gblur=sigma=3")


# --------------------------------------------------------------------------- #
# Service layer — pure orchestration view
# --------------------------------------------------------------------------- #
def test_service_resolve_for_render_view():
    view = service.resolve_for_render("orbit_left_360", intensity=50)
    assert view["preset_id"] == "orbit_left_360"
    assert view["motion_class"] == "model"
    assert view["model"]["camera_pose"] == "Anti Clockwise"


def test_service_list_and_get():
    assert service.get_motion("dolly_in")["id"] == "dolly_in"
    assert len(service.list_motions()) >= 50
