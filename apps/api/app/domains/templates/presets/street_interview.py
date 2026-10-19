"""Seed: street-interview — the "man on the street" Q&A format.

The viral interview format: a provocative question hook, rapid-fire answers from
different people (the rising body), the standout/funniest answer as the climax,
and a CTA. Whip-pan cuts between answers, karaoke captions. Built for comments +
shares on the "we asked X people…" street-interview trend.
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="street-interview",
    name="Street Interview (Q&A)",
    genre="interview",
    version="1.0.0",
    description=(
        "Man-on-the-street Q&A: provocative question hook → rapid-fire answers → the "
        "standout answer → CTA. Whip-pan cuts between answers, karaoke captions."
    ),
    aspect="9:16",
    layout="full",
    default_duration_s=38.0,
    min_duration_s=15.0,
    max_duration_s=75.0,
    caption_style="karaoke_green",
    camera_motion="whip_pan",
    effects=(),
    vfx_intensity=20,
    loopable=False,
    default_background="",
    tags=("interview", "street", "q-and-a", "vox-pop", "comments", "trend"),
    audio=AudioPlanDef(foreground="dialogue", bgm_prompt="playful street groove, light bounce",
                       duck=True, layers=("dialogue", "bgm")),
    slots=(
        SlotSpec(role="hook", order=0, t_start_frac=0.0, t_end_frac=0.10, track="full",
                 audio=("dialogue",), caption=True, min_s=1.5, max_s=3.5, hook_gate=True,
                 label="Question hook", notes="Open on the question itself: 'we asked strangers…'"),
        SlotSpec(role="rising", order=1, t_start_frac=0.10, t_end_frac=0.80, track="full",
                 audio=("dialogue",), caption=True, label="The answers",
                 notes="Whip-pan between answers; one person per beat; escalate to the best."),
        SlotSpec(role="climax", order=2, t_start_frac=0.80, t_end_frac=0.90, track="full",
                 audio=("dialogue",), caption=True, label="Standout answer",
                 notes="Save the funniest/most-shocking answer for last."),
        SlotSpec(role="cta", order=3, t_start_frac=0.90, t_end_frac=1.0, track="full",
                 audio=("dialogue",), caption=True, label="Comment CTA",
                 notes="'What's your answer? Comment it.'"),
    ),
    inputs=(
        TemplateInput("topic", "text", "The question you're asking", required=True),
        TemplateInput("broll_clip", "clip", "Your interview footage (optional)", required=False),
    ),
)
