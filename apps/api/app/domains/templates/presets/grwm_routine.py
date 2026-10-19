"""Seed: get-ready-with-me — the GRWM lifestyle chat format.

The lifestyle staple: talk casually to camera while doing a routine ("get ready
with me for…"), with a hook that promises the story/context, a setup, a chatty
body that carries the routine, and a soft CTA. Handheld energy, karaoke captions.
Drives parasocial connection + follows on lifestyle/beauty/fitness niches.
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="get-ready-with-me",
    name="Get Ready With Me (GRWM)",
    genre="lifestyle",
    version="1.0.0",
    description=(
        "Casual GRWM chat: hook that promises the story → setup → chatty body over your "
        "routine → soft CTA. Handheld energy, parasocial connection, karaoke captions."
    ),
    aspect="9:16",
    layout="full",
    default_duration_s=40.0,
    min_duration_s=15.0,
    max_duration_s=75.0,
    caption_style="karaoke_yellow",
    camera_motion="handheld_follow",
    effects=(),
    vfx_intensity=10,
    loopable=False,
    default_background="",
    tags=("lifestyle", "grwm", "vlog", "beauty", "routine", "parasocial"),
    audio=AudioPlanDef(foreground="narration", bgm_prompt="chill aesthetic lo-fi, warm, soft",
                       duck=True, layers=("narration", "bgm")),
    slots=(
        SlotSpec(role="hook", order=0, t_start_frac=0.0, t_end_frac=0.09, track="full",
                 audio=("narration",), caption=True, min_s=1.5, max_s=4.0, hook_gate=True,
                 label="GRWM hook", notes="'Get ready with me while I tell you about…' Promise a story."),
        SlotSpec(role="setup", order=1, t_start_frac=0.09, t_end_frac=0.25, track="full",
                 audio=("narration",), caption=True, label="Setup",
                 notes="Set the occasion + the story you're about to tell."),
        SlotSpec(role="body", order=2, t_start_frac=0.25, t_end_frac=0.85, track="full",
                 audio=("narration",), caption=True, label="The chat / routine",
                 notes="Carry the story over the routine; keep it warm and conversational."),
        SlotSpec(role="cta", order=3, t_start_frac=0.85, t_end_frac=1.0, track="full",
                 audio=("narration",), caption=True, label="Soft CTA",
                 notes="'Follow to get ready with me every day.'"),
    ),
    inputs=(
        TemplateInput("topic", "text", "What's the occasion + story? (e.g. 'GRWM for a first date')",
                      required=True),
        TemplateInput("broll_clip", "clip", "Your routine clip (optional)", required=False),
    ),
)
