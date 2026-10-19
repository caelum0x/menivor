"""Populate the routing registry with adapters whose credentials are present.

Called by the worker/ops at startup (behind the launch flag) — never at import
time — so only providers with configured credentials become routable. A model
still needs to be promoted live in the catalog before a client can select it;
registering an adapter merely makes the outbound protocol available.
"""

from __future__ import annotations

import os
from typing import Mapping

from loguru import logger

from app.domains.routing.base import ProviderRegistry, registry as default_registry
from app.domains.routing.providers.elevenlabs import ElevenLabsAdapter
from app.domains.routing.providers.heygen import HeyGenAdapter
from app.domains.routing.providers.image import ImageAdapter
from app.domains.routing.providers.kokoro import KokoroTTSAdapter, kokoro_url
from app.domains.routing.providers.openrouter import OpenRouterAdapter
from app.domains.routing.providers.pixelle import PixelleAdapter
from app.domains.routing.providers.sadtalker import SadTalkerAdapter
from app.domains.routing.providers.tts import SelfHostTTSAdapter
from app.domains.routing.providers.wan_camera import WanCameraAdapter

# Image providers served by the shared ImageAdapter: (provider_key, base_url).
_IMAGE_PROVIDERS: tuple[tuple[str, str], ...] = (
    ("stability", "https://api.stability.ai"),
    ("black-forest-labs", "https://api.bfl.ai"),
    ("ideogram", "https://api.ideogram.ai"),
    ("recraft", "https://external.api.recraft.ai"),
)

_IMAGE_BASE_URLS: dict[str, str] = dict(_IMAGE_PROVIDERS)

# Self-hosted / free voice fallbacks served by the shared SelfHostTTSAdapter.
_TTS_PROVIDERS: tuple[tuple[str, str], ...] = (
    ("chatterbox", "https://chatterbox.internal.reelforge.app"),
    ("kokoro", "https://kokoro.internal.reelforge.app"),
    ("edge", "https://edge-tts.internal.reelforge.app"),
)

_TTS_BASE_URLS: dict[str, str] = dict(_TTS_PROVIDERS)


def build_adapter(provider_key: str, api_key: str):
    """Construct a fresh adapter for ``provider_key`` using ``api_key``.

    Used for BYOK: a per-request adapter bound to the customer's own credential
    (never the platform key). Returns ``None`` for an unknown provider.
    """
    key = (provider_key or "").strip()
    if key == "openrouter":
        return OpenRouterAdapter(api_key=api_key)
    if key == "elevenlabs":
        return ElevenLabsAdapter(api_key=api_key)
    if key == "heygen":
        return HeyGenAdapter(api_key=api_key)
    if key == "pixelle":
        return PixelleAdapter(api_key=api_key)
    if key == "sadtalker":
        return SadTalkerAdapter(api_key=api_key)
    if key == "wan_camera":
        # Opt-in local ComfyUI backend ($0-wallet path): requires no cloud
        # credential, only WAN_CAMERA_BACKEND=local + a COMFYUI_LOCAL_URL.
        if os.getenv("WAN_CAMERA_BACKEND", "remote").strip().lower() == "local" and os.getenv(
            "COMFYUI_LOCAL_URL"
        ):
            from app.domains.routing.providers.wan_camera_local import WanCameraLocalAdapter

            return WanCameraLocalAdapter(base_url=os.getenv("COMFYUI_LOCAL_URL", ""))
        return WanCameraAdapter(
            api_key=api_key,
            base_url=os.getenv("WAN_CAMERA_BASE_URL")
            or os.getenv("COMFY_DEPLOY_BASE_URL"),
        )
    if key == "lora_train":
        from app.domains.routing.providers.lora_train import LoRATrainAdapter

        return LoRATrainAdapter(
            api_key=api_key,
            base_url=os.getenv("LORA_TRAIN_BASE_URL") or None,
        )
    if key in _IMAGE_BASE_URLS:
        return ImageAdapter(
            provider_key=key, base_url=_IMAGE_BASE_URLS[key], api_key=api_key
        )
    if key == "kokoro" and kokoro_url():
        # Real Kokoro-FastAPI sidecar (OpenAI-compatible /v1/audio/speech).
        return KokoroTTSAdapter(base_url=kokoro_url())
    if key in _TTS_BASE_URLS:
        return SelfHostTTSAdapter(
            provider_key=key, base_url=_TTS_BASE_URLS[key], api_key=api_key
        )
    from app.domains.routing.providers.async_media import PROVIDER_CONFIGS, AsyncMediaAdapter

    if key in PROVIDER_CONFIGS:
        return AsyncMediaAdapter(PROVIDER_CONFIGS[key], api_key=api_key)
    return None


