"""Compose-stage VFX render — pure filtergraph fragments + splice + validation.

Covers the "selectable -> rendered" crossing for the Higgsfield-class camera
motion + Effects-Mix catalog (``app.domains.catalog.presets``):

  * PURE fragment builder (``app.services.compose.vfx``) — each renderable preset
    maps to a VALID FFmpeg filter fragment; overlay-class VFX are cleanly skipped
    (never a fake filter); intensity scales strength; ``build_vfx_node`` labels.
  * Compose SPLICE — ``compose_avatar_over_screen`` inserts the VFX node between
    ``[comp]`` and the caption burn so captions render ON TOP (subprocess mocked).
  * DTO VALIDATION — ``camera_motion`` accepts both the legacy pre-compose presets
    and the new catalog ids; ``effects`` is validated/capped; unknowns are 422.
"""

from __future__ import annotations

import pytest

from app.services.compose import compose_ffmpeg as cf
from app.services.compose import vfx


# --------------------------------------------------------------------------- #
# Pure fragment builder — filter-class VFX emit REAL fragments
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "eid, needle",
    [
        ("glitch", "rgbashift"),
        ("datamosh", "tblend"),
        ("light_leak", "curves"),
        ("film_burn", "curves"),
        ("glow", "gblur"),
    ],
)
def test_filter_class_vfx_emit_real_fragments(eid, needle):
    frags = vfx.build_vfx_filters("none", [eid], intensity=50)
    assert len(frags) == 1
    assert needle in frags[0]
    # A fragment is a bare filter chain — never a dangling label or empty.
    assert frags[0] and "[" not in frags[0]


@pytest.mark.parametrize(
    "eid",
    ["explosion", "disintegration", "earth_zoom", "smoke", "rain", "snow", "confetti", "shockwave"],
)
def test_overlay_class_vfx_are_skipped_not_faked(eid):
    # Overlay/generative effects need real assets — the pure builder must emit
    # NOTHING for them (a fake filter would be a lie), deferring to the overlay
    # pipeline. The node is therefore empty and reads straight from the input.
    assert vfx.build_vfx_filters("none", [eid], intensity=50) == []
    node, label = vfx.build_vfx_node("none", [eid], in_label="comp")
    assert node == ""
    assert label == "comp"


def test_filter_class_membership_matches_renderable_set():
    for eid in vfx.FILTER_CLASS_VFX:
        assert vfx.build_vfx_filters("none", [eid], intensity=50), eid


# --------------------------------------------------------------------------- #
# Pure fragment builder — camera moves (catalog ids) render real geometry
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "cam, needle",
    [
        ("dolly_in", "zoompan"),
        ("crash_zoom_in", "zoompan"),
        ("dolly_out", "zoompan"),
        ("crash_zoom_out", "zoompan"),
        ("orbit_360", "rotate"),
        ("fpv_drone", "rotate"),
        ("dutch_angle", "rotate"),
        ("pan_left", "crop"),
        ("truck_right", "crop"),
        ("tilt_up", "crop"),
        ("crane_down", "crop"),
        ("bullet_time", "crop"),
        ("whip_pan", "crop"),
        ("hyperlapse", "setpts"),
        ("focus_change", "gblur"),
    ],
)
def test_camera_moves_render_real_fragments(cam, needle):
    frags = vfx.build_vfx_filters(cam, None, intensity=60)
    assert len(frags) == 1
    assert needle in frags[0]


def test_none_camera_and_no_effects_is_empty_node():
    assert vfx.build_vfx_filters("none", None) == []
    assert vfx.build_vfx_filters("", []) == []
    node, label = vfx.build_vfx_node("none", None, in_label="comp")
    assert node == ""
    assert label == "comp"


def test_camera_first_then_vfx_ordering():
    frags = vfx.build_vfx_filters("dolly_in", ["glitch"], intensity=50)
    assert len(frags) == 2
    assert "zoompan" in frags[0]  # camera geometry first
    assert "rgbashift" in frags[1]  # look second


def test_build_vfx_node_labels_and_chains():
    node, label = vfx.build_vfx_node("dolly_in", ["glitch"], in_label="comp", out_label="cfx")
    assert label == "cfx"
    assert node.startswith(";[comp]")
    assert node.endswith("[cfx]")
    # The two fragments are comma-joined into ONE chain between the labels.
    assert node.count("[comp]") == 1 and node.count("[cfx]") == 1
    inner = node[len(";[comp]") : -len("[cfx]")]
    assert "," in inner  # camera,vfx


def test_overlay_effects_dropped_but_filter_effects_kept():
    # A mixed stack renders only its filter-class members; overlay-class silently
    # deferred (logged), never faked — so exactly one fragment survives here.
    frags = vfx.build_vfx_filters("none", ["explosion", "glitch", "rain"], intensity=50)
    assert len(frags) == 1
    assert "rgbashift" in frags[0]


