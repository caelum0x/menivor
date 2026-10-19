"""Extended publish connectors (registered on import).

Kept in their own registry so the native TikTok / Instagram / YouTube
``/publishing/native`` surface is unchanged.
"""

from __future__ import annotations

from . import bluesky, facebook, linkedin, pinterest, threads, x  # noqa: F401 - registers connectors
from . import discord, mastodon, telegram  # noqa: F401 - credential channels (Wave L)
from . import instagram  # noqa: F401 - image-only (reels stay on the native connector)
from .base import ExtendedConnector, PublishContext, PublishError, Step, get, get_for_images, registered

__all__ = ["ExtendedConnector", "PublishContext", "PublishError", "Step", "get", "get_for_images", "registered"]
