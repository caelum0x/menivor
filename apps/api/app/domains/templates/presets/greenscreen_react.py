"""Seed: greenscreen-react — commentary / hot-take react format.

The creator-commentary staple: an avatar (green-screened) reacts *over* a headline,
screenshot, tweet, or chart. Read-the-headline hook → the breakdown → the hot take →
a divisive CTA that farms comments. The reacted-to image is the background; the
avatar sits foreground.
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="greenscreen-react",
    name="Greenscreen React / Hot Take",
    genre="commentary",
    version="1.0.0",
    description=(
        "Avatar reacts over a headline/screenshot: read-the-headline hook → breakdown → "
        "hot take → divisive comment-bait CTA."
    ),
    aspect="9:16",
    layout="pip",
    default_duration_s=30.0,
    min_duration_s=12.0,
    max_duration_s=55.0,
    caption_style="clean_white",
    camera_motion="none",
    effects=(),
    vfx_intensity=10,
    loopable=False,
    default_background="aerial-nature",
    tags=("commentary", "react", "greenscreen", "hot-take", "news", "faceless"),
    audio=AudioPlanDef(foreground="narration", bgm_prompt="tense subtle underscore, low",
                       duck=True, layers=("narration", "bgm")),
    slots=(
        SlotSpec(role="hook", order=0, t_start_frac=0.0, t_end_frac=0.13, track="primary",
                 audio=("narration",), caption=True, min_s=2.0, max_s=4.0, hook_gate=True,
                 label="Read-the-headline hook", notes="Read the wildest line of the screenshot verbatim."),
        SlotSpec(role="body", order=1, t_start_frac=0.13, t_end_frac=0.62, track="primary",
                 audio=("narration",), caption=True, label="Breakdown",
                 notes="Walk what it actually means; point at the reacted-to image."),
        SlotSpec(role="payoff", order=2, t_start_frac=0.62, t_end_frac=0.86, track="primary",
                 audio=("narration",), caption=True, label="Hot take",
                 notes="The spicy opinion — the reason people quote-share."),
        SlotSpec(role="cta", order=3, t_start_frac=0.86, t_end_frac=1.0, track="primary",
                 audio=("narration",), caption=True, label="Divisive CTA",
                 notes="'Am I wrong? comment.' — bait the reply war."),
    ),
    inputs=(
        TemplateInput("angle", "text", "The take / what you're reacting to", required=True),
        TemplateInput("broll_clip", "clip", "The screenshot / headline / chart to react over", required=False),
        TemplateInput("cta", "text", "Comment-bait CTA", required=False, default="Am I wrong? Comment below"),
    ),
)
