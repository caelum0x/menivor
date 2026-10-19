"""Seed: countdown-ranking — the "top N / tier list" countdown reel.

The ranking format: a hook that promises the countdown, a rising body that counts
DOWN through the ranked picks (each with a bold caption), the #1 reveal as the
climax with a confetti pop, and a "do you agree?" CTA. Zoom-punch cuts between
ranks. Built for comments (rankings are the ultimate debate-bait).
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="countdown-ranking",
    name="Countdown / Ranking",
    genre="ranking",
    version="1.0.0",
    description=(
        "Top-N countdown: hook → count DOWN through the ranked picks with bold captions → "
        "the #1 reveal with a confetti pop → 'do you agree?' CTA. Debate-bait for comments."
    ),
    aspect="9:16",
    layout="split",
    default_duration_s=33.0,
    min_duration_s=12.0,
    max_duration_s=60.0,
    caption_style="karaoke_yellow",
    camera_motion="zoom_punch_in",
    effects=("confetti",),
    vfx_intensity=30,
    loopable=False,
    default_background="marble-run",
    tags=("ranking", "countdown", "tier-list", "top-10", "debate", "comments"),
    audio=AudioPlanDef(foreground="narration", bgm_prompt="building countdown beat, rising energy",
                       duck=True, layers=("narration", "bgm")),
    slots=(
        SlotSpec(role="hook", order=0, t_start_frac=0.0, t_end_frac=0.10, track="primary",
                 audio=("narration",), caption=True, min_s=1.2, max_s=3.5, hook_gate=True,
                 label="Countdown hook", notes="'Top 5 X, ranked worst to best.' Promise a controversial #1."),
        SlotSpec(role="rising", order=1, t_start_frac=0.10, t_end_frac=0.72, track="primary",
                 audio=("narration",), caption=True, label="The countdown",
                 notes="One rank per beat, counting down; each caption is the pick + its number."),
        SlotSpec(role="climax", order=2, t_start_frac=0.72, t_end_frac=0.88, track="primary",
                 audio=("narration",), caption=True, label="The #1 reveal",
                 notes="Reveal #1 with the confetti pop; make it feel earned."),
        SlotSpec(role="cta", order=3, t_start_frac=0.88, t_end_frac=1.0, track="primary",
                 audio=("narration",), caption=True, label="Debate CTA",
                 notes="'Do you agree? Drop your #1 in the comments.'"),
    ),
    inputs=(
        TemplateInput("topic", "text", "Ranking topic (e.g. 'top 5 productivity apps')", required=True),
        TemplateInput("broll_clip", "clip", "Background loop (optional — auto-filled)", required=False),
    ),
)
