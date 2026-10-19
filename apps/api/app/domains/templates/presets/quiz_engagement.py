"""Seed: quiz-engagement — comment-driving "which one / would you rather" format.

A pure engagement-bait format built to farm comments + rewatches: a rapid-fire
"pick one" or "guess the answer" over a satisfying/gameplay background, with a
pause-for-answer beat and a loop-back CTA. The algorithm rewards the comments and
the loop, so this is the cheapest reach format to run at volume.
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="quiz-engagement",
    name="Quiz / Would-You-Rather",
    genre="engagement",
    version="1.0.0",
    description=(
        "Comment-bait quiz: rapid 'pick one / guess the answer' rounds over a "
        "satisfying background, a pause beat, and a loop-back CTA. Farms comments + rewatches."
    ),
    aspect="9:16",
    layout="split",
    default_duration_s=22.0,
    min_duration_s=10.0,
    max_duration_s=40.0,
    caption_style="karaoke_green",
    camera_motion="none",
    effects=(),
    vfx_intensity=25,
    loopable=True,
    default_background="kinetic-sand-cutting",
    tags=("engagement", "quiz", "comment-bait", "faceless", "loop", "would-you-rather"),
    audio=AudioPlanDef(
        foreground="narration",
        bgm_prompt="playful upbeat game-show, light tension",
        duck=True,
        layers=("narration", "bgm"),
    ),
    slots=(
        SlotSpec(role="hook", order=0, t_start_frac=0.0, t_end_frac=0.10,
                 track="primary", audio=("narration",), caption=True, min_s=1.5, max_s=3.0,
                 hook_gate=True, label="Challenge hook",
                 notes="'Only 1% can… / Would you rather…' — dare the viewer to answer."),
        SlotSpec(role="rising", order=1, t_start_frac=0.10, t_end_frac=0.70,
                 track="primary", audio=("narration",), caption=True, label="Rounds",
                 notes="3-5 quick options; each caption is a choice; background loops uninterrupted."),
        SlotSpec(role="climax", order=2, t_start_frac=0.70, t_end_frac=0.86,
                 track="primary", audio=("narration",), caption=True, label="Pause / reveal",
                 notes="A beat of silence ('comment your answer before the reveal…') then the answer."),
        SlotSpec(role="cta", order=3, t_start_frac=0.86, t_end_frac=0.95,
                 track="primary", audio=("narration",), caption=True, label="Comment CTA",
                 notes="'Comment your score' — drive the reply farm."),
        SlotSpec(role="loop", order=4, t_start_frac=0.95, t_end_frac=1.0,
                 track="primary", audio=("narration",), caption=True, label="Loop seam",
                 notes="Snap back to the hook so the rewatch is seamless."),
    ),
    inputs=(
        TemplateInput("topic", "text", "Quiz topic / prompt (e.g. 'would you rather have X or Y')", required=True),
        TemplateInput("background_id", "text", "Background (optional; defaults to satisfying loop)", required=False),
    ),
)
