"""Pure template → RenderSpec compiler.

Expands a genre template's segment slots into a concrete, timed
:class:`~app.domains.templates.render_spec.RenderSpec` the composer consumes:

1. resolve the reel duration (clamped to template bounds),
2. scale each slot's fractional timing to absolute seconds, clamped to its
   ``min_s``/``max_s`` and re-normalized so segments tile the timeline with no
   gaps/overlaps,
3. bind user inputs to tracks (narration text, gameplay/B-roll clips),
4. attach caption cues (safe-zone + Hormozi highlight) and a ducked audio bus,
5. carry reel-level camera-motion / VFX / loop / aspect through unchanged.

No DB, no ffmpeg — deterministic and fully unit-testable. The render worker (or
the ``instantiate`` bridge into the existing reel pipeline) executes the result.
"""

from __future__ import annotations

from . import policy
from .definitions import ShotTemplateDef
from .render_spec import (
    AudioCue,
    CaptionCue,
    LoopPlan,
    MediaBinding,
    RenderSpec,
    SegmentSpec,
)
from .slots import SlotSpec

# Which input key feeds the narrated/text foreground of a slot.
_TEXT_INPUT_KEYS = ("story", "topic", "bit", "promise", "angle", "title")
# Which input key provides the secondary/looping visual track.
_CLIP_INPUT_KEYS = ("gameplay_clip", "broll_clip", "trigger_clip", "clips")


def _resolve_durations(template: ShotTemplateDef, total: float) -> list[float]:
    """Scale slot fractions to absolute seconds, honour min/max, re-normalize.

    Fractional widths give the base split; per-slot ``min_s``/``max_s`` clamp the
    absolute duration; any surplus/deficit from clamping is redistributed across
    the unclamped slots proportionally so the segments still sum to ``total``.
    """
    slots = template.slots
    base = [s.duration_frac * total for s in slots]
    clamped = list(base)
    fixed = [False] * len(slots)
    for i, s in enumerate(slots):
        lo = s.min_s
        hi = s.max_s if s.max_s > 0 else float("inf")
        if clamped[i] < lo:
            clamped[i] = lo
            fixed[i] = True
        elif clamped[i] > hi:
            clamped[i] = hi
            fixed[i] = True

    # Redistribute the delta across unclamped slots proportional to their base.
    delta = total - sum(clamped)
    free_idx = [i for i in range(len(slots)) if not fixed[i]]
    free_base = sum(base[i] for i in free_idx)
    if free_idx and abs(delta) > 1e-6 and free_base > 1e-6:
        for i in free_idx:
            clamped[i] += delta * (base[i] / free_base)
    return [round(max(0.1, d), 3) for d in clamped]


def _pick(inputs: dict, keys: tuple[str, ...]) -> str:
    for k in keys:
        v = str(inputs.get(k, "") or "").strip()
        if v:
            return v
    return ""


def _caption_for(
    template: ShotTemplateDef, slot: SlotSpec, text: str, surface: str | None
) -> CaptionCue | None:
    if not slot.caption:
        return None
    zone = policy.safezone_for(surface)
    return CaptionCue(
        text=text,
        style=template.caption_style,
        highlight=policy.HORMOZI_HIGHLIGHT,
        all_caps=True,
        y_frac=zone["y_frac"],
        height_frac=zone["height_frac"],
    )


def _audio_for(slot: SlotSpec, duck: bool) -> tuple[AudioCue, ...]:
    cues: list[AudioCue] = []
    for layer in slot.audio:
        is_fg = layer in ("narration", "dialogue", "trigger")
        cues.append(
            AudioCue(
                layer=layer,
                gain_db=policy.gain_for(layer, ducked=duck and not is_fg),
                ducked=duck and not is_fg,
            )
        )
    return tuple(cues)


def _media_for(slot: SlotSpec, narration_text: str, clip_ref: str, loopable: bool) -> tuple[MediaBinding, ...]:
    bindings: list[MediaBinding] = []
    # The narrated/text-driven surface.
    if narration_text and slot.track in ("primary", "full"):
        bindings.append(MediaBinding(track=slot.track, kind="text", ref=narration_text))
    # The looping companion visual (gameplay / B-roll / trigger clip).
    companion_track = "secondary" if slot.track == "primary" else slot.track
    if clip_ref:
        bindings.append(
            MediaBinding(track=companion_track, kind="clip", ref=clip_ref, loop=loopable)
        )
    return tuple(bindings)


def _identity_lock_for(character, shot_index: int):
    """Build an :class:`IdentityLock` for one segment from a bound character.

    Imported lazily so the templates domain never hard-depends on the characters
    domain (and stays import-safe if it is absent). ``consistency`` returns pure
    primitives; the frozen ``IdentityLock`` is constructed here so the pure
    module never imports ``render_spec`` (no import cycle).
    """
    from app.domains.characters.consistency import build_identity_lock

    from .render_spec import IdentityLock

    f = build_identity_lock(character, shot_index=shot_index)
    return IdentityLock(
        character_id=f.character_id,
        identity_key=f.identity_key,
        seed=f.seed,
        reference_images=tuple(f.reference_images),
        lora_ref=f.lora_ref,
        negative_prompt=f.negative_prompt,
    )


