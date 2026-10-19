"""ReelForge caption-engine (Python port) — word timestamps → styled ASS.

Byte-identical to ``@reelforge/caption-engine`` (verified by golden ``.ass``
fixtures) so the client preview and the burned subtitle match. Consumed by
``app/services/captions``.
"""

from .ass_builder import build_ass, format_time
from .color import hex_to_ass
from .style import CaptionStyle, get_preset, list_presets

__all__ = [
    "build_ass",
    "format_time",
    "hex_to_ass",
    "CaptionStyle",
    "get_preset",
    "list_presets",
]
