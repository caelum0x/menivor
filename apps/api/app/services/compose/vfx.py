"""Real FFmpeg filtergraph fragments for camera-motion + VFX presets.

Turns the reviewed presets (``app.domains.catalog.presets``) into **valid FFmpeg
filter fragments** spliced into the compose graph between ``[comp]`` and the
caption burn, so effects render under the captions. Pure + unit-testable — no
subprocess here; the compose stage assembles and runs the command.

Two classes of preset:

* **filter-class** — renderable now with pure filters (``zoompan``/``rotate``/
  ``crop``/``setpts`` for camera moves; ``rgbashift``/``noise``/``tblend``/
  ``curves``/``vignette``/``gblur`` for VFX). Emitted as real fragments.
* **overlay-class** — explosion/confetti/rain… need generative overlay assets;
  they are cleanly SKIPPED here (a fake filter is never emitted) and handled by a
  separate overlay pipeline.

Intensity (0..100) scales each effect's strength.

Shared kernel math (``reelforge_effects_core``)
----------------------------------------------
The camera/VFX *curves* are owned by ``packages/effects-core`` — pure kernels
(``push_in`` / ``ken_burns`` / ``handheld`` / ``rgb_split`` / ``film_grain``)
that the live preview (web + mobile) samples numerically. This module renders the
**same** kernels as FFmpeg filter expressions via ``reelforge_effects_core.ffexpr``
so a rendered frame carries the exact value the preview showed (frame-accurate
parity, proven by ``packages/effects-core/test/test_ffexpr.py``).

The kernel-backed camera moves use the per-frame ``scale=...:eval=frame`` /
``crop`` / ``rotate`` technique (mirroring ``services/editing/motion.py``, which
is safer than ``zoompan`` for VFR screen recordings), so they need the clip
``duration_s`` to build the normalized-time progress term. When the duration is
unknown (legacy callers that don't pass it), the previous self-contained
``zoompan``/``sin`` fragments are emitted unchanged — no regression.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

try:  # Shared kernel math — the effect picker / preview and this render path agree.
    from reelforge_effects_core import ffexpr, kernels
except ModuleNotFoundError:  # monorepo path dep, not pip-installed (mirrors render-core)
    import sys as _sys
    from pathlib import Path as _Path

    _EFFECTS_CORE = (
        _Path(__file__).resolve().parents[5] / "packages" / "effects-core" / "python"
    )
    if str(_EFFECTS_CORE) not in _sys.path:
        _sys.path.insert(0, str(_EFFECTS_CORE))
    from reelforge_effects_core import ffexpr, kernels

# --------------------------------------------------------------------------- #
# Camera moves — each returns a valid filter fragment for a WxH portrait comp.
# ``k`` is a normalized 0..1 intensity.
# --------------------------------------------------------------------------- #
def _zoompan_in(rate: float, zmax: float, w: int, h: int, fps: int) -> str:
    # Incremental centered zoom-in (zoompan accumulates via the `zoom` var).
    return (
        f"zoompan=z='min(zoom+{rate:.4f},{zmax:.3f})':d=1:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps}"
    )


def _zoompan_out(rate: float, zstart: float, w: int, h: int, fps: int) -> str:
    # Zoom-out from zstart toward 1.0 over input frames (`in` = frame index).
    return (
        f"zoompan=z='max({zstart:.3f}-{rate:.4f}*in,1.0)':d=1:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps}"
    )


def _dutch(k: float) -> str:
    # Slight rotation, pre-scaled + cropped so no black corners show.
    angle = round(0.03 + 0.09 * k, 4)  # ~1.7°..6.9°
    return f"scale=iw*1.12:-1,rotate={angle}:ow=iw:oh=ih:c=black,crop=in_w/1.12:in_h/1.12"


def _pan_x(direction: int, k: float) -> str:
    # Horizontal drift via a time-varying crop over a slightly upscaled frame.
    amp = round(0.02 + 0.06 * k, 4)
    return (
        f"scale=iw*1.1:ih*1.1,"
        f"crop=w=iw/1.1:h=ih/1.1:x='(iw-iw/1.1)/2+{direction}*{amp}*iw*sin(t)':y='(ih-ih/1.1)/2'"
    )


def _drift_y(direction: int, k: float) -> str:
    amp = round(0.02 + 0.06 * k, 4)
    return (
        f"scale=iw*1.1:ih*1.1,"
        f"crop=w=iw/1.1:h=ih/1.1:x='(iw-iw/1.1)/2':y='(ih-ih/1.1)/2+{direction}*{amp}*ih*sin(t)'"
    )


# --------------------------------------------------------------------------- #
# Wave-1 additions (MOTION-owned). New pure-FFmpeg camera fragments + an alias
# table that reconciles legacy/preset ids onto canonical camera moves. Existing
# ids keep byte-identical output (aliases only ADD resolutions for ids that were
# previously unknown / not handled).
# --------------------------------------------------------------------------- #

# Legacy / catalog preset ids -> the canonical vfx id whose fragment they render.
# Applied at the top of ``_camera_fragment`` so a template that stored an alias
# id renders the intended move. ``glow_bloom`` maps to the ``glow`` VFX look
# (an effect, not geometry) so it emits nothing on the camera path.
#
# NOTE (ownership split): ``push_in`` / ``pull_out`` / ``ken_burns`` are NOT aliased
# here — they are owned by the LEGACY pre-compose editing pass
# (``app.services.reelforge._apply_motion`` -> ``app.services.editing.motion``),
# which bakes them into the screen recording BEFORE compose. Emitting a compose
# fragment for those bare ids would double-apply the move. The MOTION catalog
# reconciles them at the CATALOG level instead (push_in->dolly_in, pull_out->
# dolly_out, ken_burns->ken_burns_fx) so the compose path renders a NON-colliding
# fragment while the bare legacy ids keep their pre-compose ownership.
FILTER_ALIAS: dict[str, str] = {
    "rack_focus": "focus_change",
    "bullet_time_hold": "bullet_time",
    "orbit_360_fake": "orbit_360",
    "fpv_drone_shake": "fpv_drone",
    "glow_bloom": "glow",
}

# Ids the legacy pre-compose editing pass owns — the compose VFX path renders
# NOTHING for these so each move is applied exactly once (guards the golden
# "no double application" contract). Mirrors ``reelforge._LEGACY_MOTION_PRESETS``.
_LEGACY_PRECOMPOSE_IDS: frozenset[str] = frozenset({"ken_burns", "push_in", "pull_out"})

# Model-only (Wan camera-control) preset ids that must NEVER emit FFmpeg geometry:
# a stray model id fed to the filter path returns None instead of a fake 2D move.
MODEL_ONLY_CAMERA_IDS: frozenset[str] = frozenset(
    {
        "orbit_left_360", "orbit_right_360", "arc_left", "arc_right",
        "product_360_spin", "bullet_time_freeze", "robo_arm", "drone_flythrough",
        "drone_orbit", "flyover", "dolly_zoom_vertigo", "crane_up_reveal",
        "crane_down_reveal", "pan_up_reveal", "pan_down_reveal", "pan_left_parallax",
        "pan_right_parallax", "zoom_in_parallax", "zoom_out_reveal",
        "push_in_parallax", "pull_back_reveal", "diagonal_pan_up_left",
        "diagonal_pan_down_right", "spiral_ascend", "through_object", "snorricam",
        "handheld_follow", "crash_zoom_3d", "orbit_hero", "vertigo_hybrid",
    }
)


def _ken_burns(k: float, w: int, h: int, fps: int) -> str:
    # Slow continuous zoom-in with a gentle diagonal pan (classic Ken Burns).
    rate = round(0.0006 + 0.0015 * k, 5)
    amp = round(0.03 + 0.05 * k, 4)
    return (
        f"zoompan=z='min(zoom+{rate},1.18)':d=1:"
        f"x='iw/2-(iw/zoom/2)+{amp}*iw*sin(on/120)':"
        f"y='ih/2-(ih/zoom/2)+{amp}*ih*sin(on/160)':s={w}x{h}:fps={fps}"
    )


def _vignette_punch(rate: float, w: int, h: int, fps: int) -> str:
    # Zoom-in with a tightening vignette closing in on the subject.
    return _zoompan_in(rate, 1.25, w, h, fps) + ",vignette=PI/5:mode=backward"


def _handheld(k: float) -> str:
    # Subtle organic handheld jitter via a small time-varying crop.
    amp = round(0.006 + 0.014 * k, 4)
    return (
        f"scale=iw*1.08:ih*1.08,"
        f"crop=w=iw/1.08:h=ih/1.08:x='(iw-iw/1.08)/2+{amp}*iw*sin(t*6)':"
        f"y='(ih-ih/1.08)/2+{amp}*ih*cos(t*7)'"
    )


def _dutch_dir(k: float, direction: int) -> str:
    # Directional Dutch tilt (left = negative lean, right = positive).
    angle = round((0.03 + 0.09 * k) * direction, 4)
    return f"scale=iw*1.12:-1,rotate={angle}:ow=iw:oh=ih:c=black,crop=in_w/1.12:in_h/1.12"


def _speed_ramp(k: float) -> str:
    # Variable-speed ramp: setpts oscillates the playback rate over frame index N.
    depth = round(0.3 + 0.4 * k, 3)
    return f"setpts='PTS/(1.5+{depth}*sin(N/40))'"


# --------------------------------------------------------------------------- #
# Kernel-backed camera fragments (reelforge_effects_core parity).
#
# These render the shared effects-core kernels as per-frame FFmpeg expressions so
# the executed frame matches the preview exactly. They build a ``scale=eval=frame``
# up-scale + ``crop`` back to the comp size (mirroring services/editing/motion.py),
# driven by the kernel curve; a normalized-time progress term ``(t/duration)``
# feeds ``ffexpr``. ``duration_s`` must be > 0 (compose passes the clip duration);
# the caller falls back to the self-contained fragments when it is unknown.
#
# The vfx preset id -> effects-core kernel id map is the single source of truth
# for which moves share math with the preview.
KERNEL_BY_PRESET: dict[str, str] = {
    "slow_zoom_in": "push-in",
    "dolly_in": "push-in",
    "ken_burns_fx": "ken-burns",
    "handheld_shake": "handheld",
}


def _progress_expr(duration_s: float) -> str:
    # Normalized clip time 0..1 for the ffexpr easing (clamped inside ffexpr).
    d = duration_s if duration_s and duration_s > 0 else 1.0
    return f"(t/{d:.6g})"


def _scale_crop(zoom_expr: str, crop_x: str, crop_y: str, w: int, h: int) -> str:
    # Per-frame up-scale (rounded UP to an even size so it always covers the crop
    # window) then crop back to WxH. ``setsar=1`` pins the pixel aspect so the
    # fragment drops straight back into the compose graph.
    scaled_w = f"ceil({w}*{zoom_expr}/2)*2"
    scaled_h = f"ceil({h}*{zoom_expr}/2)*2"
    return (
        f"scale=w='{scaled_w}':h='{scaled_h}':eval=frame,"
        f"crop={w}:{h}:x='{crop_x}':y='{crop_y}',setsar=1"
    )


def _kernel_push_in(intensity: float, w: int, h: int, duration_s: float) -> str:
    # Eased centred zoom-in — mirrors kernels.push_in.
    z = ffexpr.push_in_zoom_expr(_progress_expr(duration_s), intensity=intensity)
    return _scale_crop(z, "(in_w-out_w)/2", "(in_h-out_h)/2", w, h)


def _kernel_ken_burns(
    k: float, w: int, h: int, duration_s: float
) -> str:
    # Linear pan + zoom over the frame — mirrors kernels.ken_burns. The kernel's
    # normalized pan (x,y) is mapped to pixels and clamped inside the crop room.
    tn = _progress_expr(duration_s)
    kb = ffexpr.ken_burns_expr(
        tn, zoom=0.08 + 0.10 * k, pan_x=0.04 + 0.06 * k, pan_y=0.03 + 0.04 * k
    )
    crop_x = f"clip((in_w-out_w)/2+({kb.x})*{w},0,in_w-out_w)"
    crop_y = f"clip((in_h-out_h)/2+({kb.y})*{h},0,in_h-out_h)"
    return _scale_crop(kb.zoom, crop_x, crop_y, w, h)


def _kernel_handheld(intensity: float, w: int, h: int, duration_s: float) -> str:
    # Deterministic micro-shake (dx, dy, rot) — mirrors kernels.handheld. A small
    # constant up-scale opens room for the translation + rotation so no edge shows.
    tn = _progress_expr(duration_s)
    hh = ffexpr.handheld_expr(tn, intensity=intensity, seed=1)
    margin = 1.0 + 4.0 * intensity  # covers max |dx|/|dy| plus the tiny rotation
    scaled_w = f"ceil({w}*{margin:.6g}/2)*2"
    scaled_h = f"ceil({h}*{margin:.6g}/2)*2"
    return (
        f"scale=w='{scaled_w}':h='{scaled_h}':eval=frame,"
        f"rotate='{hh.rot}':ow=iw:oh=ih:c=black,"
        f"crop={w}:{h}:"
        f"x='clip((in_w-out_w)/2+({hh.dx})*{w},0,in_w-out_w)':"
        f"y='clip((in_h-out_h)/2+({hh.dy})*{h},0,in_h-out_h)',setsar=1"
    )


def _kernel_camera_fragment(
    pid: str, k: float, w: int, h: int, duration_s: float
) -> str | None:
    """Kernel-backed fragment for ``pid`` when a valid ``duration_s`` is known."""
    if pid == "slow_zoom_in":
        return _kernel_push_in(0.04 + 0.06 * k, w, h, duration_s)
    if pid == "dolly_in":
        return _kernel_push_in(0.06 + 0.06 * k, w, h, duration_s)
    if pid == "ken_burns_fx":
        return _kernel_ken_burns(k, w, h, duration_s)
    if pid == "handheld_shake":
        return _kernel_handheld(0.006 + 0.014 * k, w, h, duration_s)
    return None


def _camera_fragment(
    pid: str, k: float, w: int, h: int, fps: int, duration_s: float | None = None
) -> str | None:
    # Reconcile legacy/preset ids onto canonical moves BEFORE dispatch (additive:
    # existing canonical ids are absent from FILTER_ALIAS so their output is
    # unchanged).
    pid = FILTER_ALIAS.get(pid, pid)
    rate = 0.0008 + 0.004 * k  # zoom speed grows with intensity
    if pid in ("none", ""):
        return None
    # Guard: legacy pre-compose-owned ids never emit a compose fragment (the
    # move is baked into the screen recording upstream — no double application).
    if pid in _LEGACY_PRECOMPOSE_IDS:
        return None
    # Guard: model-only camera-control ids never emit synthetic 2D geometry.
    if pid in MODEL_ONLY_CAMERA_IDS:
        return None
    # --- Shared effects-core kernels (frame-accurate with the preview) ----- #
    # When the clip duration is known, render the preset from its effects-core
    # kernel so the executed frame matches the numeric preview exactly. Without a
    # duration the normalized-time term can't be built, so we fall through to the
    # self-contained fragments below (unchanged legacy behaviour).
    if duration_s and duration_s > 0 and pid in KERNEL_BY_PRESET:
        kernel_frag = _kernel_camera_fragment(pid, k, w, h, duration_s)
        if kernel_frag:
            return kernel_frag
    # --- Wave-1 new fragments --------------------------------------------- #
    if pid == "ken_burns_fx":
        # The MOTION catalog's ken_burns preset renders here (compose path);
        # the bare legacy ``ken_burns`` id stays pre-compose-owned above.
        return _ken_burns(k, w, h, fps)
    if pid == "slow_zoom_in":
        return _zoompan_in(rate * 0.3, 1.10, w, h, fps)
    if pid == "slow_zoom_out":
        return _zoompan_out(rate * 0.3, 1.10, w, h, fps)
    if pid == "zoom_punch_in":
        return _zoompan_in(rate * 2.2, 1.60, w, h, fps)
    if pid == "zoom_punch_out":
        return _zoompan_out(rate * 2.2, 1.60, w, h, fps)
    if pid == "dutch_left":
        return _dutch_dir(k, -1)
    if pid == "dutch_right":
        return _dutch_dir(k, 1)
    if pid == "drift_left":
        return _pan_x(-1, k * 0.5)
    if pid == "drift_right":
        return _pan_x(1, k * 0.5)
    if pid == "handheld_shake":
        return _handheld(k)
    if pid == "speed_ramp":
        return _speed_ramp(k)
    if pid == "vignette_punch":
        return _vignette_punch(rate, w, h, fps)
    # --- Existing fragments (unchanged output) ---------------------------- #
    if pid == "dolly_in":
        return _zoompan_in(rate * 0.5, 1.12, w, h, fps)
    if pid == "crash_zoom_in":
        return _zoompan_in(rate * 1.6, 1.45, w, h, fps)
    if pid == "dolly_out":
        return _zoompan_out(rate * 0.5, 1.12, w, h, fps)
    if pid == "crash_zoom_out":
        return _zoompan_out(rate * 1.6, 1.45, w, h, fps)
    if pid == "bullet_time":
        # Hold a constant punch-in (frozen-moment feel).
        return f"scale=iw*1.2:-1,crop={w}:{h}"
    if pid == "dutch_angle":
        return _dutch(k)
    if pid in ("pan_left", "truck_left"):
        return _pan_x(-1, k)
    if pid in ("pan_right", "truck_right"):
        return _pan_x(1, k)
    if pid in ("tilt_up", "crane_up"):
        return _drift_y(-1, k)
    if pid in ("tilt_down", "crane_down"):
        return _drift_y(1, k)
    if pid == "orbit_360":
        # Slow rotation + slight zoom to cover corners.
        return f"scale=iw*1.15:-1,rotate=0.15*sin(t/2):ow=iw:oh=ih:c=black,crop={w}:{h}"
    if pid == "fpv_drone":
        return f"scale=iw*1.15:-1,rotate=0.05*sin(t*4):ow=iw:oh=ih:c=black,crop={w}:{h}"
    if pid == "hyperlapse":
        # Time-compress the composed stream (2x..4x by intensity).
        speed = 2.0 + 2.0 * k
        return f"setpts=PTS/{speed:.2f}"
    if pid == "whip_pan":
        return _pan_x(1, min(1.0, k + 0.4))
    if pid == "focus_change":
        # Rack focus: brief blur over the first ~1.2s. gblur.sigma is a plain
        # float (no per-frame expression), so gate a constant blur with the
        # timeline `enable` expression instead of an unparsable sigma expr.
        return "gblur=sigma=6:steps=1:enable='lte(t,1.2)'"
    # Unknown camera move -> no fragment (validated upstream anyway).
    return None


# --------------------------------------------------------------------------- #
# VFX — filter-class emit real fragments; overlay-class return None (skipped).
# --------------------------------------------------------------------------- #
def _vfx_fragment(pid: str, k: float) -> str | None:
    if pid == "glitch":
        # Chromatic-aberration magnitude sourced from the shared rgb_split kernel.
        # ``rgbashift`` is a constant-per-render filter (a comma-joined single-input
        # chain can't carry a per-frame shift expression), so we render the kernel's
        # PEAK shift (t=0.5) as the constant offset instead of an animated curve.
        shift = int(round(kernels.rgb_split(0.5, intensity=2.0 + 4.0 * k)["shift_px"]))
        return f"rgbashift=rh={shift}:bh=-{shift},noise=alls={int(6 + 10 * k)}:allf=t"
    if pid == "datamosh":
        return "tblend=all_mode=difference128"
    if pid == "light_leak":
        return f"curves=preset=lighter,vignette=PI/{max(3, int(6 - 2 * k))}:mode=backward"
    if pid == "film_burn":
        # Grain amount sourced from the shared film_grain kernel (0..1 fraction ->
        # ffmpeg ``noise=alls`` 0..100); constant strength, not a per-frame curve.
        grain = kernels.film_grain(0.0, intensity=(8.0 + 12.0 * k) / 100.0)["grain"]
        return f"curves=preset=vintage,noise=alls={int(round(grain * 100))}:allf=t,vignette=PI/4"
    if pid == "glow":
        # Single-input bloom look. `blend` needs two inputs and cannot sit in a
        # comma-joined single-input chain, so approximate the screen-blend glow
        # with a blur + gentle brightness/contrast lift.
        return "gblur=sigma=3,eq=brightness=0.06:contrast=1.05"
    # Overlay/generative-class effects need real assets — not a pure filter.
    if pid in ("explosion", "disintegration", "earth_zoom", "smoke", "rain", "snow", "confetti", "shockwave"):
        return None
    return None


# Which VFX ids this module renders as pure filters (the rest are overlay-class).
FILTER_CLASS_VFX = frozenset({"glitch", "datamosh", "light_leak", "film_burn", "glow"})


# --------------------------------------------------------------------------- #
# Grade LUTs (``lut3d``) and the console 480-line degrade.
#
# Shipped looks live in ``apps/api/assets/luts`` (17x17x17 ``.cube`` files made by
# ``tools/luts/make_luts.py``). The effect id is ``lut:<look id>``; an unknown id
# or a missing file emits nothing (logged), never a broken filter. Callers check
# ``ffmpeg_has_filter("lut3d")`` first: some ffmpeg builds lack it.
# --------------------------------------------------------------------------- #
LUT_DIR = Path(__file__).resolve().parents[3] / "assets" / "luts"
LUT_FILES: dict[str, str] = {
    "console-480": "console-480.cube",
    "flash-lookbook": "flash-lookbook.cube",
    "atelier-film": "atelier-film.cube",
}
LUT_EFFECT_PREFIX = "lut:"
CONSOLE_LINES = 480


def lut_path(look_id: str) -> Path | None:
    name = LUT_FILES.get(str(look_id or ""))
    if not name:
        return None
    path = LUT_DIR / name
    return path if path.is_file() else None


def lut_fragment(look_id: str, *, path: str | Path | None = None) -> str | None:
    """``lut3d=file=<escaped path>:interp=tetrahedral`` for a shipped look (``None`` when unknown)."""
    from app.services.compose.compose_ffmpeg import _escape_ass_filter_path

    target = Path(path) if path is not None else lut_path(look_id)
    if target is None:
        logger.info(f"vfx: no shipped LUT for look {look_id!r}; grade skipped")
        return None
    return f"lut3d=file={_escape_ass_filter_path(str(target))}:interp=tetrahedral"


def console_degrade_fragment(width: int = 1080, height: int = 1920, lines: int = CONSOLE_LINES) -> str:
    """Scale down to ``lines`` rows and back up with nearest-neighbour: stair-stepped 480-line edges."""
    low_h = max(2, int(lines))
    low_w = max(2, int(round(low_h * width / height / 2.0)) * 2)
    return f"scale={low_w}:{low_h}:flags=neighbor,scale={int(width)}:{int(height)}:flags=neighbor,setsar=1"


def look_filters(look_id: str, *, width: int = 1080, height: int = 1920, degrade: str = "",
                 lut_available: bool = True) -> list[str]:
    """The grade for a look: the LUT (when the build has ``lut3d``) then the optional console degrade."""
    fragments: list[str] = []
    if look_id:
        if lut_available:
            frag = lut_fragment(look_id)
            if frag:
                fragments.append(frag)
        else:
            logger.info(f"vfx: this ffmpeg has no lut3d filter; {look_id} grade skipped")
    if degrade == "console" or (not degrade and str(look_id).startswith("console")):
        fragments.append(console_degrade_fragment(width, height))
    return fragments


def build_vfx_filters(
    camera_motion: str | None,
    effects: list[str] | None,
    *,
    intensity: int = 50,
    fps: int = 30,
    width: int = 1080,
    height: int = 1920,
    duration_s: float | None = None,
) -> list[str]:
    """Return the ordered list of real FFmpeg filter fragments for a selection.

    Camera move first (geometry), then filter-class VFX (look). Overlay-class VFX
    are skipped here (logged) and rendered by the overlay pipeline.

    ``duration_s`` is the composed clip length. When provided (>0), camera presets
    that map to an ``effects-core`` kernel (see ``KERNEL_BY_PRESET``) render the
    shared kernel curve as per-frame FFmpeg expressions — frame-accurate with the
    preview. When omitted, the self-contained legacy fragments are used unchanged.
    """
    k = max(0.0, min(1.0, int(intensity) / 100.0))
    fragments: list[str] = []

    cam = _camera_fragment(
        str(camera_motion or "none"), k, width, height, fps, duration_s
    )
    if cam:
        fragments.append(cam)

    skipped: list[str] = []
    for eid in effects or []:
        if str(eid).startswith(LUT_EFFECT_PREFIX):
            lut_frags = look_filters(str(eid)[len(LUT_EFFECT_PREFIX):], width=width, height=height)
            if lut_frags:
                fragments.extend(lut_frags)
            else:
                skipped.append(str(eid))
            continue
        frag = _vfx_fragment(str(eid), k)
        if frag:
            fragments.append(frag)
        else:
            skipped.append(str(eid))
    if skipped:
        logger.info(f"vfx: overlay-class effects deferred to overlay pipeline: {skipped}")
    return fragments


def build_vfx_node(
    camera_motion: str | None,
    effects: list[str] | None,
    *,
    in_label: str = "comp",
    out_label: str = "cfx",
    intensity: int = 50,
    fps: int = 30,
    width: int = 1080,
    height: int = 1920,
    duration_s: float | None = None,
) -> tuple[str, str]:
    """Return ``(node, out_label)`` — ``;[in]f1,f2[out]`` or ``('', in_label)``.

    When there are no renderable fragments the node is empty and the input label
    is returned so the caller reads straight from ``[in]`` (no dangling relabel).

    ``duration_s`` (composed clip length) enables the frame-accurate,
    kernel-backed camera fragments — see :func:`build_vfx_filters`.
    """
    fragments = build_vfx_filters(
        camera_motion,
        effects,
        intensity=intensity,
        fps=fps,
        width=width,
        height=height,
        duration_s=duration_s,
    )
    if not fragments:
        return "", in_label
    chain = ",".join(fragments)
    return f";[{in_label}]{chain}[{out_label}]", out_label