def compile_template(
    template: ShotTemplateDef,
    inputs: dict,
    *,
    duration_s: float,
    surface: str | None = None,
    character=None,
) -> RenderSpec:
    """Compile a template + validated inputs into a :class:`RenderSpec`.

    ``inputs`` must already be validated (see ``validation.validate_inputs``);
    ``duration_s`` must already be within the template bounds (see
    ``validation.validate_duration``).

    When ``character`` (a ``consistency.CharacterProfile``) is bound, each
    segment additionally carries a deterministic :class:`IdentityLock` (per-shot
    seed + reference sheet + LoRA ref + drift-guard negative) so the render
    worker reproduces the same identity. ``character=None`` keeps every existing
    compiled spec byte-identical.
    """
    durations = _resolve_durations(template, duration_s)
    narration = _pick(inputs, _TEXT_INPUT_KEYS)
    clip_ref = _pick(inputs, _CLIP_INPUT_KEYS)
    background_id = ""
    # No user footage → auto-fill the looping companion track from the curated
    # background library (so split-screen / loop formats render without the user
    # sourcing footage). An explicit ``background_id`` input overrides the default.
    if not clip_ref:
        from app.domains.content import background_library as bglib

        chosen = str(inputs.get("background_id", "") or "").strip() or template.default_background
        resolved = bglib.resolve(chosen, genre=template.genre)
        if resolved is not None:
            background_id = resolved.id
            clip_ref = f"lib:{resolved.id}"  # compose stage materializes via bglib.materialize

    segments: list[SegmentSpec] = []
    t = 0.0
    for slot, dur in zip(template.slots, durations):
        t_start = round(t, 3)
        t_end = round(t + dur, 3)
        t = t_end
        identity_lock = (
            _identity_lock_for(character, slot.order) if character is not None else None
        )
        segments.append(
            SegmentSpec(
                role=slot.role,
                order=slot.order,
                t_start=t_start,
                t_end=t_end,
                track=slot.track,
                media=_media_for(slot, narration, clip_ref, template.loopable),
                caption=_caption_for(template, slot, narration, surface),
                audio=_audio_for(slot, template.audio.duck),
                transition_in=slot.transition_in,
                transition_out=slot.transition_out,
                hook_gate=slot.hook_gate,
                label=slot.label,
                identity_lock=identity_lock,
            )
        )

    warnings = _retention_warnings(template, segments, duration_s)
    loop = LoopPlan(enabled=template.loopable) if template.loopable else LoopPlan()

    # Wave-1 motion routing (additive): tag which render path the camera move
    # takes so the worker branches on filter/model/hybrid. Unknown/legacy ids
    # default to the pure-FFmpeg filter path, preserving today's behavior.
    motion_class, motion_preset = _resolve_motion_routing(template.camera_motion)

    return RenderSpec(
        template_slug=template.slug,
        template_version=template.version,
        genre=template.genre,
        aspect=template.aspect,
        layout=template.layout,
        duration_s=round(sum(durations), 3),
        segments=tuple(segments),
        camera_motion=template.camera_motion,
        effects=tuple(template.effects),
        vfx_intensity=template.vfx_intensity,
        caption_style=template.caption_style,
        music_prompt=template.audio.bgm_prompt,
        audio_foreground=template.audio.foreground,
        duck=template.audio.duck,
        trend_relink=template.audio.trend_relink,
        loop=loop,
        background_id=background_id,
        warnings=tuple(warnings),
        motion_class=motion_class,
        motion_preset=motion_preset,
    )


def _resolve_motion_routing(camera_motion: str) -> tuple[str, str]:
    """Map a template ``camera_motion`` id onto its motion render_class + preset.

    Import-safe + total: any failure (or an unknown id) degrades to the pure
    FFmpeg filter path so template compilation never depends on the motion domain.
    """
    try:
        from app.domains.motion import catalog as motion_catalog

        entry = motion_catalog.get_motion(camera_motion)
        if entry is None:
            return "filter", ""
        return entry.get("render_class", "filter"), entry["id"]
    except Exception:  # noqa: BLE001 - motion routing is additive, never fatal
        return "filter", ""


def _retention_warnings(
    template: ShotTemplateDef, segments: list[SegmentSpec], duration_s: float
) -> list[str]:
    """Non-fatal advisories tied to the research-backed retention gates."""
    warnings: list[str] = []
    gate = next((s for s in segments if s.hook_gate), None)
    if gate and gate.t_end > policy.HOOK_WINDOW_S + 0.5:
        warnings.append(
            f"hook slot ends at {gate.t_end}s (> {policy.HOOK_WINDOW_S}s window); "
            "tighten the cold-open to clear the first-3s retention gate"
        )
    if template.loopable and duration_s > policy.LOOP_MAX_DURATION_S and template.genre == "asmr":
        warnings.append(
            f"ASMR loop is {duration_s}s (> {policy.LOOP_MAX_DURATION_S}s); "
            "shorter loops inflate rewatch rate"
        )
    return warnings
