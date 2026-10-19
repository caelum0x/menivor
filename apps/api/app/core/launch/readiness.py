"""Launch readiness: public-launch checklist + what generates with zero paid keys.

Backs ``GET /api/v1/launch/status`` so web/mobile can render a precise
"private beta" state. Everything here is names/booleans only — never a value.

``free_paths`` answers "what can a beta user make right now without any paid
provider key?". It is computed from installed packages, binaries and which
variable NAMES are set, so it is cheap enough for an unauthenticated read.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
from typing import Any, Mapping

from app.core.launch.formats import format_catalog
from app.core.launch_preflight import (
    collect_preflight_warnings,
    missing_public_requirements,
    optional_missing_requirements,
    public_launch_requirements,
    public_tier,
)

# Packaged first-party background loops (no network, no key). Mirrors the
# ``bundled`` + ``asset_path`` entries in ``app.domains.content.background_library``.
_BUNDLED_BACKGROUNDS = ("voxel-parkour", "neon-runner", "synthwave-road")
# Example free (edge-tts) voice names; any ``<locale>-<Name>Neural-<Gender>``
# Microsoft neural voice works through ``services.voice.azure_tts_v1``.
_FREE_VOICE_EXAMPLES = ("en-US-AriaNeural-Female", "en-US-GuyNeural-Male", "tr-TR-EmelNeural-Female")


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _present(env: Mapping[str, str], *names: str) -> bool:
    return any(str(env.get(name, "") or "").strip() for name in names)


def _storage_ready(env: Mapping[str, str]) -> bool:
    return _present(env, "R2_ACCOUNT_ID") and _present(env, "R2_ACCESS_KEY_ID") and _present(
        env, "R2_SECRET_ACCESS_KEY"
    ) and _present(env, "REELFORGE_R2_BUCKET_NAME", "R2_BUCKET_NAME", "R2_BUCKET")


def _llm_keyless() -> bool:
    """True when the configured script LLM needs no paid key (local Ollama)."""
    try:
        from app.config import config

        return str(config.app.get("llm_provider", "") or "").strip().lower() == "ollama"
    except Exception:  # noqa: BLE001 - status must never fail
        return False


def free_paths(env: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """Reel formats and whether each works with zero paid provider keys."""
    env = os.environ if env is None else env
    ffmpeg = shutil.which("ffmpeg") is not None or _has_module("imageio_ffmpeg")
    storage = _storage_ready(env)
    whisper = _has_module("faster_whisper")
    edge = _has_module("edge_tts")
    llm_keyless = _llm_keyless()
    llm_paid = _present(env, "ANTHROPIC_API_KEY")
    stock = _present(env, "PEXELS_API_KEY", "PIXABAY_API_KEY")

    return [
        {
            "id": "captions_only_byov",
            "label": "Captions over your own video",
            "params": {"layout": "captions_only", "screen_recording_key": "<your upload>"},
            "paid_keys": [],
            "available": ffmpeg and storage and whisper,
            "requires": {"ffmpeg": ffmpeg, "object_storage": storage, "local_transcription": whisper},
            "notes": "Your recording's own audio is transcribed locally (faster-whisper); no AI provider is called.",
        },
        {
            "id": "faceless_tts_free_voice",
            "label": "Faceless narrated reel with a free voice",
            "params": {
                "layout": "captions_only",
                "voice_name": _FREE_VOICE_EXAMPLES[0],
                "video_script": "<your script>",
                "background_id": _BUNDLED_BACKGROUNDS[0],
            },
            "paid_keys": [],
            "available": ffmpeg and storage and edge,
            "requires": {"ffmpeg": ffmpeg, "object_storage": storage, "free_tts": edge},
            "free_voices": list(_FREE_VOICE_EXAMPLES),
            "keyless_backgrounds": list(_BUNDLED_BACKGROUNDS),
            "stock_backgrounds": stock,
            "script_generation": "keyless" if llm_keyless else ("configured" if llm_paid else "type_your_own"),
            "notes": (
                "Narrated with Microsoft Edge neural voices (edge-tts, free, needs outbound network). "
                "Type the script yourself unless a script LLM is configured; stock backgrounds need a "
                "free Pexels/Pixabay key, bundled loops need none."
            ),
        },
        {
            "id": "avatar_ugc",
            "label": "AI avatar UGC ad",
            "paid_keys": ["HEYGEN_API_KEY"],
            "available": _present(env, "HEYGEN_API_KEY"),
        },
        {
            "id": "generated_script",
            "label": "AI-written script",
            "paid_keys": [] if llm_keyless else ["ANTHROPIC_API_KEY"],
            "available": llm_keyless or llm_paid,
        },
        {
            "id": "premium_voice",
            "label": "Premium / cloned voices",
            "paid_keys": ["ELEVENLABS_API_KEY"],
            "available": _present(env, "ELEVENLABS_API_KEY"),
        },
        {
            "id": "ai_broll",
            "label": "AI B-roll clips",
            "paid_keys": ["COMFYUI_API_KEY (BROLL_GEN_PROVIDER=comfyui) or a Pixelle endpoint"],
            "available": _present(env, "COMFYUI_API_KEY") or (
                str(env.get("BROLL_GEN_PROVIDER", "") or "").strip().lower() == "pixelle"
            ),
        },
    ]


def readiness_document(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Public-launch checklist + keyless generation paths (names only)."""
    explicit_env = env
    env = os.environ if env is None else env
    requirements = public_launch_requirements(env)
    missing = missing_public_requirements(env)
    catalog = format_catalog(explicit_env)
    return {
        "tier": public_tier(env),
        "public_launch_ready": not missing,
        "requirements": requirements,
        "missing": missing,
        "optional_missing": optional_missing_requirements(env),
        "warnings": collect_preflight_warnings(env),
        "met_count": sum(1 for item in requirements if item["met"]),
        "total_count": len(requirements),
        "available_formats": catalog["available_formats"],
        "locked_formats": catalog["locked_formats"],
        "free_paths": free_paths(env),
    }


__all__ = ["free_paths", "readiness_document"]
