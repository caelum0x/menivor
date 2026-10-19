"""Per-platform OAuth endpoint / scope descriptors (mirror of ``src/oauth/config.ts``).

Client-safe metadata (no secrets): the web/mobile PKCE start and the API token
exchange both read the same endpoints + scopes. Feeds
``connectors/oauth_flows.py``.
"""

from __future__ import annotations

OAUTH: dict[str, dict] = {
    "tiktok": {
        "auth_url": "https://www.tiktok.com/v2/auth/authorize/",
        "token_url": "https://open.tiktokapis.com/v2/oauth/token/",
        "scopes": ["user.info.basic", "video.publish", "video.upload"],
        "pkce": True,
    },
    "instagram": {
        "auth_url": "https://www.facebook.com/v19.0/dialog/oauth",
        "token_url": "https://graph.facebook.com/v19.0/oauth/access_token",
        "scopes": ["instagram_basic", "instagram_content_publish", "pages_show_list"],
        "pkce": False,
    },
    "youtube": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
        "pkce": True,
    },
    "x": {
        "auth_url": "https://twitter.com/i/oauth2/authorize",
        "token_url": "https://api.twitter.com/2/oauth2/token",
        "scopes": ["tweet.read", "tweet.write", "users.read", "offline.access"],
        "pkce": True,
    },
}


def oauth_for(platform: str) -> dict | None:
    return OAUTH.get(str(platform or "").strip().lower())


def scope_string(platform: str) -> str:
    """Space-joined scope string for the authorize URL."""
    cfg = oauth_for(platform)
    return " ".join(cfg["scopes"]) if cfg else ""


def requires_pkce(platform: str) -> bool:
    cfg = oauth_for(platform)
    return bool(cfg and cfg["pkce"])
