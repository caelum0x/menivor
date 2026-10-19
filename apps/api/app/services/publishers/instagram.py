"""Thin Instagram (Reels) publisher (Direct-Publish).

Like :class:`~app.services.publishers.tiktok.TikTokPublisher`, this is a one-line
per-provider subclass of :class:`~app.services.publishers.base.BasePublisher`.
The provider-specific request shaping and the live HTTP upload (Instagram Graph
API container → publish) live behind the injected
:class:`~app.services.publishers.base.VideoUploadClient` — in production the
:class:`~app.services.publishers.http_client.NativeUploadClient`.
"""

from __future__ import annotations

from typing import Any

from app.services.provenance import ai_flag_extra
from app.services.publishers.base import BasePublisher, PublishResult


class InstagramPublisher(BasePublisher):
    """Publish a rendered reel to Instagram via the injected upload client."""

    provider = "instagram"

    def publish(self, **kwargs: Any) -> PublishResult:
        """Publish with the AI-generated disclosure on (MN5).

        the Instagram Graph API has no AI-label field, so the disclosure rides the provenance metadata in the file.
        """
        return super().publish(**{**kwargs, "extra": ai_flag_extra(kwargs.get("extra"))})


__all__ = ["InstagramPublisher"]
