"""Seed: split-screen-gameplay-story — any gameplay + any narration.

Payoff-first narration with gameplay already in motion; story/dialogue up top,
continuous high-completion gameplay below for baseline-retention dopamine;
comment-bait / Part-2 loop. Narration always mixed above gameplay SFX + ducked
trending BGM. 9:16.
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="split-screen-gameplay-story",
    name="Gameplay × Story Split",
    genre="brainrot-split",
    version="1.0.0",
    description="Narration up top over continuous gameplay below; payoff-first hook; narration above the mix.",
    layout="split",
    default_duration_s=45.0,
    min_duration_s=20.0,
    max_duration_s=60.0,
    caption_style="karaoke_green",
    camera_motion="none",
    effects=(),
    loopable=True,
    default_background="generic-parkour",
    tags=("gameplay", "story", "faceless", "split"),
    audio=AudioPlanDef(foreground="narration", bgm_prompt="upbeat trending background, low",
                       duck=True, layers=("narration", "gameplay_sfx", "bgm")),
    slots=(
        SlotSpec(role="hook", order=0, t_start_frac=0.0, t_end_frac=0.05,
                 track="primary", audio=("narration",), caption=True, min_s=1.5, max_s=3.0,
                 hook_gate=True, label="Payoff-First Hook", notes="Gameplay already in motion."),
        SlotSpec(role="body", order=1, t_start_frac=0.05, t_end_frac=0.9,
                 track="primary", audio=("narration", "gameplay_sfx"), caption=True,
                 label="Story Body", notes="Continuous gameplay below; narration foreground."),
        SlotSpec(role="cta", order=2, t_start_frac=0.9, t_end_frac=1.0,
                 track="primary", audio=("narration",), caption=True, label="CTA / Loop"),
    ),
    inputs=(
        TemplateInput("story", "text", "Story / narration", required=True),
        TemplateInput("gameplay_clip", "clip", "Gameplay clip", required=False),
    ),
)
