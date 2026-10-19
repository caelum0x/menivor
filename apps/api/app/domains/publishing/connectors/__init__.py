"""Native platform-publish connectors (registered on import).

Importing this package registers the YouTube / TikTok / Instagram connectors into
the ``base`` registry so ``get_connector(platform)`` resolves them.
"""

from __future__ import annotations

from . import instagram, tiktok, youtube  # noqa: F401 - import side effect registers connectors
from .base import (
    PublishConnector,
    PublishError,
    PublishRequest,
    PublishResult,
    RequestsTransport,
    Transport,
    available_platforms,
    get_connector,
    register_connector,
)

__all__ = [
    "PublishConnector",
    "PublishError",
    "PublishRequest",
    "PublishResult",
    "RequestsTransport",
    "Transport",
    "available_platforms",
    "get_connector",
    "register_connector",
]
