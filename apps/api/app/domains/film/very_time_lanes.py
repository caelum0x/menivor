"""Which provider runs each Very ___ Time step, chosen by the keys this deployment has.

Pure functions over an environment mapping (``os.environ`` by default; tests pass
their own). No secrets are returned, only which lanes are live. Explicit model
env overrides always win over the automatic choice.

=============  ==========================================  ==========================================
Step           Preferred (key)                              Replicate fallback (REPLICATE_API_TOKEN)
=============  ==========================================  ==========================================
stills, refs   Seedream 4.5 edit on fal (FAL_KEY)          Seedream 4.5 on Replicate (image_input)
stills, text   Ideogram v3 on fal (FAL_KEY)                Ideogram v3 Turbo on Replicate (lettering)
video          ModelArk (ARK_API_KEY), then fal            Seedance 2.0 on Replicate (i2v / r2v)
voice          ElevenLabs v3 (ELEVENLABS_API_KEY)          MiniMax Speech 02 HD; free chain otherwise
sound effects  ElevenLabs Sound Effects                    Stable Audio 2.5 (not MMAudio: NC weights)
lip-sync       MuseTalk (MUSETALK_API_KEY + base URL)      sync lipsync-2 on Replicate
=============  ==========================================  ==========================================
"""

from __future__ import annotations

import os
from typing import Mapping

FAL, ARK, REPLICATE, ELEVENLABS, MUSETALK = "fal", "ark", "replicate", "elevenlabs", "musetalk"

IMAGE_ENV = "VERY_TIME_IMAGE_MODEL"
REFERENCE_IMAGE_ENV = "VERY_TIME_REFERENCE_IMAGE_MODEL"
VIDEO_ENV = "VERY_TIME_VIDEO_MODEL"
REFERENCE_VIDEO_ENV = "VERY_TIME_REFERENCE_VIDEO_MODEL"

IMAGE_MODELS = {FAL: "ideogram/ideogram-v3", REPLICATE: "ideogram-ai/ideogram-v3-turbo"}
# Replicate: Nano Banana Pro, proven on the Oxhan episode renders (sheet + stills, lettering correct).
REFERENCE_IMAGE_MODELS = {FAL: "bytedance-seed/seedream-4.5-edit", REPLICATE: "google/nano-banana-pro-replicate"}
VIDEO_MODELS = {ARK: "bytedance/seedance-2.0-i2v-ark", FAL: "bytedance/seedance-2.0-i2v",
                REPLICATE: "bytedance/seedance-2.0-i2v-replicate"}
REFERENCE_VIDEO_MODELS = {ARK: "bytedance/seedance-2.0-r2v-ark", FAL: "bytedance/seedance-2.0-r2v",
                          REPLICATE: "bytedance/seedance-2.0-r2v-replicate"}


def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def _set(env: Mapping[str, str], name: str) -> bool:
    return bool(str(env.get(name) or "").strip())


def _elevenlabs(env: Mapping[str, str], use_config: bool) -> bool:
    if _set(env, "ELEVENLABS_API_KEY"):
        return True
    if not use_config:
        return False
    try:
        from app.config import config

        return bool(str(config.elevenlabs.get("api_key", "") or "").strip())
    except Exception:  # noqa: BLE001 - no config means no key
        return False


def keys(env: Mapping[str, str] | None = None) -> dict[str, bool]:
    """Which provider keys are present (booleans only)."""
    e = _env(env)
    return {
        FAL: _set(e, "FAL_KEY"),
        ARK: _set(e, "ARK_API_KEY"),
        REPLICATE: _set(e, "REPLICATE_API_TOKEN"),
        ELEVENLABS: _elevenlabs(e, use_config=env is None),
        MUSETALK: _set(e, "MUSETALK_API_KEY") and _set(e, "MUSETALK_BASE_URL"),
    }


def _first(order: tuple[str, ...], table: Mapping[str, str], have: Mapping[str, bool]) -> str | None:
    return next((table[k] for k in order if have.get(k) and k in table), None)


def image_model(with_refs: bool, env: Mapping[str, str] | None = None) -> str | None:
    e = _env(env)
    override = str(e.get(REFERENCE_IMAGE_ENV if with_refs else IMAGE_ENV) or "").strip()
    if override:
        return override
    return _first((FAL, REPLICATE), REFERENCE_IMAGE_MODELS if with_refs else IMAGE_MODELS, keys(env))


def video_model(with_refs: bool, env: Mapping[str, str] | None = None) -> str | None:
    e = _env(env)
    override = str(e.get(REFERENCE_VIDEO_ENV if with_refs else VIDEO_ENV) or "").strip()
    if override:
        return override
    return _first((ARK, FAL, REPLICATE), REFERENCE_VIDEO_MODELS if with_refs else VIDEO_MODELS, keys(env))


def voice_backend(env: Mapping[str, str] | None = None) -> str:
    have = keys(env)
    return ELEVENLABS if have[ELEVENLABS] else (REPLICATE if have[REPLICATE] else "free")


def sfx_backend(env: Mapping[str, str] | None = None) -> str:
    have = keys(env)
    return ELEVENLABS if have[ELEVENLABS] else (REPLICATE if have[REPLICATE] else "")


def lipsync_backend(env: Mapping[str, str] | None = None) -> str:
    have = keys(env)
    return MUSETALK if have[MUSETALK] else (REPLICATE if have[REPLICATE] else "")


def summary(env: Mapping[str, str] | None = None) -> dict[str, object]:
    """What the plan screen can say is live (model ids and backend names; never keys)."""
    return {
        "image_model": image_model(False, env), "reference_image_model": image_model(True, env),
        "video_model": video_model(False, env), "reference_video_model": video_model(True, env),
        "voice": voice_backend(env), "sfx": sfx_backend(env), "lipsync": lipsync_backend(env),
    }


__all__ = ["ARK", "ELEVENLABS", "FAL", "MUSETALK", "REPLICATE", "image_model", "keys", "lipsync_backend",
           "sfx_backend", "summary", "video_model", "voice_backend"]
