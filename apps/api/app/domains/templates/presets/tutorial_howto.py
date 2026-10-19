"""Seed: tutorial-howto — the step-by-step "how to" screen tutorial.

The classic value tutorial: an avatar-forward hook promising the outcome, a quick
"what you need" setup, the numbered steps narrated over a screen recording, the
finished result, and a save/follow CTA. Layout ``hook_intro`` opens avatar-forward
then drops the avatar to a corner while the screen recording fills the frame.
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="tutorial-howto",
    name="Tutorial / How-To",
    genre="tutorial",
    version="1.0.0",
    description=(
        "Step-by-step how-to: outcome hook → 'what you need' → numbered steps over your "
        "screen recording → the finished result → save CTA. Avatar drops to a corner for the demo."
    ),
    aspect="9:16",
    layout="hook_intro",
    default_duration_s=50.0,
    min_duration_s=20.0,
    max_duration_s=90.0,
    caption_style="karaoke_green",
    camera_motion="push_in",
    effects=(),
    vfx_intensity=15,
    loopable=False,
    default_background="",
    tags=("tutorial", "how-to", "steps", "educational", "screen-recording", "save-bait"),
    audio=AudioPlanDef(foreground="narration", bgm_prompt="clean upbeat productivity, light, background",
                       duck=True, layers=("narration", "bgm")),
    slots=(
        SlotSpec(role="hook", order=0, t_start_frac=0.0, t_end_frac=0.08, track="full",
                 audio=("narration",), caption=True, min_s=1.5, max_s=4.0, hook_gate=True,
                 label="Outcome hook", notes="Promise the finished result up front: 'here's how to X in 60s.'"),
        SlotSpec(role="setup", order=1, t_start_frac=0.08, t_end_frac=0.20, track="full",
                 audio=("narration",), caption=True, label="What you need",
                 notes="List the tools/inputs so viewers can follow along."),
        SlotSpec(role="rising", order=2, t_start_frac=0.20, t_end_frac=0.85, track="full",
                 audio=("narration",), caption=True, label="The steps",
                 notes="One numbered step per beat over the screen recording; narrate the clicks."),
        SlotSpec(role="payoff", order=3, t_start_frac=0.85, t_end_frac=0.93, track="full",
                 audio=("narration",), caption=True, label="The result",
                 notes="Show the finished thing so the payoff is concrete."),
        SlotSpec(role="cta", order=4, t_start_frac=0.93, t_end_frac=1.0, track="full",
                 audio=("narration",), caption=True, label="Save CTA",
                 notes="'Save this so you don't forget the steps.'"),
    ),
    inputs=(
        TemplateInput("title", "text", "What are you teaching? (e.g. 'edit a reel in CapCut')", required=True),
        TemplateInput("gameplay_clip", "clip", "Screen recording of the steps (optional)", required=False,
                      help="Upload key of a screen recording; narration + captions are composed over it."),
        TemplateInput("cta", "text", "Call to action", required=False, default="Save this tutorial"),
    ),
)
