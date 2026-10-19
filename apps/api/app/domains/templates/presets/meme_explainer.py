"""Seed: meme-explainer — the fast, funny "let me explain" reel.

A high-energy explainer with meme timing: a crash-zoom hook, a quick "here's the
context" setup, the punchy explanation with a glitch cut, a comedic payoff, and a
follow CTA. Faster and funnier than the straight talking-head explainer — built
for the "explain the drama / the trend / the discourse" comedy-education niche.
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="meme-explainer",
    name="Meme Explainer",
    genre="explainer",
    version="1.0.0",
    description=(
        "Fast, funny 'let me explain': crash-zoom hook → quick context → punchy explanation "
        "with a glitch cut → comedic payoff → follow CTA. Meme timing, high energy."
    ),
    aspect="9:16",
    layout="full",
    default_duration_s=26.0,
    min_duration_s=10.0,
    max_duration_s=45.0,
    caption_style="bold_violet",
    camera_motion="crash_zoom_in",
    effects=("glitch",),
    vfx_intensity=45,
    loopable=False,
    default_background="",
    tags=("explainer", "meme", "comedy", "commentary", "trend", "fast"),
    audio=AudioPlanDef(foreground="narration", bgm_prompt="quirky upbeat meme beat, bouncy",
                       duck=True, layers=("narration", "bgm")),
    slots=(
        SlotSpec(role="hook", order=0, t_start_frac=0.0, t_end_frac=0.10, track="full",
                 audio=("narration",), caption=True, min_s=1.2, max_s=3.5, hook_gate=True,
                 label="Crash-zoom hook", notes="'Okay so nobody is talking about this…' Punch in hard."),
        SlotSpec(role="setup", order=1, t_start_frac=0.10, t_end_frac=0.28, track="full",
                 audio=("narration",), caption=True, label="Quick context",
                 notes="Give just enough backstory for the joke/point to land."),
        SlotSpec(role="body", order=2, t_start_frac=0.28, t_end_frac=0.75, track="full",
                 audio=("narration",), caption=True, label="The explanation",
                 notes="Explain it fast; glitch-cut between beats to keep energy up."),
        SlotSpec(role="payoff", order=3, t_start_frac=0.75, t_end_frac=0.90, track="full",
                 audio=("narration",), caption=True, label="Comedic payoff",
                 notes="Land the punchline or the 'and that's why…' button."),
        SlotSpec(role="cta", order=4, t_start_frac=0.90, t_end_frac=1.0, track="full",
                 audio=("narration",), caption=True, label="Follow CTA",
                 notes="'Follow, I explain the internet.'"),
    ),
    inputs=(
        TemplateInput("topic", "text", "What are you explaining? (the trend/drama/thing)", required=True),
        TemplateInput("broll_clip", "clip", "Reaction/greenscreen clip (optional)", required=False),
    ),
)
