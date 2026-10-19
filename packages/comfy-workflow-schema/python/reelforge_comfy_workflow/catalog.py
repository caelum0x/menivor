"""First-party ComfyUI workflow descriptors + registry (mirror of ``src/catalog``).

Each descriptor pins node commits + weight refs + a typed input contract. The
``services/render/workflows/registry.py`` loads these; adapters reference their
ids. Static reviewed data.
"""

from __future__ import annotations

from typing import Any

_CATALOG: dict[str, dict[str, Any]] = {
    "wan-i2v": {
        "slug": "wan-i2v",
        "category": "i2v",
        "description": "Wan 2.2 image-to-video (A14B).",
        "node_commits": {
            "WanVideoWrapper": "a1b2c3d",
            "ComfyUI-VideoHelperSuite": "e4f5a6b",
        },
        "weight_refs": ["wan2.2-i2v-a14b.safetensors", "umt5-xxl-enc.safetensors"],
        "inputs": [
            {"name": "image", "type": "image", "required": True},
            {"name": "frames", "type": "int", "default": 81, "min": 16, "max": 161},
            {"name": "steps", "type": "int", "default": 20, "min": 1, "max": 60},
        ],
    },
    "flux-first-frame": {
        "slug": "flux-first-frame",
        "category": "t2i",
        "description": "FLUX first-frame T2I (schnell).",
        "node_commits": {"ComfyUI": "8f37cf8"},
        "weight_refs": ["flux1-schnell.safetensors", "t5xxl_fp8.safetensors"],
        "inputs": [
            {"name": "prompt", "type": "string", "required": True},
            {"name": "steps", "type": "int", "default": 4, "min": 1, "max": 12},
        ],
    },
    "lipsync-musetalk": {
        "slug": "lipsync-musetalk",
        "category": "lipsync",
        "description": "MuseTalk real-time lipsync.",
        "node_commits": {"ComfyUI-MuseTalk": "c7d8e9f"},
        "weight_refs": ["musetalk.pth", "sd-vae-ft-mse.safetensors"],
        "inputs": [
            {"name": "video", "type": "video", "required": True},
            {"name": "audio", "type": "audio", "required": True},
        ],
    },
}


def get_workflow(slug: str) -> dict[str, Any]:
    if slug not in _CATALOG:
        raise KeyError(f"unknown workflow {slug!r}")
    return _CATALOG[slug]


def list_workflows(category: str | None = None) -> list[str]:
    slugs = [s for s, w in _CATALOG.items() if category is None or w["category"] == category]
    return sorted(slugs)
