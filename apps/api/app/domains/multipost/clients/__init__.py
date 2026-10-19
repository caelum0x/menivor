"""Platform clients for multi-account publishing (TikTok, Instagram, YouTube)."""

from . import instagram, tiktok, youtube
from .base import AuthError, ClientError, PostSpec, PublishOutcome, RateLimited, RequestsTransport, Transport

__all__ = [
    "AuthError",
    "ClientError",
    "PostSpec",
    "PublishOutcome",
    "RateLimited",
    "RequestsTransport",
    "Transport",
    "instagram",
    "tiktok",
    "youtube",
]
