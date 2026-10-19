"""Template engine orchestration — compile + instantiate into the real pipeline.

This is the executable bridge: ``instantiate`` turns a genre template + creator
inputs into a **real** ``JobCreateRequest``-shaped reel draft that flows through
the existing reel pipeline (script → TTS → avatar/captions → compose → upload),
carrying the compiled camera-motion / VFX / caption / layout / music selections.
``compile_spec`` returns the timed :class:`RenderSpec` for preview.

No new DB tables: system templates are code-defined (``presets/``) and the draft
is submitted to the existing ``POST /reels`` create path, so this ships value with
zero migration. The returned draft is validated against ``JobCreateRequest`` so an
invalid template/inputs surface as a clean error before any credit is spent.
"""

from __future__ import annotations

from .compiler import compile_template
from .presets import all_templates, get_template
from .render_spec import RenderSpec
from .validation import TemplateError, validate_duration, validate_inputs


def list_templates() -> tuple:
    """All seeded system templates (curated order)."""
    return all_templates()


def _require(slug: str):
    tmpl = get_template(slug)
    if tmpl is None:
        raise TemplateError(f"unknown template {slug!r}")
    return tmpl


def compile_spec(
    slug: str,
    inputs: dict | None,
    *,
    duration_s: float | None = None,
    surface: str | None = None,
    character=None,
) -> RenderSpec:
    """Validate inputs + compile the template into a timed RenderSpec.

    When ``character`` (a ``consistency.CharacterProfile``) is bound, each segment
    carries a deterministic :class:`IdentityLock` so the render worker reproduces
    the same identity across shots. ``character=None`` is byte-identical to the
    classic compile.
    """
    tmpl = _require(slug)
    duration = validate_duration(tmpl, duration_s)
    clean = validate_inputs(tmpl, inputs)
    return compile_template(tmpl, clean, duration_s=duration, surface=surface, character=character)


def instantiate_draft(
    slug: str,
    inputs: dict | None,
    *,
    duration_s: float | None = None,
    surface: str | None = None,
    character=None,
) -> dict:
    """Produce a pipeline-ready reel draft + the compiled spec for preview.

    Returns ``{"template", "render_spec", "reel_draft"}`` where ``reel_draft`` is a
    ``JobCreateRequest``-shaped dict ready to POST to ``/reels`` create. The draft
    is validated by constructing a ``JobCreateRequest`` so template output can
    never produce an unsubmittable job.

    When ``character`` is bound, the compiled per-segment identity locks are
    carried into the draft (as a ``character`` sidecar the render worker bridges
    into IPAdapter/LoRA conditioning) instead of being discarded, so the bound
    reference + trained LoRA actually reach the provider across every shot.
    """
    tmpl = _require(slug)
    spec = compile_spec(slug, inputs, duration_s=duration_s, surface=surface, character=character)
    clean = validate_inputs(tmpl, inputs)

    # Map the compiled spec onto the real reel-create fields.
    narration = _first(clean, ("story", "topic", "bit", "promise", "angle"))
    subject = _first(clean, ("subject", "title", "character")) or (tmpl.name)
    gameplay_key = _first(clean, ("gameplay_clip", "broll_clip", "trigger_clip"))

    draft: dict = {
        "video_subject": subject,
        "video_script": narration,  # "" => the pipeline's LLM writes the script from the subject
        "layout": tmpl.layout if tmpl.layout in ("pip", "hook_intro", "split") else "pip",
        "caption_style": tmpl.caption_style,
        "camera_motion": tmpl.camera_motion,
        "effects": list(tmpl.effects) or None,
        "vfx_intensity": tmpl.vfx_intensity,
        "music_prompt": tmpl.audio.bgm_prompt,
    }
    if gameplay_key:
        # The looping visual becomes the screen recording the compose stage layers under.
        draft["screen_recording_key"] = gameplay_key
    elif spec.background_id:
        # No user footage: the compose stage materializes this curated background
        # (content.background_library) into the looping companion track.
        draft["background_id"] = spec.background_id
    # Identity lock (Wave 4): when a character is bound, carry the per-shot locks
    # so the render worker reproduces the same identity every shot (never discard
    # the compiled render_spec's conditioning). JobCreateRequest allows extras, so
    # this rides through to Job.params for the render-worker bridge.
    character_sidecar = _identity_sidecar(spec)
    if character_sidecar is not None:
        draft["character"] = character_sidecar
    # Drop Nones so the payload matches the classic shape (validators treat absent
    # optionals as defaults).
    draft = {k: v for k, v in draft.items() if v is not None}

    _assert_pipeline_valid(draft)

    return {
        "template": tmpl.slug,
        "version": tmpl.version,
        "render_spec": spec.to_dict(),
        "reel_draft": draft,
    }


def _identity_sidecar(spec: RenderSpec) -> dict | None:
    """Extract the compiled per-segment identity locks into a Job-params sidecar.

    Returns ``None`` when the reel carries no bound character (every segment's
    ``identity_lock`` is ``None``) so a classic reel draft is byte-identical.
    Otherwise returns ``{"character_id", "identity_key", "shots": [...]}`` where
    each shot holds the deterministic per-shot seed + the reference-sheet r2 keys
    + LoRA ref the render-worker bridge presigns into IPAdapter/LoRA URLs.
    """
    from dataclasses import asdict

    shots = [
        {"order": seg.order, **asdict(seg.identity_lock)}
        for seg in spec.segments
        if seg.identity_lock is not None
    ]
    if not shots:
        return None
    first = shots[0]
    return {
        "character_id": first.get("character_id", ""),
        "identity_key": first.get("identity_key", ""),
        "shots": shots,
    }


def _first(inputs: dict, keys: tuple[str, ...]) -> str:
    for k in keys:
        v = str(inputs.get(k, "") or "").strip()
        if v:
            return v
    return ""


def _assert_pipeline_valid(draft: dict) -> None:
    """Prove the draft is a submittable reel by constructing the real request DTO."""
    from pydantic import ValidationError

    from app.models.schema import JobCreateRequest

    try:
        JobCreateRequest(**draft)
    except ValidationError as exc:
        raise TemplateError(f"template produced an invalid reel draft: {exc}") from exc
