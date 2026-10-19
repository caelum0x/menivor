"""Seed: story over gameplay split — the flagship dual-stimulation format.

Internal slug ``minecraft-reddit-split`` (kept for the shared schema and stored
channels); the API shows ``story-gameplay-split`` (see ``aliases``).

Top ~55% = AI-voiced story (a pasted thread or your own) with karaoke captions;
bottom ~45% = uninterrupted original looping parkour for baseline-retention
dopamine. Cold-open the most shocking sentence FIRST, tension bump every ~5s,
Part-2 loop CTA. 9:16, 30–60s.
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="minecraft-reddit-split",
    name="Story × Gameplay Split",
    genre="brainrot-split",
    version="1.0.0",
    description=(
        "Top narrated story + karaoke captions over bottom looping parkour. "
        "Cold-open the spiciest line first; keep the gameplay uninterrupted."
    ),
    layout="split",
    default_duration_s=45.0,
    min_duration_s=20.0,
    max_duration_s=60.0,
    caption_style="karaoke_yellow",
    camera_motion="none",
    effects=(),
    loopable=True,
    default_background="voxel-parkour",
    tags=("gameplay", "faceless", "story"),
    audio=AudioPlanDef(
        foreground="narration",
        bgm_prompt="chill lo-fi hip hop, low energy, background",
        duck=True,
        layers=("narration", "gameplay_sfx", "bgm"),
    ),
    slots=(
        SlotSpec(
            role="hook", order=0, t_start_frac=0.0, t_end_frac=0.045,
            track="primary", audio=("narration",), caption=True,
            transition_out="cut", min_s=1.5, max_s=3.0, hook_gate=True,
            label="Cold-Open Hook",
            notes="Most shocking sentence FIRST + big title card; must clear 70% first-3s.",
        ),
        SlotSpec(
            role="setup", order=1, t_start_frac=0.045, t_end_frac=0.22,
            track="primary", audio=("narration", "gameplay_sfx"), caption=True,
            label="Setup", notes="Where the story comes from + framing; parkour uninterrupted below.",
        ),
        SlotSpec(
            role="rising", order=2, t_start_frac=0.22, t_end_frac=0.7,
            track="primary", audio=("narration", "gameplay_sfx"), caption=True,
            label="Rising Action", notes="Tension bump every ~5s.",
        ),
        SlotSpec(
            role="climax", order=3, t_start_frac=0.7, t_end_frac=0.88,
            track="primary", audio=("narration", "gameplay_sfx"), caption=True,
            label="Climax / Twist",
        ),
        SlotSpec(
            role="cta", order=4, t_start_frac=0.88, t_end_frac=1.0,
            track="primary", audio=("narration",), caption=True,
            label="Loop-back / CTA", notes="'Part 2?' / comment-bait.",
        ),
    ),
    inputs=(
        TemplateInput("story", "text", "Story / script", required=True,
                      help="Paste the story; the hook line goes first."),
        TemplateInput("gameplay_clip", "clip", "Looping gameplay clip", required=False,
                      help="Parkour loop clip R2 key; a library loop is used if omitted."),
        TemplateInput("subject", "text", "Subject / title", required=False),
        TemplateInput("voice_id", "choice", "Narration voice", required=False),
    ),
)
