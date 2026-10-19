"""Seed: talking-head-explainer — the creator-to-camera authority format.

The bread-and-butter educational reel: a person (or AI avatar) talks straight to
camera and explains one idea — cold-open hook → frame the question → the
explanation body → the takeaway → a follow CTA. Faceless creators bind an avatar;
everyone else uploads a selfie clip. Drives watch-time + follows on "teach me one
thing" content.
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="talking-head-explainer",
    name="Talking-Head Explainer",
    genre="talking-head",
    version="1.0.0",
    description=(
        "Straight-to-camera explainer: hook → frame the question → clear explanation → "
        "the one takeaway → follow CTA. Upload a selfie clip or bind an AI avatar."
    ),
    aspect="9:16",
    layout="full",
    default_duration_s=40.0,
    min_duration_s=15.0,
    max_duration_s=90.0,
    caption_style="karaoke_yellow",
    camera_motion="push_in",
    effects=(),
    vfx_intensity=15,
    loopable=False,
    default_background="",
    tags=("talking-head", "explainer", "educational", "authority", "avatar", "faceless"),
    audio=AudioPlanDef(foreground="narration", bgm_prompt="warm minimal lo-fi, subtle, low",
                       duck=True, layers=("narration", "bgm")),
    slots=(
        SlotSpec(role="hook", order=0, t_start_frac=0.0, t_end_frac=0.10, track="full",
                 audio=("narration",), caption=True, min_s=1.5, max_s=4.0, hook_gate=True,
                 label="Cold-open hook", notes="Lead with the promise/claim; make them need the answer."),
        SlotSpec(role="setup", order=1, t_start_frac=0.10, t_end_frac=0.25, track="full",
                 audio=("narration",), caption=True, label="Frame the question",
                 notes="State the exact question or misconception you're about to resolve."),
        SlotSpec(role="body", order=2, t_start_frac=0.25, t_end_frac=0.82, track="full",
                 audio=("narration",), caption=True, label="The explanation",
                 notes="Deliver the idea in 2-3 clean steps; one concept per beat."),
        SlotSpec(role="payoff", order=3, t_start_frac=0.82, t_end_frac=0.92, track="full",
                 audio=("narration",), caption=True, label="The takeaway",
                 notes="Compress it to a single memorable line they can repeat."),
        SlotSpec(role="cta", order=4, t_start_frac=0.92, t_end_frac=1.0, track="full",
                 audio=("narration",), caption=True, label="Follow CTA",
                 notes="'Follow for more' / 'comment a word for part 2.'"),
    ),
    inputs=(
        TemplateInput("topic", "text", "What are you explaining? (one idea)", required=True),
        TemplateInput("broll_clip", "clip", "Your selfie/talking clip (optional)", required=False),
        TemplateInput("cta", "text", "Call to action", required=False,
                      default="Follow for one idea a day"),
    ),
)
