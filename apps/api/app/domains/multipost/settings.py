"""Server configuration and per-platform posting policy for multi-account publishing.

Everything is read from env first, then ``config.app`` (lower-cased name). No
value is ever hardcoded; a missing developer app shows up as an honest
"connect your developer app" state listing the env names to set.

Credentials per provider ``P`` in {TIKTOK, INSTAGRAM, YOUTUBE}:
``MULTIPOST_P_CLIENT_ID`` / ``MULTIPOST_P_CLIENT_SECRET`` (falls back to the
existing ``P_CLIENT_ID`` / ``P_CLIENT_SECRET`` used by single-account connect).

Redirect: ``MULTIPOST_OAUTH_REDIRECT_URL`` (one URL for all three - the state
row says which provider it was), else ``WEB_BASE_URL`` + ``/autopost/callback``.

Platform review switches (owner flips them after each platform approves the app):
``MULTIPOST_TIKTOK_AUDITED`` - until true, TikTok only allows private (SELF_ONLY)
posts, so every TikTok post is forced private and the UI says why.
``MULTIPOST_YOUTUBE_VERIFIED`` - until true, Google locks API uploads of an
unverified app to private, so YouTube posts are forced private.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .models import INSTAGRAM, PROVIDERS, TIKTOK, YOUTUBE


def setting(name: str) -> str:
    """Env ``NAME`` wins over ``config.app['name']`` (``""`` when unset)."""
    env = os.getenv(name.upper(), "").strip()
    if env:
        return env
    try:
        from app.config import config

        return str(config.app.get(name.lower(), "") or "").strip()
    except Exception:  # pragma: no cover - config is always bound in practice
        return ""


def flag(name: str) -> bool:
    return setting(name).lower() in {"1", "true", "yes", "on"}


def int_setting(name: str, default: int) -> int:
    raw = setting(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def client_id(provider: str) -> str:
    p = provider.upper()
    return setting(f"MULTIPOST_{p}_CLIENT_ID") or setting(f"{p}_CLIENT_ID")


def client_secret(provider: str) -> str:
    p = provider.upper()
    return setting(f"MULTIPOST_{p}_CLIENT_SECRET") or setting(f"{p}_CLIENT_SECRET")


def redirect_uri() -> str:
    explicit = setting("MULTIPOST_OAUTH_REDIRECT_URL")
    if explicit:
        return explicit
    web = setting("WEB_BASE_URL")
    return f"{web.rstrip('/')}/autopost/callback" if web else ""


def missing_settings(provider: str) -> list[str]:
    """Env names an operator still has to set before ``provider`` can connect."""
    p = provider.upper()
    missing: list[str] = []
    if not client_id(provider):
        missing.append(f"MULTIPOST_{p}_CLIENT_ID")
    if not client_secret(provider):
        missing.append(f"MULTIPOST_{p}_CLIENT_SECRET")
    if not redirect_uri():
        missing.append("MULTIPOST_OAUTH_REDIRECT_URL")
    if not setting("SOCIAL_TOKEN_KEY"):
        missing.append("SOCIAL_TOKEN_KEY")
    return missing


def tiktok_audited() -> bool:
    return flag("MULTIPOST_TIKTOK_AUDITED")


def youtube_verified() -> bool:
    return flag("MULTIPOST_YOUTUBE_VERIFIED")


def tiktok_source() -> str:
    """``file`` (default, bytes upload - no domain verification) or ``url`` (PULL_FROM_URL)."""
    return "url" if setting("MULTIPOST_TIKTOK_SOURCE").lower() in {"url", "pull", "pull_from_url"} else "file"


@dataclass(frozen=True)
class PostingPolicy:
    """Platform pacing limits.

    ``platform_daily_cap``: the hard per-account cap in any rolling 24 hours
    (TikTok ~15 direct posts per creator per day across all apps; Instagram's API
    publishing limit, also read live from ``content_publishing_limit``; YouTube
    has no per-channel cap but a per-project upload quota, below).
    ``default_daily_cap`` / ``default_gap_minutes``: what a new account uses.
    ``min_gap_floor_minutes``: the smallest gap an owner may configure.
    """

    provider: str
    platform_daily_cap: int
    default_daily_cap: int
    default_gap_minutes: int
    min_gap_floor_minutes: int
    label: str


def policy(provider: str) -> PostingPolicy:
    if provider == TIKTOK:
        cap = int_setting("MULTIPOST_TIKTOK_DAILY_CAP", 15)
        return PostingPolicy(TIKTOK, cap, min(cap, int_setting("MULTIPOST_TIKTOK_DEFAULT_CAP", 4)),
                             int_setting("MULTIPOST_TIKTOK_DEFAULT_GAP_MIN", 120), 15, "TikTok")
    if provider == INSTAGRAM:
        cap = int_setting("MULTIPOST_INSTAGRAM_DAILY_CAP", 50)
        return PostingPolicy(INSTAGRAM, cap, min(cap, int_setting("MULTIPOST_INSTAGRAM_DEFAULT_CAP", 4)),
                             int_setting("MULTIPOST_INSTAGRAM_DEFAULT_GAP_MIN", 120), 15, "Instagram")
    if provider == YOUTUBE:
        cap = int_setting("MULTIPOST_YOUTUBE_DAILY_CAP", 20)
        return PostingPolicy(YOUTUBE, cap, min(cap, int_setting("MULTIPOST_YOUTUBE_DEFAULT_CAP", 3)),
                             int_setting("MULTIPOST_YOUTUBE_DEFAULT_GAP_MIN", 180), 30, "YouTube")
    raise ValueError(f"unknown provider {provider!r}")


def youtube_project_daily_uploads() -> int:
    """Uploads per rolling 24 h the Google Cloud project may make (all channels).

    Quota belongs to the project, not the channel. The default (6) fits the
    classic 10,000-unit pool at 1,600 units per ``videos.insert``; raise it with
    ``MULTIPOST_YOUTUBE_PROJECT_DAILY_UPLOADS`` once Google grants more.
    """
    return max(1, int_setting("MULTIPOST_YOUTUBE_PROJECT_DAILY_UPLOADS", 6))


def instagram_caption_disclosure() -> str:
    """Caption line added to Instagram posts (the Graph API has no AI-label field)."""
    return setting("MULTIPOST_INSTAGRAM_AI_DISCLOSURE") or "Made with AI."


def provider_overview(provider: str) -> dict:
    """Public, secret-free description of a provider's server state and limits."""
    pol = policy(provider)
    missing = missing_settings(provider)
    notes: list[str] = []
    if provider == TIKTOK and not tiktok_audited():
        notes.append("TikTok has not approved this app yet, so posts go out as private (only you can see "
                     "them) and at most 5 accounts can post per day.")
    if provider == YOUTUBE and not youtube_verified():
        notes.append("Google has not verified this app yet, so uploads stay private until it does.")
    if provider == INSTAGRAM:
        notes.append("Works with Instagram professional (business or creator) accounts.")
    return {
        "provider": provider,
        "label": pol.label,
        "ready": not missing,
        "missing_settings": missing,
        "daily_cap_max": pol.platform_daily_cap,
        "default_daily_cap": pol.default_daily_cap,
        "default_gap_minutes": pol.default_gap_minutes,
        "min_gap_floor_minutes": pol.min_gap_floor_minutes,
        "notes": notes,
    }


def all_providers() -> tuple[str, ...]:
    return PROVIDERS
