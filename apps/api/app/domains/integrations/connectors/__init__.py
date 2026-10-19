"""Ad-account connector registry (Creatify order: Meta, Google, Apple, TikTok, Snapchat, Reddit, AppLovin, OpenAI)."""

from __future__ import annotations

from app.domains.integrations.connectors.apple_search_ads import AppleSearchAdsConnector
from app.domains.integrations.connectors.applovin import AppLovinConnector
from app.domains.integrations.connectors.base import Connector
from app.domains.integrations.connectors.google_ads import GoogleAdsConnector
from app.domains.integrations.connectors.meta import MetaConnector
from app.domains.integrations.connectors.openai_ads import OpenAIAdsConnector
from app.domains.integrations.connectors.reddit import RedditConnector
from app.domains.integrations.connectors.snapchat import SnapchatConnector
from app.domains.integrations.connectors.tiktok import TikTokConnector

_REGISTRY: dict[str, Connector] = {c.provider: c for c in (
    MetaConnector(), GoogleAdsConnector(), AppleSearchAdsConnector(), TikTokConnector(), SnapchatConnector(),
    RedditConnector(), AppLovinConnector(), OpenAIAdsConnector(),
)}
AD_PROVIDERS: tuple[str, ...] = tuple(_REGISTRY)


def get_connector(provider: str) -> Connector:
    """The connector for ``provider`` (``KeyError`` for an unknown one)."""
    return _REGISTRY[provider]


__all__ = ["AD_PROVIDERS", "get_connector"]
