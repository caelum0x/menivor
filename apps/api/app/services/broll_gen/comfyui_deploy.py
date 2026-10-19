"""Compatibility alias for the ComfyUI B-roll provider."""

import sys

from app.domains.broll.providers import comfyui_deploy as _implementation

sys.modules[__name__] = _implementation
