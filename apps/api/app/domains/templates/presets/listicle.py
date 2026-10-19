"""Seed: listicle — rapid-fire "N things" edutainment / marketing format.

The workhorse of value content: a numbered-list hook ("5 tools every founder
needs"), fast punchy items each with a bold caption, a "best one" payoff, and a
save/follow CTA. Drives saves + shares; pairs with a satisfying/gameplay loop or
product b-roll behind the captions.
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="listicle",
    name="Listicle (N things)",
    genre="edutainment",
    version="1.0.0",
    description=(
        "Rapid-fire numbered list: '5 X you need' hook → punchy items with bold captions → "
        "the best pick → save/follow CTA. Built for saves + shares."
    ),
    aspect="9:16",
    layout="split",
    default_duration_s=28.0,
    min_duration_s=12.0,
    max_duration_s=50.0,
    caption_style="bold_violet",
    camera_motion="none",
    effects=(),
    vfx_intensity=20,
    loopable=False,
    default_background="marble-run",
    tags=("edutainment", "listicle", "tips", "value", "marketing", "faceless"),
    audio=AudioPlanDef(foreground="narration", bgm_prompt="energetic clean, steady tempo",
                       duck=True, layers=("narration", "bgm")),
    slots=(
        SlotSpec(role="hook", order=0, t_start_frac=0.0, t_end_frac=0.10, track="primary",
                 audio=("narration",), caption=True, min_s=1.5, max_s=3.5, hook_gate=True,
                 label="Numbered hook", notes="'5 X every Y needs — save this.' Promise the payoff."),
        SlotSpec(role="rising", order=1, t_start_frac=0.10, t_end_frac=0.78, track="primary",
                 audio=("narration",), caption=True, label="The items",
                 notes="One item per beat; each caption is the item name; keep it fast."),
        SlotSpec(role="payoff", order=2, t_start_frac=0.78, t_end_frac=0.90, track="primary",
                 audio=("narration",), caption=True, label="Best pick",
                 notes="Call out the #1 so it feels resolved, not a cliffhanger."),
        SlotSpec(role="cta", order=3, t_start_frac=0.90, t_end_frac=1.0, track="primary",
                 audio=("narration",), caption=True, label="Save CTA", notes="'Follow for part 2 / save this.'"),
    ),
    inputs=(
        TemplateInput("topic", "text", "List topic (e.g. '5 free tools for founders')", required=True),
        TemplateInput("broll_clip", "clip", "Background footage (optional)", required=False),
    ),
)
