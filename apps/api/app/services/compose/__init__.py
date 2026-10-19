"""ReelForge pure-FFmpeg compose service.

Composes a HeyGen avatar (green-screen) over a screen recording, burns the
karaoke `.ass` captions, and muxes the ElevenLabs narration into a single
1080x1920 portrait reel — all via one FFmpeg filtergraph (no MoviePy).

Public API mirrors the ReelForge integration contract (§2.6).
"""

from app.services.compose.compose_ffmpeg import (
    _LAYOUTS,
    _escape_ass_filter_path,
    compose_avatar_over_screen,
)
from app.services.compose.transitions import stitch_with_transitions

__all__ = [
    "_LAYOUTS",
    "_escape_ass_filter_path",
    "compose_avatar_over_screen",
    "stitch_with_transitions",
]
