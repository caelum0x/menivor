"""ReelForge render-core (Python port) — RenderSpec → FFmpeg filtergraph.

Byte-identical to ``@reelforge/render-core`` (golden fixtures) so the client
preview and the executor (``app/services/compose/compose_ffmpeg.py``) build the
same composition graph. This package owns spec→string only; the Celery worker
spawns FFmpeg. The composition (``[comp]``) and the ducked-audio (``[aout]``)
fragments are reproduced byte-for-byte from the executor; the executor's
environment-specific caption-burn / watermark finishing is layered on top of the
``[comp]`` sink at render time and is out of this shared byte-identical contract.
"""

from .filtergraph import (
    build_audio_graph,
    build_filtergraph,
    build_video_graph,
    has_audio_out,
    video_out_label,
)
from .spec import AVATAR_LAYOUTS, LAYOUTS, make_spec, validate_spec

__all__ = [
    "build_filtergraph",
    "build_video_graph",
    "build_audio_graph",
    "video_out_label",
    "has_audio_out",
    "make_spec",
    "validate_spec",
    "LAYOUTS",
    "AVATAR_LAYOUTS",
]
