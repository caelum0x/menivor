"""Seed: before-after — transformation-reveal format.

The highest-converting proof format for fitness / beauty / product / SaaS: open on
the *after* (or the promise), rewind to the *before* + the struggle, walk the
process fast, then a satisfying reveal and a CTA. Works over a screen recording,
a photo pair, or product b-roll.
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="before-after",
    name="Before / After Transformation",
    genre="marketing",
    version="1.0.0",
    description=(
        "Transformation reveal: after-first hook → the before + struggle → fast process → "
        "satisfying reveal → CTA. The highest-converting proof format."
    ),
    aspect="9:16",
    layout="hook_intro",
    default_duration_s=25.0,
    min_duration_s=12.0,
    max_duration_s=45.0,
    caption_style="karaoke_yellow",
    camera_motion="push_in",
    effects=(),
    vfx_intensity=30,
    loopable=False,
    default_background="aerial-nature",
    tags=("marketing", "transformation", "before-after", "proof", "ugc"),
    audio=AudioPlanDef(foreground="narration", bgm_prompt="building motivational, drop on the reveal",
                       duck=True, layers=("narration", "bgm")),
    slots=(
        SlotSpec(role="hook", order=0, t_start_frac=0.0, t_end_frac=0.14, track="primary",
                 audio=("narration",), caption=True, min_s=2.0, max_s=4.0, hook_gate=True,
                 label="After-first hook", notes="Open on the end result / the promise."),
        SlotSpec(role="setup", order=1, t_start_frac=0.14, t_end_frac=0.38, track="primary",
                 audio=("narration",), caption=True, label="The before",
                 notes="Rewind to the starting point + the struggle the viewer recognizes."),
        SlotSpec(role="rising", order=2, t_start_frac=0.38, t_end_frac=0.74, track="primary",
                 audio=("narration",), caption=True, label="The process",
                 notes="The fast montage of how — enough to be credible, not a tutorial."),
        SlotSpec(role="climax", order=3, t_start_frac=0.74, t_end_frac=0.90, track="primary",
                 audio=("narration",), caption=True, label="The reveal",
                 notes="Land the after on the music drop; the payoff beat."),
        SlotSpec(role="cta", order=4, t_start_frac=0.90, t_end_frac=1.0, track="primary",
                 audio=("narration",), caption=True, label="CTA", notes="One clear next step."),
    ),
    inputs=(
        TemplateInput("promise", "text", "The transformation (before → after in one line)", required=True),
        TemplateInput("gameplay_clip", "clip", "Your before/after footage or screen recording", required=False),
        TemplateInput("cta", "text", "Call to action", required=False, default="Full guide — link in bio"),
    ),
)
