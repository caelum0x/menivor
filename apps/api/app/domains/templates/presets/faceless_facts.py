"""Seed: faceless-facts — the "did you know" scroll-stopper.

A 100% faceless value format: a punchy factual hook over a satisfying background
loop, rapid-fire surprising facts each with a bold caption, a mind-blown payoff,
and a save/follow CTA. No camera, no voice actor needed — narration is TTS over a
looping second-stimulation background. The workhorse of faceless niche channels
(space, history, psychology, money).
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="faceless-facts",
    name="Faceless Facts (Did You Know)",
    genre="faceless",
    version="1.0.0",
    description=(
        "100% faceless value: a 'did you know' hook → rapid surprising facts with bold "
        "captions → mind-blown payoff → save CTA, all over a satisfying loop. TTS narration."
    ),
    aspect="9:16",
    layout="split",
    default_duration_s=34.0,
    min_duration_s=12.0,
    max_duration_s=60.0,
    caption_style="bold_violet",
    camera_motion="none",
    effects=(),
    vfx_intensity=20,
    loopable=False,
    default_background="marble-run",
    tags=("faceless", "facts", "did-you-know", "value", "save-bait", "tts"),
    audio=AudioPlanDef(foreground="narration", bgm_prompt="curious ambient, light tension, steady",
                       duck=True, layers=("narration", "bgm")),
    slots=(
        SlotSpec(role="hook", order=0, t_start_frac=0.0, t_end_frac=0.09, track="primary",
                 audio=("narration",), caption=True, min_s=1.5, max_s=3.5, hook_gate=True,
                 label="Fact hook", notes="'99% of people don't know…' Promise something surprising."),
        SlotSpec(role="rising", order=1, t_start_frac=0.09, t_end_frac=0.80, track="primary",
                 audio=("narration",), caption=True, label="The facts",
                 notes="One fact per beat; each caption is the punchy fact; escalate the wow."),
        SlotSpec(role="payoff", order=2, t_start_frac=0.80, t_end_frac=0.90, track="primary",
                 audio=("narration",), caption=True, label="Mind-blown payoff",
                 notes="Land the biggest fact last so it resolves, not cliff-hangs."),
        SlotSpec(role="cta", order=3, t_start_frac=0.90, t_end_frac=1.0, track="primary",
                 audio=("narration",), caption=True, label="Save CTA",
                 notes="'Save this' / 'follow for daily facts.'"),
    ),
    inputs=(
        TemplateInput("topic", "text", "Facts topic (e.g. 'space facts that sound fake')", required=True),
        TemplateInput("broll_clip", "clip", "Background loop (optional — auto-filled)", required=False),
    ),
)
