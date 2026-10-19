"""Seed: fake-ai-podcast — two synthetic hosts, mid-conversation hook.

Drop into the spiciest take mid-sentence (auto speaker-tracking frame), speaker-cut
each turn, bold burned-in captions carry the content, punchline/cliffhanger button.
Mode A: AI image → HeyGen/Kling lip-sync two hosts. Mode B (cheap): split-screen
satisfying B-roll top + captions bottom. ~3-min audio clipped to 30–60s.
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="fake-ai-podcast",
    name="Two-Host AI Podcast",
    genre="podcast",
    version="1.0.0",
    description="Two-host synthetic dialogue, mid-convo hook, speaker-cut turns, bold captions.",
    layout="split",
    default_duration_s=50.0,
    min_duration_s=30.0,
    max_duration_s=60.0,
    caption_style="bold_violet",
    camera_motion="none",
    effects=(),
    loopable=False,
    default_background="generic-parkour",
    tags=("podcast", "dialogue", "faceless"),
    audio=AudioPlanDef(foreground="dialogue", bgm_prompt="", duck=True, layers=("dialogue",)),
    slots=(
        SlotSpec(role="hook", order=0, t_start_frac=0.0, t_end_frac=0.06,
                 track="primary", audio=("dialogue",), caption=True, min_s=2.0, max_s=4.0,
                 hook_gate=True, label="Mid-Convo Hook", notes="Drop into the spiciest take mid-sentence."),
        SlotSpec(role="exchange", order=1, t_start_frac=0.06, t_end_frac=0.9,
                 track="primary", audio=("dialogue",), caption=True,
                 label="Exchange", notes="Speaker-cut each turn; captions carry the content."),
        SlotSpec(role="button", order=2, t_start_frac=0.9, t_end_frac=1.0,
                 track="primary", audio=("dialogue",), caption=True, label="Button",
                 notes="Punchline / cliffhanger."),
    ),
    inputs=(
        TemplateInput("topic", "text", "Podcast topic / script", required=True),
        TemplateInput("mode", "choice", "Render mode", required=False,
                      choices=("lipsync", "split_broll"), default="split_broll"),
        TemplateInput("broll_clip", "clip", "B-roll (split mode)", required=False),
    ),
)
