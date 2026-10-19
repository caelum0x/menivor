"""Seed: movie-recap — narrated summary with a SPECIFIC ANGLE.

Open on intrigue/question (not a title card), high-familiarity film, hook in the
first 20–30s, chronological beats with distinct commentary over clip B-roll, AI
narration + ducked score, Hormozi karaoke captions. 9:16.
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="movie-recap",
    name="Angle-First Recap",
    genre="recap",
    version="1.0.0",
    description="Angle-first narrated recap over clip B-roll; hook in the first 20–30s; Hormozi captions.",
    layout="full",
    default_duration_s=60.0,
    min_duration_s=30.0,
    max_duration_s=90.0,
    caption_style="karaoke_yellow",
    camera_motion="none",
    effects=(),
    loopable=False,
    default_background="aerial-nature",
    tags=("recap", "film", "narration", "faceless"),
    audio=AudioPlanDef(foreground="narration", bgm_prompt="tense cinematic underscore, subtle",
                       duck=True, layers=("narration", "bgm")),
    slots=(
        SlotSpec(role="hook", order=0, t_start_frac=0.0, t_end_frac=0.08,
                 track="full", audio=("narration",), caption=True, min_s=3.0, max_s=6.0,
                 hook_gate=True, label="Intrigue Hook", notes="Open on a question, not a title card."),
        SlotSpec(role="setup", order=1, t_start_frac=0.08, t_end_frac=0.25,
                 track="full", audio=("narration", "bgm"), caption=True, label="Premise + Angle"),
        SlotSpec(role="body", order=2, t_start_frac=0.25, t_end_frac=0.82,
                 track="full", audio=("narration", "bgm"), caption=True,
                 label="Beats", notes="Chronological beats with distinct commentary."),
        SlotSpec(role="payoff", order=3, t_start_frac=0.82, t_end_frac=0.94,
                 track="full", audio=("narration", "bgm"), caption=True, label="Payoff / Verdict"),
        SlotSpec(role="cta", order=4, t_start_frac=0.94, t_end_frac=1.0,
                 track="full", audio=("narration",), caption=True, label="CTA / Follow"),
    ),
    inputs=(
        TemplateInput("title", "text", "Film / show title", required=True),
        TemplateInput("angle", "text", "Specific angle", required=False,
                      help="e.g. 'why the villain was right' — a summary is generated if omitted."),
        TemplateInput("broll_clip", "clip", "Clip B-roll", required=False),
    ),
)
