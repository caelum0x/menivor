"""Provider registry for ReelForge's trend-ingestion (pull) domain.

Mirrors ``app/domains/broll/providers/__init__.py``: exposes the registry entry
points and defensively imports each concrete backend so a missing optional
dependency (Playwright absent) degrades one provider without breaking the rest.
Does NOT touch the existing trends scoring/repository/router.
"""

from loguru import logger

from app.domains.trends.providers.base import (
    TREND_PULL_PROVIDERS,
    TrendPullProvider,
    get_trend_pull_provider,
    register_trend_pull_provider,
)

try:
    from app.domains.trends.providers import tiktok_pull as _tiktok_pull  # noqa: F401
except Exception as exc:  # noqa: BLE001
    logger.warning(f"tiktok trend_pull provider unavailable: {exc}")

__all__ = [
    "TREND_PULL_PROVIDERS",
    "TrendPullProvider",
    "get_trend_pull_provider",
    "register_trend_pull_provider",
]
