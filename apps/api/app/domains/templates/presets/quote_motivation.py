"""Seed: quote-motivation — the cinematic motivational quote reel.

A short, high-share inspirational format: a tension-building cold open, a slow
narrated build over cinematic B-roll, the punch line quote delivered at the peak,
and a follow CTA. Clean white captions, a light-leak accent, and a slow push give
it the "deep motivation" aesthetic that dominates the mindset/stoicism niche.
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="quote-motivation",
    name="Motivational Quote",
    genre="motivation",
    version="1.0.0",
    description=(
        "Cinematic motivation: tension hook → slow narrated build over B-roll → the punch-line "
        "quote at the peak → follow CTA. Clean captions, light-leak accent, slow push."
    ),
    aspect="9:16",
    layout="full",
    default_duration_s=22.0,
    min_duration_s=8.0,
    max_duration_s=40.0,
    caption_style="clean_white",
    camera_motion="slow_zoom_in",
    effects=("light_leak",),
    vfx_intensity=25,
    loopable=False,
    default_background="aerial-nature",
    tags=("motivation", "quote", "mindset", "stoicism", "cinematic", "inspirational"),
    audio=AudioPlanDef(foreground="narration", bgm_prompt="cinematic inspiring swell, building strings, emotional",
                       duck=True, layers=("narration", "bgm")),
    slots=(
        SlotSpec(role="hook", order=0, t_start_frac=0.0, t_end_frac=0.15, track="full",
                 audio=("narration",), caption=True, min_s=1.2, max_s=4.0, hook_gate=True,
                 label="Tension hook", notes="A short, arresting line that creates a gap to fill."),
        SlotSpec(role="rising", order=1, t_start_frac=0.15, t_end_frac=0.68, track="full",
                 audio=("narration",), caption=True, label="The build",
                 notes="Narrate the reframe slowly; let the music breathe under it."),
        SlotSpec(role="climax", order=2, t_start_frac=0.68, t_end_frac=0.88, track="full",
                 audio=("narration",), caption=True, label="The quote",
                 notes="Deliver the punch-line quote on the musical peak; hold on it."),
        SlotSpec(role="cta", order=3, t_start_frac=0.88, t_end_frac=1.0, track="full",
                 audio=("narration",), caption=True, label="Follow CTA",
                 notes="'Follow for your daily reminder.'"),
    ),
    inputs=(
        TemplateInput("topic", "text", "Theme (e.g. 'discipline over motivation')", required=True),
        TemplateInput("quote", "text", "The quote to land (optional — AI writes one otherwise)",
                      required=False),
        TemplateInput("broll_clip", "clip", "Cinematic B-roll (optional)", required=False),
    ),
)
