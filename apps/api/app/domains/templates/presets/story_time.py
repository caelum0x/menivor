"""Seed: story-time — the narrated "story time" over a gameplay loop.

The retention monster of faceless content: a first-person story ("so this
happened to me…") narrated over a looping second-stimulation background, with a
cold-open hook, a setup, escalating drama, a twist climax, the resolution, and a
"part 2?" comment-bait CTA. Built for completion rate + comments.
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="story-time",
    name="Story Time (narrated)",
    genre="story",
    version="1.0.0",
    description=(
        "First-person story over a gameplay loop: hook → setup → escalating drama → twist "
        "→ resolution → 'part 2?' CTA. Built for completion rate and comments."
    ),
    aspect="9:16",
    layout="split",
    default_duration_s=45.0,
    min_duration_s=20.0,
    max_duration_s=90.0,
    caption_style="karaoke_yellow",
    camera_motion="none",
    effects=(),
    vfx_intensity=15,
    loopable=False,
    default_background="neon-runner",
    tags=("story", "storytime", "narration", "faceless", "drama"),
    audio=AudioPlanDef(foreground="narration", bgm_prompt="light suspense underscore, low, non-distracting",
                       duck=True, layers=("narration", "bgm")),
    slots=(
        SlotSpec(role="hook", order=0, t_start_frac=0.0, t_end_frac=0.08, track="primary",
                 audio=("narration",), caption=True, min_s=1.5, max_s=3.5, hook_gate=True,
                 label="Story hook", notes="Drop them into the most dramatic beat first, then rewind."),
        SlotSpec(role="setup", order=1, t_start_frac=0.08, t_end_frac=0.25, track="primary",
                 audio=("narration",), caption=True, label="Setup",
                 notes="Who/where/stakes in one breath; keep it moving."),
        SlotSpec(role="rising", order=2, t_start_frac=0.25, t_end_frac=0.60, track="primary",
                 audio=("narration",), caption=True, label="Escalation",
                 notes="Bump the tension every couple of seconds; no dead air."),
        SlotSpec(role="climax", order=3, t_start_frac=0.60, t_end_frac=0.80, track="primary",
                 audio=("narration",), caption=True, label="The twist",
                 notes="The turn/reveal — the reason the story is worth telling."),
        SlotSpec(role="payoff", order=4, t_start_frac=0.80, t_end_frac=0.92, track="primary",
                 audio=("narration",), caption=True, label="Resolution",
                 notes="Land how it ended; give emotional closure."),
        SlotSpec(role="cta", order=5, t_start_frac=0.92, t_end_frac=1.0, track="primary",
                 audio=("narration",), caption=True, label="Comment CTA",
                 notes="'Should I tell part 2? Comment below.'"),
    ),
    inputs=(
        TemplateInput("story", "text", "Your story (or a prompt to dramatize)", required=True),
        TemplateInput("broll_clip", "clip", "Background loop (optional — auto-filled)", required=False),
    ),
)
