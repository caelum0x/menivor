"""Speak domain: image + narration audio → talking video (async lipsync).

Import-safe surface (mirrors ``domains/broll/__init__.py``): it exposes the pure
selection + licensing entrypoints and a lipsync-provider resolver, but does NOT
import the HTTP router (FastAPI/DB) at package import — ``app/router.py`` mounts
the router via ``from app.domains.speak import router`` (the submodule), so the
package stays cheap to import from the worker/services layer.
"""

from app.domains.speak.licensing import (
    LicenseClass,
    LicenseClassError,
    is_commercial_ok,
    license_class_for,
    require_commercial_ok,
)
from app.domains.speak.selection import (
    NoLipsyncProviderError,
    choose_lipsync_provider,
)


def get_lipsync_provider(provider_key: str):
    """Resolve a lipsync :class:`ProviderAdapter` for ``provider_key``.

    Prefers an adapter already registered in the routing registry (credentials
    present at startup); falls back to a seeded lipsync adapter. Kept here so the
    package exposes one selection/resolution entrypoint (parallels
    ``broll.get_broll_provider``).
    """
    from app.domains.routing.base import registry

    adapter = registry.get(provider_key)
    if adapter is not None:
        return adapter
    from app.domains.routing.providers._lipsync import build_lipsync_adapter

    return build_lipsync_adapter(provider_key)


__all__ = [
    "LicenseClass",
    "LicenseClassError",
    "is_commercial_ok",
    "license_class_for",
    "require_commercial_ok",
    "NoLipsyncProviderError",
    "choose_lipsync_provider",
    "get_lipsync_provider",
]
