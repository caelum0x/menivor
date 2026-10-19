"""Seed: testimonial-ad — social-proof UGC marketing format.

The #2 startup ad after a product demo: a customer-review style spot that leads
with the *result*, then a relatable objection, then the payoff + a soft CTA. Reads
as an authentic review, not a pitch — the avatar (or a photo-avatar of a "customer")
delivers it with bold captions carrying the key claims. Pairs well with a short
b-roll of the product in use.
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="testimonial-ad",
    name="Testimonial Ad (UGC)",
    genre="marketing",
    version="1.0.0",
    description=(
        "Authentic customer-review UGC ad: result-first hook → the objection you had → "
        "the payoff → soft CTA. Reads as a real review, not a pitch."
    ),
    aspect="9:16",
    layout="pip",
    default_duration_s=25.0,
    min_duration_s=12.0,
    max_duration_s=45.0,
    caption_style="clean_white",
    camera_motion="none",
    effects=(),
    vfx_intensity=15,
    loopable=False,
    default_background="aerial-nature",
    tags=("marketing", "ugc", "ad", "testimonial", "review", "proof", "startup"),
    audio=AudioPlanDef(
        foreground="narration",
        bgm_prompt="warm acoustic, sincere, low background",
        duck=True,
        layers=("narration", "bgm"),
    ),
    slots=(
        SlotSpec(role="hook", order=0, t_start_frac=0.0, t_end_frac=0.14,
                 track="primary", audio=("narration",), caption=True, min_s=2.0, max_s=4.0,
                 hook_gate=True, label="Result-first hook",
                 notes="Open with the concrete outcome ('I got X in Y days'), not the product."),
        SlotSpec(role="setup", order=1, t_start_frac=0.14, t_end_frac=0.40,
                 track="primary", audio=("narration",), caption=True, label="The objection",
                 notes="The doubt the viewer shares ('I was skeptical because…')."),
        SlotSpec(role="payoff", order=2, t_start_frac=0.40, t_end_frac=0.82,
                 track="primary", audio=("narration",), caption=True, label="What changed",
                 notes="The turning point + the tangible result; b-roll of the product in use."),
        SlotSpec(role="cta", order=3, t_start_frac=0.82, t_end_frac=1.0,
                 track="primary", audio=("narration",), caption=True, label="Soft CTA",
                 notes="Low-pressure recommend ('honestly just try it — link in bio')."),
    ),
    inputs=(
        TemplateInput("promise", "text", "The result / claim (what changed for the customer)", required=True),
        TemplateInput("broll_clip", "clip", "B-roll of the product in use (optional)", required=False),
        TemplateInput("cta", "text", "Soft call to action", required=False,
                      default="Honestly, just try it — link in bio"),
    ),
)
