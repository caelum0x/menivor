"""Env gate for paid ads: which platforms are enabled and their tunables.

A platform is enabled only when BOTH its app id and app secret are set; these
are the credentials of Menivor's own Meta / TikTok business app and only work
for other advertisers once the app passed platform review. Nothing here is a
per-user secret.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

PLATFORMS: tuple[str, ...] = ("meta", "tiktok")

NOT_ENABLED_REASON = "Ads not enabled — requires Meta/TikTok app approval"

# Default Graph API version; override with MENIVOR_META_API_VERSION.
DEFAULT_META_API_VERSION = "v21.0"
DEFAULT_WEB_URL = "https://menivor.com"

# Platform minimum daily budgets in account-currency minor units (USD cents by
# default). Meta's floor for an impressions-billed ad set is about 1 USD/day;
# TikTok's documented ad-group daily minimum is 20 USD. Both vary by currency,
# so they are env-overridable rather than hard truths.
_DEFAULT_MIN_DAILY_MINOR = {"meta": 100, "tiktok": 2000}
_LABELS = {"meta": "Meta (Facebook + Instagram)", "tiktok": "TikTok"}


@dataclass(frozen=True)
class PlatformConfig:
    platform: str
    app_id: str
    app_secret: str
    min_daily_budget_minor: int
    redirect_uri: str

    @property
    def enabled(self) -> bool:
        return bool(self.app_id and self.app_secret)


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _int_env(name: str, default: int) -> int:
    raw = _env(name)
    try:
        value = int(raw) if raw else default
    except ValueError:
        return default
    return value if value > 0 else default


def web_url() -> str:
    return (_env("MENIVOR_WEB_URL") or DEFAULT_WEB_URL).rstrip("/")


def meta_api_version() -> str:
    version = _env("MENIVOR_META_API_VERSION") or DEFAULT_META_API_VERSION
    return version if version.startswith("v") else f"v{version}"


def platform_config(platform: str) -> PlatformConfig:
    if platform not in PLATFORMS:
        raise ValueError(f"unknown ads platform: {platform}")
    upper = platform.upper()
    redirect = _env(f"MENIVOR_{upper}_ADS_REDIRECT_URI") or f"{web_url()}/ads/connect/{platform}"
    return PlatformConfig(
        platform=platform,
        app_id=_env(f"MENIVOR_{upper}_APP_ID"),
        app_secret=_env(f"MENIVOR_{upper}_APP_SECRET"),
        min_daily_budget_minor=_int_env(
            f"MENIVOR_{upper}_MIN_DAILY_BUDGET_MINOR", _DEFAULT_MIN_DAILY_MINOR[platform]
        ),
        redirect_uri=redirect,
    )


def any_enabled() -> bool:
    return any(platform_config(p).enabled for p in PLATFORMS)


def status() -> dict:
    """Public, non-secret gate document for the web surface."""
    platforms = []
    for name in PLATFORMS:
        cfg = platform_config(name)
        platforms.append({
            "platform": name,
            "label": _LABELS[name],
            "enabled": cfg.enabled,
            "min_daily_budget_minor": cfg.min_daily_budget_minor,
            "reason": "" if cfg.enabled else NOT_ENABLED_REASON,
        })
    enabled = any(p["enabled"] for p in platforms)
    return {
        "enabled": enabled,
        "reason": "" if enabled else NOT_ENABLED_REASON,
        "platforms": platforms,
        # Menivor never marks up or bills ad spend: spend is charged by the
        # platform to the advertiser's own ad account.
        "menivor_fee": 0,
    }
