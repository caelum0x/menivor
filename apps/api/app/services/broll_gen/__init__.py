"""Compatibility import for the B-roll domain provider registry.

New product code imports :mod:`app.domains.broll`. This package remains until a
separately approved internal-import deprecation removes legacy consumers.
"""

from app.domains.broll import (
    BROLL_GEN_PROVIDERS,
    BrollGenProvider,
    get_broll_provider,
    register_broll_provider,
)

__all__ = [
    "BROLL_GEN_PROVIDERS",
    "BrollGenProvider",
    "get_broll_provider",
    "register_broll_provider",
]
