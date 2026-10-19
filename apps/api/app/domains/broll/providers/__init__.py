"""Provider registry for ReelForge's standalone AI B-roll domain."""

from loguru import logger

from app.domains.broll.providers.base import (
    BROLL_GEN_PROVIDERS,
    BrollGenProvider,
    get_broll_provider,
    register_broll_provider,
)

try:
    from app.domains.broll.providers import comfyui_deploy as _comfyui_deploy  # noqa: F401
except Exception as exc:  # noqa: BLE001
    logger.warning(f"comfyui broll_gen provider unavailable: {exc}")

try:
    from app.domains.broll.providers import pixelle as _pixelle  # noqa: F401
except Exception as exc:  # noqa: BLE001
    logger.warning(f"pixelle broll_gen provider unavailable: {exc}")

try:
    from app.domains.broll.providers import replicate_wan as _replicate_wan  # noqa: F401
except Exception as exc:  # noqa: BLE001
    logger.warning(f"replicate broll_gen provider unavailable: {exc}")

__all__ = [
    "BROLL_GEN_PROVIDERS",
    "BrollGenProvider",
    "get_broll_provider",
    "register_broll_provider",
]
