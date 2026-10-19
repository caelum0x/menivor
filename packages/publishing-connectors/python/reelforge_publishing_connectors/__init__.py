"""ReelForge publishing-connectors (Python parity) — policy + Publisher clients.

Byte-identical to ``@reelforge/publishing-connectors`` (golden fixtures) so the
cap-aware composer (web/mobile) and the publish policy (api) agree. Exposes both
halves of the TS package:

* **policy** — caps + watermark cross-post rules + OAuth config (feeds
  ``publishing/policy.py`` + ``connectors/oauth_flows.py``); and
* **clients** — the four stateless :class:`Publisher` clients + ``http_json``
  transport + ``create_publisher`` factory, so a Python SDK consumer can publish,
  not merely read policy. Stateless: tokens are passed in per call, never
  persisted (the API decrypts Fernet tokens and injects them).
"""

from .caps import CAPS, PLATFORMS, caps_for, remaining_daily, validate_publish
from .factory import create_publisher
from .http import HttpError, HttpFn, HttpOptions, encode_uri_component, http_json
from .instagram_client import InstagramPublisher
from .oauth_config import OAUTH, oauth_for, requires_pkce, scope_string
from .publisher import (
    AnalyticsSnapshot,
    ConnectorError,
    Publisher,
    PublishRequest,
    PublishResult,
    TokenRefresh,
)
from .tiktok_client import TikTokPublisher
from .watermark_policy import check_watermark, is_watermark_allowed
from .x_client import X_POST_COST_MICROS, XPublisher
from .youtube_client import YouTubePublisher

__all__ = [
    # policy
    "PLATFORMS",
    "CAPS",
    "caps_for",
    "validate_publish",
    "remaining_daily",
    "OAUTH",
    "oauth_for",
    "scope_string",
    "requires_pkce",
    "is_watermark_allowed",
    "check_watermark",
    # contracts
    "PublishRequest",
    "PublishResult",
    "TokenRefresh",
    "ConnectorError",
    "AnalyticsSnapshot",
    "Publisher",
    # transport
    "http_json",
    "HttpOptions",
    "HttpError",
    "HttpFn",
    "encode_uri_component",
    # clients + factory
    "TikTokPublisher",
    "InstagramPublisher",
    "YouTubePublisher",
    "XPublisher",
    "X_POST_COST_MICROS",
    "create_publisher",
]
