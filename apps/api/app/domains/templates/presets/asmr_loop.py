"""Seed: asmr-satisfying-loop — single ~5s frame-perfect seamless loop.

Start mid-action (blade already contacting oversized kinetic sand), one precise
repetitive trigger, even soft lighting, surreal scale, invisible loop seam. Pure
high-fidelity trigger audio only — NO voice, NO music. Caption optional (single
top-center label out of the focal area).
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="asmr-satisfying-loop",
    name="ASMR Satisfying Loop",
    genre="asmr",
    version="1.0.0",
    description="One precise repetitive trigger as a frame-perfect ~5s seamless loop; trigger audio only.",
    layout="full",
    default_duration_s=5.0,
    min_duration_s=3.0,
    max_duration_s=6.0,
    caption_style="clean_white",
    camera_motion="none",
    effects=(),
    loopable=True,
    default_background="kinetic-sand-cutting",
    tags=("asmr", "satisfying", "loop", "faceless"),
    audio=AudioPlanDef(foreground="trigger", bgm_prompt="", duck=False, layers=("trigger",)),
    slots=(
        SlotSpec(
            role="hook", order=0, t_start_frac=0.0, t_end_frac=0.2,
            track="full", audio=("trigger",), caption=False,
            min_s=0.5, max_s=1.0, hook_gate=True,
            label="Trigger-in Hook", notes="Start mid-action; blade already contacting the material.",
        ),
        SlotSpec(
            role="body", order=1, t_start_frac=0.2, t_end_frac=0.9,
            track="full", audio=("trigger",), caption=False,
            label="Satisfying Action", notes="One precise repetitive trigger, even soft lighting, surreal scale.",
        ),
        SlotSpec(
            role="seam", order=2, t_start_frac=0.9, t_end_frac=1.0,
            track="full", audio=("trigger",), caption=False,
            transition_out="cut", label="Loop Seam", notes="Last frame == first frame; invisible cut.",
        ),
    ),
    inputs=(
        TemplateInput("trigger_clip", "clip", "Trigger clip", required=True,
                      help="Close-up of the single repetitive trigger."),
        TemplateInput("label", "text", "Optional top-center label", required=False),
    ),
)
