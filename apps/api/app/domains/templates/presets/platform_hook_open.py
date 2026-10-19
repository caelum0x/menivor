"""Seed: platform-hook-open — composable 0–5s opener prefix for any genre.

0–0.5s cold-open pattern interrupt (hard cut/whip-pan/snap-zoom, big high-contrast
text, no logo, no 'hey guys', lands with sound off) → 0.5–3s multimodal hook
(visual interrupt + benefit text + keyword-rich spoken opening) → 3–5s explicit
promise/payoff-preview, ends with a loop-back last-frame-matches-frame-1.
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="platform-hook-open",
    name="Platform Hook Opener",
    genre="opener",
    version="1.0.0",
    description="Composable 0–5s cold-open: pattern-interrupt → multimodal hook → promise → loop-back.",
    layout="full",
    default_duration_s=5.0,
    min_duration_s=3.0,
    max_duration_s=6.0,
    caption_style="karaoke_yellow",
    camera_motion="whip_pan",
    effects=("glitch",),
    vfx_intensity=60,
    loopable=True,
    default_background="neon-runner",
    tags=("hook", "opener", "prefix", "retention"),
    audio=AudioPlanDef(foreground="narration", bgm_prompt="", duck=True, layers=("narration", "sfx")),
    slots=(
        SlotSpec(role="hook", order=0, t_start_frac=0.0, t_end_frac=0.1,
                 track="full", audio=("sfx",), caption=True, transition_out="cut",
                 min_s=0.3, max_s=0.6, hook_gate=True, label="Pattern Interrupt",
                 notes="Hard cut/whip-pan; big high-contrast text; lands with sound off."),
        SlotSpec(role="setup", order=1, t_start_frac=0.1, t_end_frac=0.6,
                 track="full", audio=("narration",), caption=True, label="Multimodal Hook",
                 notes="Visual interrupt + benefit text + keyword-rich spoken opening; target <40% swipe."),
        SlotSpec(role="payoff", order=2, t_start_frac=0.6, t_end_frac=1.0,
                 track="full", audio=("narration",), caption=True, label="Promise / Payoff-Preview",
                 notes="Explicit promise; loop-back last frame == frame 1."),
    ),
    inputs=(
        TemplateInput("promise", "text", "The promise / payoff", required=True),
        TemplateInput("keyword", "text", "SEO keyword phrase", required=False),
    ),
)
