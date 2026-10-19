"""ReelForge talking-head avatar providers.

This package exposes a provider-registry abstraction (mirroring MPT's
``_VIDEO_MUSIC_PROVIDERS`` shape in ``app/services/task.py``) so avatar
backends (HeyGen today, others later) can be swapped or mocked behind a
single ``TalkingHeadProvider`` Protocol.

Public surface:
    - ``TalkingHeadProvider``  — runtime-checkable Protocol (§2.3)
    - ``AVATAR_PROVIDERS``     — name -> provider registry
    - ``get_avatar_provider``  — resolve a provider by id
    - ``register_avatar_provider`` — used by provider modules at import time
"""

from loguru import logger

from app.services.avatar.base import (
    AVATAR_PROVIDERS,
    TalkingHeadProvider,
    get_avatar_provider,
    register_avatar_provider,
)

# Import provider modules for their import-time side effect: each calls
# ``register_avatar_provider(...)`` to self-register into ``AVATAR_PROVIDERS``.
# Guarded so a missing optional dependency degrades to "provider unavailable"
# rather than breaking the whole package import (and py_compile).
try:
    from app.services.avatar import heygen as _heygen  # noqa: F401
except Exception as exc:  # noqa: BLE001 - optional provider; degrade gracefully
    logger.warning(f"heygen avatar provider unavailable: {exc}")

try:
    from app.services.avatar import latentsync_runpod as _latentsync_runpod  # noqa: F401
except Exception as exc:  # noqa: BLE001 - optional provider; degrade gracefully
    logger.warning(f"latentsync avatar provider unavailable: {exc}")

__all__ = [
    "AVATAR_PROVIDERS",
    "TalkingHeadProvider",
    "get_avatar_provider",
    "register_avatar_provider",
]
