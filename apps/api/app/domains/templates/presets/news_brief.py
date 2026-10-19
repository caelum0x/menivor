"""Seed: news-brief — the fast, neutral "here's what happened" update.

A crisp news/update format: a headline hook, the essential context, the body of
what happened, why-it-matters payoff, and a follow-for-updates CTA. Clean white
captions and a locked frame give it a credible, wire-service feel — the format for
niche news pages (tech, sports, crypto, local) that post the story of the day.
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="news-brief",
    name="News Brief",
    genre="news",
    version="1.0.0",
    description=(
        "Fast, neutral update: headline hook → essential context → what happened → why it "
        "matters → follow-for-updates CTA. Clean captions, credible wire-service feel."
    ),
    aspect="9:16",
    layout="full",
    default_duration_s=35.0,
    min_duration_s=15.0,
    max_duration_s=70.0,
    caption_style="clean_white",
    camera_motion="none",
    effects=(),
    vfx_intensity=10,
    loopable=False,
    default_background="aerial-nature",
    tags=("news", "update", "brief", "headline", "faceless", "explainer"),
    audio=AudioPlanDef(foreground="narration", bgm_prompt="neutral news underscore, steady pulse, subtle",
                       duck=True, layers=("narration", "bgm")),
    slots=(
        SlotSpec(role="hook", order=0, t_start_frac=0.0, t_end_frac=0.10, track="full",
                 audio=("narration",), caption=True, min_s=1.5, max_s=3.5, hook_gate=True,
                 label="Headline hook", notes="Lead with the single most important fact — the headline."),
        SlotSpec(role="setup", order=1, t_start_frac=0.10, t_end_frac=0.28, track="full",
                 audio=("narration",), caption=True, label="Context",
                 notes="One line of background so the story makes sense to a cold viewer."),
        SlotSpec(role="body", order=2, t_start_frac=0.28, t_end_frac=0.80, track="full",
                 audio=("narration",), caption=True, label="What happened",
                 notes="The facts in order; attribute claims; stay neutral."),
        SlotSpec(role="payoff", order=3, t_start_frac=0.80, t_end_frac=0.92, track="full",
                 audio=("narration",), caption=True, label="Why it matters",
                 notes="The 'so what' — the impact on the viewer or the space."),
        SlotSpec(role="cta", order=4, t_start_frac=0.92, t_end_frac=1.0, track="full",
                 audio=("narration",), caption=True, label="Follow CTA",
                 notes="'Follow for the story of the day.'"),
    ),
    inputs=(
        TemplateInput("topic", "text", "The story (headline or a link/summary to cover)", required=True),
        TemplateInput("broll_clip", "clip", "B-roll footage (optional)", required=False),
    ),
)
