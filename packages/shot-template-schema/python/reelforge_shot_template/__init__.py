"""ReelForge shot-template-schema (Python port) — genre segment-slot templates.

Byte-identical to ``@reelforge/shot-template-schema`` (golden fixtures) so the
``templates/`` domain, the pickers, and render-core all read one definition.
"""

from .presets import get_preset, list_presets
from .roles import ROLE_ORDER, is_role, role_index
from .template import (
    content_hash,
    make_slot,
    make_template,
    total_duration_ms,
    validate_template,
)

__all__ = [
    "ROLE_ORDER",
    "is_role",
    "role_index",
    "make_slot",
    "make_template",
    "validate_template",
    "total_duration_ms",
    "content_hash",
    "get_preset",
    "list_presets",
]
