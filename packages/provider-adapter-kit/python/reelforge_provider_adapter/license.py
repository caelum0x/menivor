"""License-class registry + paying-user exclusion rule (mirror of ``src/license``).

Extracted so the routing engine, SDKs, and burn-preview UIs agree on which model
weights are safe for paid/commercial output. Feeds ``routing/_license_class.py``.
"""

from __future__ import annotations

# commercial-safe = usable for paying customers' commercial output.
# non-commercial  = weights forbid paid/commercial use (research only).
# territorial     = commercial-OK but with regional / scale caveats — gate.
LICENSE_CLASSES: tuple[str, ...] = ("commercial-safe", "non-commercial", "territorial")

LICENSE_REGISTRY: dict[str, str] = {
    "wan/wan-2.2": "commercial-safe",
    "lightricks/ltx-video": "commercial-safe",
    "black-forest-labs/flux-schnell": "commercial-safe",
    "genmo/mochi-1": "commercial-safe",
    "kwaivgi/kling-v1.6": "commercial-safe",
    "black-forest-labs/flux-dev": "non-commercial",
    "coqui/xtts-v2": "non-commercial",
    "SWivid/f5-tts": "non-commercial",
    "stabilityai/stable-video-diffusion": "non-commercial",
    "tencent/hunyuan-video": "territorial",
    "THUDM/cogvideox-5b": "territorial",
}


def license_class(model_id: str) -> str:
    """License class for a model (defaults to ``territorial`` = gate-before-use)."""
    return LICENSE_REGISTRY.get(model_id, "territorial")


def can_use_for_paid(model_id: str) -> bool:
    """May a paying customer use this model for commercial output?"""
    return license_class(model_id) == "commercial-safe"
