"""Resolve a :class:`Publisher` for a platform (mirror of ``src/factory.ts``).

All clients are stateless; tokens are passed per call.
"""

from __future__ import annotations

from .instagram_client import InstagramPublisher
from .publisher import Publisher
from .tiktok_client import TikTokPublisher
from .x_client import XPublisher
from .youtube_client import YouTubePublisher


def create_publisher(platform: str) -> Publisher:
    p = str(platform or "").strip().lower()
    if p == "tiktok":
        return TikTokPublisher()
    if p == "instagram":
        return InstagramPublisher()
    if p == "youtube":
        return YouTubePublisher()
    if p == "x":
        return XPublisher()
    raise ValueError(f"unknown platform {platform!r}")
