"""Seed: recipe-quick — the fast overhead recipe reel.

The food-niche workhorse: a mouth-watering hook on the finished dish, a quick
ingredient setup, the rapid step-by-step over overhead cooking footage, the final
plated payoff, and a save CTA. Ken-Burns push on stills, bold captions for each
step. Built for saves (recipes are the most-saved content on every platform).
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="recipe-quick",
    name="Quick Recipe",
    genre="food",
    version="1.0.0",
    description=(
        "Fast overhead recipe: finished-dish hook → ingredients → rapid step-by-step over "
        "cooking footage → the plated payoff → save CTA. Bold step captions, built for saves."
    ),
    aspect="9:16",
    layout="full",
    default_duration_s=30.0,
    min_duration_s=12.0,
    max_duration_s=60.0,
    caption_style="bold_violet",
    camera_motion="ken_burns",
    effects=(),
    vfx_intensity=15,
    loopable=False,
    default_background="",
    tags=("food", "recipe", "cooking", "save-bait", "how-to", "overhead"),
    audio=AudioPlanDef(foreground="narration", bgm_prompt="warm cozy kitchen groove, light, upbeat",
                       duck=True, layers=("narration", "bgm")),
    slots=(
        SlotSpec(role="hook", order=0, t_start_frac=0.0, t_end_frac=0.10, track="full",
                 audio=("narration",), caption=True, min_s=1.2, max_s=3.5, hook_gate=True,
                 label="Finished-dish hook", notes="Open on the finished plate: 'you need to make this.'"),
        SlotSpec(role="setup", order=1, t_start_frac=0.10, t_end_frac=0.24, track="full",
                 audio=("narration",), caption=True, label="Ingredients",
                 notes="Flash the ingredient list so viewers can save + shop."),
        SlotSpec(role="rising", order=2, t_start_frac=0.24, t_end_frac=0.82, track="full",
                 audio=("narration",), caption=True, label="The steps",
                 notes="One quick step per beat over the cooking footage; keep it fast."),
        SlotSpec(role="payoff", order=3, t_start_frac=0.82, t_end_frac=0.92, track="full",
                 audio=("narration",), caption=True, label="The plate",
                 notes="The satisfying final reveal — the money shot."),
        SlotSpec(role="cta", order=4, t_start_frac=0.92, t_end_frac=1.0, track="full",
                 audio=("narration",), caption=True, label="Save CTA",
                 notes="'Save this recipe for later.'"),
    ),
    inputs=(
        TemplateInput("topic", "text", "The dish (e.g. '15-minute garlic butter pasta')", required=True),
        TemplateInput("broll_clip", "clip", "Your cooking footage (optional)", required=False),
    ),
)
