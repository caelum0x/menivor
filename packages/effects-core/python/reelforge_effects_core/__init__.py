"""ReelForge effects-core (Python port) — camera + VFX preset kernels.

Pure, deterministic kernel math shared bit-for-bit with the TypeScript package
(``@reelforge/effects-core``) so previews and the render executor agree. Feeds
``app/services/compose/vfx.py``.
"""

from . import easing, ffexpr, kernels, registry
from .registry import CAMERA, VFX, apply, category_of, get_kernel, list_kernels

__all__ = [
    "easing",
    "ffexpr",
    "kernels",
    "registry",
    "apply",
    "get_kernel",
    "category_of",
    "list_kernels",
    "CAMERA",
    "VFX",
]
