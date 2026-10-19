"""Seed: product-demo-ad — the startup UGC marketing format.

A founder/creator UGC ad where a talking avatar sells the product **over the app's
own screen recording**: pattern-interrupt hook → the pain → live demo (the uploaded
screen recording, avatar picture-in-picture) → proof → call to action. This is the
"a startup can make its own marketing" journey as a one-tap template: upload a
screen recording of the app + a one-line prompt, the pipeline writes the script,
voices an avatar, burns captions, and composes the avatar over the demo.

Layout ``hook_intro``: a punchy avatar-forward cold open, then the avatar drops to
a corner badge while the screen recording fills the frame for the demo.
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="product-demo-ad",
    name="Product Demo Ad (UGC)",
    genre="marketing",
    version="1.0.0",
    description=(
        "Founder-style UGC ad: hook → pain → live app demo (avatar over your screen "
        "recording) → proof → CTA. Upload a screen recording + a one-line prompt."
    ),
    aspect="9:16",
    layout="hook_intro",
    default_duration_s=30.0,
    min_duration_s=15.0,
    max_duration_s=60.0,
    caption_style="karaoke_yellow",
    camera_motion="push_in",
    effects=(),
    vfx_intensity=30,
    loopable=False,
    # No auto-loop background: the "companion" visual IS the user's screen recording
    # (bound via the gameplay/broll clip input → screen_recording_key). If the user
    # somehow supplies none, fall back to a clean product-y backdrop.
    default_background="aerial-nature",
    tags=("marketing", "ugc", "ad", "startup", "saas", "demo", "avatar"),
    audio=AudioPlanDef(
        foreground="narration",
        bgm_prompt="upbeat corporate motivational, subtle, background",
        duck=True,
        layers=("narration", "bgm"),
    ),
    slots=(
        SlotSpec(
            role="hook", order=0, t_start_frac=0.0, t_end_frac=0.12,
            track="primary", audio=("narration",), caption=True,
            min_s=2.0, max_s=4.0, hook_gate=True, label="Pattern-interrupt hook",
            notes="Avatar-forward. Lead with the outcome/claim, not the product name.",
        ),
        SlotSpec(
            role="setup", order=1, t_start_frac=0.12, t_end_frac=0.30,
            track="primary", audio=("narration",), caption=True,
            label="The pain", notes="Name the exact problem the viewer feels.",
        ),
        SlotSpec(
            role="rising", order=2, t_start_frac=0.30, t_end_frac=0.72,
            track="primary", audio=("narration",), caption=True,
            label="Live demo", notes="Screen recording fills the frame; avatar → corner badge; narrate the click-path.",
        ),
        SlotSpec(
            role="payoff", order=3, t_start_frac=0.72, t_end_frac=0.88,
            track="primary", audio=("narration",), caption=True,
            label="Proof / result", notes="The concrete result — metric, before/after, or testimonial line.",
        ),
        SlotSpec(
            role="cta", order=4, t_start_frac=0.88, t_end_frac=1.0,
            track="primary", audio=("narration",), caption=True,
            label="Call to action", notes="One clear ask: link in bio / try free / comment a keyword.",
        ),
    ),
    inputs=(
        TemplateInput("promise", "text", "One-line pitch / hook (what it does + for whom)", required=True),
        TemplateInput("gameplay_clip", "clip", "Screen recording of your app/product", required=False,
                      help="Upload key of a screen recording; the avatar is composed over it during the demo."),
        TemplateInput("cta", "text", "Call to action (e.g. 'try free — link in bio')", required=False,
                      default="Link in bio — try it free"),
    ),
)
