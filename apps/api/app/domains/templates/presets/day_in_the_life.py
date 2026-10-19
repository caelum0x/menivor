"""Seed: day-in-the-life — the aesthetic vlog montage.

The "day in my life" vlog: a hook that sets the day/identity, a quick setup, a
montage body of moments carried by narration, and a follow CTA. Handheld, clean
white captions, aesthetic pacing. The format for creators, founders, students, and
athletes to document a routine and build a parasocial audience.
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="day-in-the-life",
    name="Day in the Life (Vlog)",
    genre="vlog",
    version="1.0.0",
    description=(
        "Aesthetic vlog montage: hook that sets the day → quick setup → montage of moments "
        "over narration → follow CTA. Handheld, clean captions, aesthetic pacing."
    ),
    aspect="9:16",
    layout="full",
    default_duration_s=45.0,
    min_duration_s=20.0,
    max_duration_s=90.0,
    caption_style="clean_white",
    camera_motion="handheld_follow",
    effects=(),
    vfx_intensity=10,
    loopable=False,
    default_background="",
    tags=("vlog", "day-in-the-life", "lifestyle", "montage", "aesthetic", "routine"),
    audio=AudioPlanDef(foreground="narration", bgm_prompt="dreamy aesthetic lo-fi pop, warm, gentle groove",
                       duck=True, layers=("narration", "bgm")),
    slots=(
        SlotSpec(role="hook", order=0, t_start_frac=0.0, t_end_frac=0.08, track="full",
                 audio=("narration",), caption=True, min_s=1.5, max_s=4.0, hook_gate=True,
                 label="Day hook", notes="'A day in my life as a…' Set identity + a reason to watch."),
        SlotSpec(role="setup", order=1, t_start_frac=0.08, t_end_frac=0.22, track="full",
                 audio=("narration",), caption=True, label="Setup",
                 notes="Frame the day — what makes today worth showing."),
        SlotSpec(role="body", order=2, t_start_frac=0.22, t_end_frac=0.86, track="full",
                 audio=("narration",), caption=True, label="The montage",
                 notes="Beat-by-beat moments; narration threads them into a story."),
        SlotSpec(role="cta", order=3, t_start_frac=0.86, t_end_frac=1.0, track="full",
                 audio=("narration",), caption=True, label="Follow CTA",
                 notes="'Follow to see day two.'"),
    ),
    inputs=(
        TemplateInput("title", "text", "Whose day + the theme (e.g. 'day in my life as a founder')",
                      required=True),
        TemplateInput("broll_clip", "clip", "Your footage montage (optional)", required=False),
    ),
)
