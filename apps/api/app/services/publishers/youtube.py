"""Thin YouTube (Shorts) publisher (Direct-Publish).

Like :class:`~app.services.publishers.tiktok.TikTokPublisher`, this is a one-line
per-provider subclass of :class:`~app.services.publishers.base.BasePublisher`.
The provider-specific request shaping and the live HTTP upload (YouTube Data API
v3 resumable upload) live behind the injected
:class:`~app.services.publishers.base.VideoUploadClient` — in production the
:class:`~app.services.publishers.http_client.NativeUploadClient`.
"""

from __future__ import annotations

from typing import Any

from app.services.provenance import ai_flag_extra
from app.services.publishers.base import BasePublisher, PublishResult


class YouTubePublisher(BasePublisher):
    """Publish a rendered reel to YouTube via the injected upload client."""

    provider = "youtube"

    def publish(self, **kwargs: Any) -> PublishResult:
        """Publish with the AI-generated disclosure on (MN5).

        YouTube sets ``status.containsSyntheticMedia``.
        """
        return super().publish(**{**kwargs, "extra": ai_flag_extra(kwargs.get("extra"))})


__all__ = ["YouTubePublisher"]
