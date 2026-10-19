"""Thin TikTok publisher stub (Direct-Publish).

The concrete per-provider example of the :class:`~app.services.publishers.base.BasePublisher`
seam. It is intentionally tiny: the only provider-specific piece is the
``provider`` token — request shaping and the live HTTP upload live behind the
injected :class:`~app.services.publishers.base.VideoUploadClient`, which is mocked
in tests and wired to real TikTok credentials later. Instagram and YouTube
publishers follow the same one-line pattern.
"""

from __future__ import annotations

from typing import Any

from app.services.provenance import ai_flag_extra
from app.services.publishers.base import BasePublisher, PublishResult


class TikTokPublisher(BasePublisher):
    """Publish a rendered reel to TikTok via the injected upload client."""

    provider = "tiktok"

    def publish(self, **kwargs: Any) -> PublishResult:
        """Publish with the AI-generated disclosure on (MN5).

        TikTok sets ``post_info.is_aigc``.
        """
        return super().publish(**{**kwargs, "extra": ai_flag_extra(kwargs.get("extra"))})


__all__ = ["TikTokPublisher"]
