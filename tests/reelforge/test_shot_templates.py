"""Genre shot-template engine — pure compile + pipeline-ready instantiate."""

from __future__ import annotations

import pytest

from app.domains.templates import service
from app.domains.templates.presets import all_templates
from app.domains.templates.validation import TemplateError


def test_registry_has_expected_templates():
    slugs = {t.slug for t in all_templates()}
    assert {"minecraft-reddit-split", "asmr-satisfying-loop", "movie-recap", "fake-ai-podcast"} <= slugs


def test_every_template_has_one_hook_gate_and_tiles_fractions():
    for t in all_templates():
        gates = [s for s in t.slots if s.hook_gate]
        assert len(gates) == 1, f"{t.slug} must have exactly one hook gate"
        # Fractions tile [0,1] contiguously (each slot starts where the prior ended).
        prev = 0.0
        for s in t.slots:
            assert abs(s.t_start_frac - prev) < 1e-6, f"{t.slug} slot gap/overlap at {s.role}"
            prev = s.t_end_frac
        assert abs(prev - 1.0) < 1e-6, f"{t.slug} slots must fill to 1.0"


def test_compile_tiles_timeline_and_clamps_hook():
    spec = service.compile_spec(
        "minecraft-reddit-split",
        {"story": "shocking line first", "gameplay_clip": "jobs/u/p.mp4"},
        duration_s=45,
    )
    assert spec.duration_s == pytest.approx(45.0, abs=0.05)
    # Segments are contiguous and cover the whole duration.
    t = 0.0
    for seg in spec.segments:
        assert seg.t_start == pytest.approx(t, abs=0.01)
        t = seg.t_end
    assert t == pytest.approx(45.0, abs=0.05)
    # The hook slot is clamped to its max (3.0s) so it clears the first-3s gate.
    hook = spec.segments[0]
    assert hook.hook_gate and hook.duration <= 3.0
    # Gameplay SFX is ducked under the narration foreground.
    body = spec.segments[2]
    ducked = [a for a in body.audio if a.layer == "gameplay_sfx"]
    assert ducked and ducked[0].ducked


def test_compile_rejects_unknown_template_and_bad_inputs():
    with pytest.raises(TemplateError):
        service.compile_spec("nope", {})
    with pytest.raises(TemplateError):
        service.compile_spec("minecraft-reddit-split", {"bogus": "x"})  # unknown input
    with pytest.raises(TemplateError):
        service.compile_spec("minecraft-reddit-split", {})  # missing required 'story'
    with pytest.raises(TemplateError):
        service.compile_spec("minecraft-reddit-split", {"story": "x"}, duration_s=5)  # < min 20


def test_instantiate_produces_pipeline_valid_draft():
    res = service.instantiate_draft(
        "minecraft-reddit-split",
        {"story": "my sister read my diary", "gameplay_clip": "jobs/u/p.mp4", "subject": "AITA"},
        duration_s=45,
    )
    draft = res["reel_draft"]
    assert draft["layout"] == "split"
    assert draft["caption_style"] == "karaoke_yellow"
    assert draft["screen_recording_key"] == "jobs/u/p.mp4"
    assert draft["video_subject"] == "AITA"
    # The draft is validated against the real JobCreateRequest inside the service,
    # so re-constructing it here must also succeed.
    from app.models.schema import JobCreateRequest

    JobCreateRequest(**draft)


def test_template_with_vfx_carries_effects_into_draft():
    res = service.instantiate_draft("brainrot-ai-meme", {"character": "Tung", "bit": "boom"})
    draft = res["reel_draft"]
    assert draft["camera_motion"] == "crash_zoom_in"
    assert draft["effects"] == ["glitch"]
    # to_dict() keeps Python tuples (FastAPI serializes them to JSON lists on the wire).
    assert res["render_spec"]["effects"] == ("glitch",)


def test_duration_scales_pacing():
    short = service.compile_spec("movie-recap", {"title": "Inception"}, duration_s=30)
    long = service.compile_spec("movie-recap", {"title": "Inception"}, duration_s=90)
    assert short.duration_s == pytest.approx(30.0, abs=0.1)
    assert long.duration_s == pytest.approx(90.0, abs=0.1)
    # The body slot grows with total duration.
    assert long.segments[2].duration > short.segments[2].duration