def test_intensity_scales_effect_strength():
    low = vfx.build_vfx_filters("none", ["glitch"], intensity=0)[0]
    high = vfx.build_vfx_filters("none", ["glitch"], intensity=100)[0]
    # Zero intensity is the gentlest shift (rh=2); full intensity is stronger.
    assert "rh=2:" in low
    assert "rh=6:" in high


# --------------------------------------------------------------------------- #
# Compose splice — VFX node sits between [comp] and the caption burn
# --------------------------------------------------------------------------- #
class _FakeCompleted:
    def __init__(self, returncode=0, stderr="", stdout=""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout


@pytest.fixture
def compose_inputs(tmp_path):
    screen = tmp_path / "screen.mp4"
    avatar = tmp_path / "avatar.mp4"
    audio = tmp_path / "audio.mp3"
    for p in (screen, avatar, audio):
        p.write_bytes(b"\x00")
    return {
        "screen_path": str(screen),
        "avatar_path": str(avatar),
        "audio_path": str(audio),
        "output_file": str(tmp_path / "out.mp4"),
    }


def _capture_filtergraph(monkeypatch, compose_inputs, **kwargs) -> str:
    captured = {}

    def fake_run(cmd, capture_output=False, text=False, check=False):
        captured["cmd"] = cmd
        return _FakeCompleted(0)

    monkeypatch.setattr(cf.subprocess, "run", fake_run)
    monkeypatch.setattr(cf.video_service, "_get_effective_video_codec", lambda: cf._LIBX264)
    monkeypatch.setattr(cf, "ffmpeg_has_filter", lambda name, ffmpeg=None: True)
    cf.compose_avatar_over_screen(layout="pip", **compose_inputs, **kwargs)
    cmd = captured["cmd"]
    return cmd[cmd.index("-filter_complex") + 1]


def test_compose_splices_vfx_between_comp_and_final(compose_inputs, tmp_path, monkeypatch):
    ass = tmp_path / "cap.ass"
    ass.write_text("x", encoding="utf-8")
    fg = _capture_filtergraph(
        monkeypatch, compose_inputs, ass_path=str(ass), camera_motion="dolly_in", effects=["glitch"]
    )
    # VFX node consumes [comp] and emits [cfx]; captions burn on [cfx] -> [final].
    assert ";[comp]" in fg
    assert "[cfx]" in fg
    assert ";[cfx]ass=" in fg
    assert fg.endswith("[final]")
    # Order: the effects appear BEFORE the caption burn (rendered underneath).
    assert fg.index("rgbashift") < fg.index("ass=")


def test_compose_without_effects_is_classic_graph(compose_inputs, monkeypatch):
    fg = _capture_filtergraph(monkeypatch, compose_inputs)
    # No selection => no VFX node; caption passthrough reads straight from [comp].
    assert "[cfx]" not in fg
    assert ";[comp]null[final]" in fg


def test_compose_overlay_only_effects_add_no_node(compose_inputs, monkeypatch):
    fg = _capture_filtergraph(monkeypatch, compose_inputs, effects=["explosion", "rain"])
    # Overlay-class effects are deferred; the compose graph is byte-identical to
    # the no-VFX path (no [cfx] relabel).
    assert "[cfx]" not in fg
    assert ";[comp]null[final]" in fg


def test_legacy_camera_preset_renders_no_compose_fragment(compose_inputs, monkeypatch):
    # ken_burns is owned by the pre-compose editing pass, so the compose VFX node
    # emits nothing for it (no double application).
    fg = _capture_filtergraph(monkeypatch, compose_inputs, camera_motion="ken_burns")
    assert "[cfx]" not in fg


# --------------------------------------------------------------------------- #
# DTO validation — one field, two rendering systems both accepted
# --------------------------------------------------------------------------- #
def test_schema_camera_motion_accepts_legacy_and_catalog():
    from app.models.schema import _validate_camera_motion

    assert _validate_camera_motion(None) is None
    assert _validate_camera_motion("") == "none"
    # Legacy pre-compose editing preset.
    assert _validate_camera_motion("ken_burns") == "ken_burns"
    # New Higgsfield-class catalog move.
    assert _validate_camera_motion("dolly_in") == "dolly_in"
    with pytest.raises(ValueError):
        _validate_camera_motion("teleport")


def test_schema_effects_validate_and_cap():
    from app.models.schema import _validate_effects

    assert _validate_effects(None) is None
    assert _validate_effects(["glitch", "glitch", "rain"]) == ["glitch", "rain"]
    with pytest.raises(ValueError):
        _validate_effects(["not_a_vfx"])
    with pytest.raises(ValueError):
        _validate_effects(["explosion", "smoke", "rain", "snow", "glitch"])  # 5 > cap


def test_job_create_request_accepts_effects_and_catalog_camera():
    from app.models.schema import JobCreateRequest

    req = JobCreateRequest(
        video_subject="x",
        camera_motion="orbit_360",
        effects=["glitch", "light_leak"],
        vfx_intensity=70,
    )
    assert req.camera_motion == "orbit_360"
    assert req.effects == ["glitch", "light_leak"]
    assert req.vfx_intensity == 70
