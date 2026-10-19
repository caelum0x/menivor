"""Seed: anime-beat-edit — beat-synced montage, hardest frame first.

Single hardest-hitting frame as the hook, clips trimmed to STORY BEATS (not
seconds), fast cuts on the beat with zoom-in transitions + animated text and a
-2/-3 frame nudge. Trending track (edit muted → re-add native song on upload).
Full 9:16, never letterboxed.
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef, TemplateInput
from ..slots import AudioPlanDef, SlotSpec

TEMPLATE = ShotTemplateDef(
    slug="anime-beat-edit",
    name="Anime Beat Edit",
    genre="edit",
    version="1.0.0",
    description="Beat-synced montage; hardest frame first; story-beat trims; native trending audio on upload.",
    layout="full",
    default_duration_s=20.0,
    min_duration_s=8.0,
    max_duration_s=40.0,
    caption_style="clean_white",
    camera_motion="crash_zoom_in",
    effects=("glow", "light_leak"),
    vfx_intensity=55,
    loopable=False,
    default_background="aerial-nature",
    tags=("anime", "edit", "beat", "amv"),
    audio=AudioPlanDef(foreground="trend_audio", bgm_prompt="", duck=False, trend_relink=True,
                       layers=("trend_audio",)),
    slots=(
        SlotSpec(role="hook", order=0, t_start_frac=0.0, t_end_frac=0.08,
                 track="full", audio=("trend_audio",), caption=False, min_s=1.0, max_s=1.5,
                 hook_gate=True, label="Hardest Frame", notes="Single hardest-hitting frame."),
        SlotSpec(role="body", order=1, t_start_frac=0.08, t_end_frac=0.92,
                 track="full", audio=("trend_audio",), caption=True,
                 label="Beat Body", notes="Story-beat trims, fast cuts on beats, -2/-3 frame nudge."),
        SlotSpec(role="payoff", order=2, t_start_frac=0.92, t_end_frac=1.0,
                 track="full", audio=("trend_audio",), caption=False, label="Final Hit"),
    ),
    inputs=(
        TemplateInput("clips", "clip", "Source clips", required=True,
                      help="One or more clips; trimmed to beats."),
        TemplateInput("track", "text", "Trending track name", required=False,
                      help="Re-add the exact native sound on upload for the trending-audio page."),
    ),
)