def _env_key(provider_key: str) -> str:
    return f"{provider_key.upper().replace('-', '_')}_API_KEY"


def register_available_adapters(
    reg: ProviderRegistry | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    """Register adapters whose API keys are set in ``env``. Returns their keys.

    Idempotent (registration is keyed), safe to call repeatedly. Providers
    without a configured key are skipped so an unconfigured provider can never
    become a live route.
    """
    reg = reg or default_registry
    env = env if env is not None else os.environ
    registered: list[str] = []

    if env.get("OPENROUTER_API_KEY"):
        reg.register(OpenRouterAdapter(api_key=env["OPENROUTER_API_KEY"]))
        registered.append("openrouter")
    if env.get("ELEVENLABS_API_KEY"):
        reg.register(ElevenLabsAdapter(api_key=env["ELEVENLABS_API_KEY"]))
        registered.append("elevenlabs")
    if env.get("HEYGEN_API_KEY"):
        reg.register(HeyGenAdapter(api_key=env["HEYGEN_API_KEY"]))
        registered.append("heygen")
    if env.get("PIXELLE_API_KEY"):
        reg.register(PixelleAdapter(api_key=env["PIXELLE_API_KEY"]))
        registered.append("pixelle")
    if env.get("SADTALKER_API_KEY"):
        reg.register(SadTalkerAdapter(api_key=env["SADTALKER_API_KEY"]))
        registered.append("sadtalker")

    # Wan2.2-Fun model-native camera control. Two mutually-exclusive backends under
    # the same "wan_camera" key:
    #   * LOCAL (opt-in, $0-wallet): WAN_CAMERA_BACKEND=local + COMFYUI_LOCAL_URL —
    #     a native LOCAL/LAN ComfyUI server, needs NO cloud credential.
    #   * REMOTE (default): ComfyUI-Deploy token (or a dedicated Wan camera key).
    # Wan is open-weights (Apache-2.0), so either route is paid-safe.
    if env.get("WAN_CAMERA_BACKEND", "remote").strip().lower() == "local" and env.get(
        "COMFYUI_LOCAL_URL"
    ):
        from app.domains.routing.providers.wan_camera_local import WanCameraLocalAdapter

        reg.register(WanCameraLocalAdapter(base_url=env.get("COMFYUI_LOCAL_URL", "")))
        registered.append("wan_camera")
    else:
        wan_camera_key = env.get("COMFY_DEPLOY_TOKEN") or env.get("WAN_CAMERA_API_KEY")
        if wan_camera_key:
            reg.register(
                WanCameraAdapter(
                    api_key=wan_camera_key,
                    base_url=env.get("WAN_CAMERA_BASE_URL")
                    or env.get("COMFY_DEPLOY_BASE_URL"),
                    workflow_id=env.get("WAN_CAMERA_WORKFLOW_ID", ""),
                )
            )
            registered.append("wan_camera")

    # Wave-4 character LoRA training (capability ``lora_train``). Gated behind a
    # Replicate or ComfyUI-Deploy token (same credential family as wan_camera).
    # Trained weights are open (Wan-2.2), so this route is paid-safe.
    lora_train_key = env.get("REPLICATE_API_TOKEN") or env.get("COMFY_DEPLOY_TOKEN")
    if lora_train_key:
        from app.domains.routing.providers.lora_train import LoRATrainAdapter

        reg.register(
            LoRATrainAdapter(
                api_key=lora_train_key,
                base_url=env.get("LORA_TRAIN_BASE_URL") or None,
            )
        )
        registered.append("lora_train")

    # Async media providers (video/music: Kling/Runway/Luma/Veo/Suno) — each
    # registered only when its API key is present so an unconfigured provider is
    # never a live route.
    from app.domains.routing.providers.async_media import (
        PROVIDER_CONFIGS,
        AsyncMediaAdapter,
        env_var_for,
    )

    for provider_key, cfg in PROVIDER_CONFIGS.items():
        # Reference-only providers (e.g. HunyuanVideo: non-commercial + EU/UK/KR
        # territorial caveat) are never a default live route — skip unless an
        # explicit per-provider reference flag opts them in.
        if cfg.reference_only and not env.get(
            f"REELFORGE_ENABLE_{provider_key.upper()}_REFERENCE"
        ):
            continue
        # Resolve via the config's declared env var so providers sharing a vendor
        # credential (e.g. fal.ai models -> FAL_API_KEY) are discovered correctly.
        key = env.get(env_var_for(provider_key))
        if key:
            reg.register(AsyncMediaAdapter(cfg, api_key=key))
            registered.append(provider_key)

    # Wan 2.2 on Replicate (open-weights, Apache-2.0) — the equivalent-fallback
    # video candidate. Registered only when a Replicate token is present so an
    # unconfigured provider is never a live route.
    replicate_token = env.get("REPLICATE_API_TOKEN")
    if replicate_token:
        from app.domains.routing.providers.wan_replicate import WanAdapter

        reg.register(WanAdapter(api_key=replicate_token))
        registered.append("wan")

    for provider_key, base_url in _IMAGE_PROVIDERS:
        key = env.get(_env_key(provider_key))
        if key:
            reg.register(
                ImageAdapter(
                    provider_key=provider_key, base_url=base_url, api_key=key
                )
            )
            registered.append(provider_key)

    # Kokoro: when KOKORO_URL points at the Kokoro-FastAPI sidecar (infra-box
    # stacks/kokoro, off by default) register the real HTTP adapter; the generic
    # SelfHostTTSAdapter slot below is then skipped for "kokoro".
    kokoro_base = kokoro_url(env)
    if kokoro_base:
        reg.register(KokoroTTSAdapter(base_url=kokoro_base))
        registered.append("kokoro")

    for provider_key, base_url in _TTS_PROVIDERS:
        if provider_key == "kokoro" and kokoro_base:
            continue
        # Self-hosted TTS may need only a base URL (EdgeTTS is unauthenticated);
        # register when a key OR an explicit enable flag is present.
        key = env.get(_env_key(provider_key))
        enabled = env.get(f"REELFORGE_ENABLE_{provider_key.upper()}_TTS")
        if key or enabled:
            reg.register(
                SelfHostTTSAdapter(
                    provider_key=provider_key, base_url=base_url, api_key=key or ""
                )
            )
            registered.append(provider_key)

    # Open lipsync providers (speak capability: image + audio -> talking video).
    # MuseTalk / LatentSync ship open weights, so either is paid-safe; each is
    # registered only when its API key OR an explicit enable flag is present so an
    # unconfigured provider is never a live route.
    from app.domains.routing.providers._lipsync import (
        LIPSYNC_CONFIGS,
        LipsyncAdapter,
    )

    for provider_key, cfg in LIPSYNC_CONFIGS.items():
        key = env.get(_env_key(provider_key))
        enabled = env.get(f"REELFORGE_ENABLE_{provider_key.upper()}_LIPSYNC")
        if key or enabled:
            reg.register(LipsyncAdapter(cfg, api_key=key or ""))
            registered.append(provider_key)

    if registered:
        logger.info(f"routing: registered provider adapters: {registered}")
    return registered
