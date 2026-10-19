"""Seed: brainrot-ai-meme — absurdist recurring AI character, serialized.

0–1.5s jarring AI character + catchphrase (pure pattern-interrupt), escalating
nonsense synced to a signature repetitive sound (each beat more exaggerated),
meme resolution or loop-back. Numbered/serialized (Italian-brainrot style). 9:16
8–15s. Bold centered 1–2-word ALL-CAPS pop-ins.
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="brainrot-ai-meme",
    name="Brainrot AI Meme",
    genre="meme",
    version="1.0.0",
    description="Recurring AI character, catchphrase pattern-interrupt, escalating nonsense to a signature sound.",
    layout="full",
    default_duration_s=12.0,
    min_duration_s=8.0,
    max_duration_s=15.0,
    caption_style="bold_violet",
    camera_motion="crash_zoom_in",
    effects=("glitch",),
    vfx_intensity=70,
    loopable=True,
    default_background="neon-runner",
    tags=("brainrot", "meme", "serialized", "character"),
    audio=AudioPlanDef(foreground="narration", bgm_prompt="", duck=False, layers=("narration", "sfx")),
    slots=(
        SlotSpec(role="hook", order=0, t_start_frac=0.0, t_end_frac=0.12,
                 track="full", audio=("narration", "sfx"), caption=True, min_s=1.0, max_s=1.5,
                 hook_gate=True, label="Absurd Hook", notes="AI character + catchphrase; pure pattern-interrupt."),
        SlotSpec(role="escalation", order=1, t_start_frac=0.12, t_end_frac=0.75,
                 track="full", audio=("narration", "sfx"), caption=True, label="Escalation",
                 notes="Rapid nonsense synced to a signature repetitive sound; each beat more exaggerated."),
        SlotSpec(role="payoff", order=2, t_start_frac=0.75, t_end_frac=1.0,
                 track="full", audio=("narration", "sfx"), caption=True, label="Payoff / Loop-back"),
    ),
    inputs=(
        TemplateInput("character", "text", "Recurring character name", required=True),
        TemplateInput("bit", "text", "The bit / catchphrase", required=True),
        TemplateInput("episode", "number", "Episode number", required=False, default="1"),
    ),
)
