"""The extended publish platforms: what each needs, allows and requires.

Six platforms with official posting APIs, on top of the native TikTok /
Instagram / YouTube connectors:

* **Facebook Pages** - Graph API ``/{page-id}/videos`` (``file_url`` ingest).
  ``pages_manage_posts`` needs Meta app review before accounts outside the
  developer app can connect.
* **LinkedIn** - Posts API + Videos API. Posting as yourself (``w_member_social``)
  is self-serve ("Share on LinkedIn"); posting as a company page needs the
  Community Management API, which LinkedIn approves per app.
* **X** - API v2 (``/2/media/upload`` + ``/2/tweets``). X charges for API
  access, so posting is off until the operator declares a paid plan.
* **Threads** - Threads API (``/{user-id}/threads`` + ``threads_publish``).
  Meta app review for accounts outside the app.
* **Pinterest** - API v5 (``/v5/media`` + ``/v5/pins``). New Pinterest apps
  start on Trial access, where created Pins are visible only to the app owner
  until Pinterest grants Standard access.
* **Bluesky** - AT Protocol. Free and open; connects with the handle plus an app
  password (no developer app, no review).

Everything here is static data plus config reads; nothing touches the network.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from app.config import config

FACEBOOK = "facebook"
LINKEDIN = "linkedin"
X = "x"
THREADS = "threads"
PINTEREST = "pinterest"
BLUESKY = "bluesky"

EXTENDED_PLATFORMS: tuple[str, ...] = (FACEBOOK, LINKEDIN, X, THREADS, PINTEREST, BLUESKY)

AUTH_OAUTH2 = "oauth2"
AUTH_APP_PASSWORD = "app_password"

# Where a connected account posts to (the "target").
TARGET_SELF = "self"             # the connected user (X, Threads, Bluesky, LinkedIn member)
TARGET_PAGE = "page"             # a Facebook Page the user manages
TARGET_ORGANIZATION = "organization"  # a LinkedIn company page the user administers
TARGET_BOARD = "board"           # a Pinterest board


@dataclass(frozen=True)
class FormatRules:
    """Per-platform post constraints enforced before anything is sent."""

    caption_max: int
    title_max: int = 0             # 0 = the platform has no separate title
    hashtags_max: int = 30
    video_min_seconds: float = 0.0
    video_max_seconds: float = 0.0  # 0 = not limited by us
    max_bytes: int = 0             # 0 = not limited by us
    aspect_note: str = ""
    counts_graphemes: bool = False  # Bluesky counts graphemes, not characters

    def to_record(self) -> dict:
        return {
            "caption_max": self.caption_max,
            "title_max": self.title_max,
            "hashtags_max": self.hashtags_max,
            "video_min_seconds": self.video_min_seconds,
            "video_max_seconds": self.video_max_seconds,
            "max_bytes": self.max_bytes,
            "aspect_note": self.aspect_note,
        }


@dataclass(frozen=True)
class PlatformSpec:
    key: str
    label: str
    auth: str
    rules: FormatRules
    target_kind: str = TARGET_SELF
    authorize_url: str = ""
    token_url: str = ""
    scopes: str = ""
    organization_scopes: str = ""  # LinkedIn company-page scopes (needs approval)
    scope_separator: str = " "
    pkce: bool = False
    review_note: str = ""          # platform approval the operator must obtain
    cost_note: str = ""            # platform-side cost, stated plainly
    docs_url: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def uses_oauth(self) -> bool:
        return self.auth == AUTH_OAUTH2


_MB = 1024 * 1024

SPECS: dict[str, PlatformSpec] = {
    FACEBOOK: PlatformSpec(
        key=FACEBOOK,
        label="Facebook Page",
        auth=AUTH_OAUTH2,
        target_kind=TARGET_PAGE,
        authorize_url="https://www.facebook.com/v21.0/dialog/oauth",
        token_url="https://graph.facebook.com/v21.0/oauth/access_token",
        scopes=(
            "pages_show_list,pages_read_engagement,pages_manage_posts,"
            "pages_manage_engagement,pages_read_user_content,read_insights"
        ),
        scope_separator=",",
        rules=FormatRules(
            caption_max=5000, title_max=255, hashtags_max=30,
            video_min_seconds=1, video_max_seconds=4 * 60 * 60, max_bytes=4 * 1024 * _MB,
            aspect_note="Vertical 9:16 plays full screen; any ratio is accepted.",
        ),
        review_note=(
            "Meta must approve the pages_manage_posts permission (App Review) before "
            "Pages outside the Menivor developer app can be connected."
        ),
        docs_url="https://developers.facebook.com/docs/video-api/guides/publishing",
    ),
    LINKEDIN: PlatformSpec(
        key=LINKEDIN,
        label="LinkedIn",
        auth=AUTH_OAUTH2,
        target_kind=TARGET_SELF,
        authorize_url="https://www.linkedin.com/oauth/v2/authorization",
        token_url="https://www.linkedin.com/oauth/v2/accessToken",
        scopes="openid profile w_member_social",
        organization_scopes="openid profile w_member_social w_organization_social r_organization_social rw_organization_admin",
        rules=FormatRules(
            caption_max=3000, title_max=200, hashtags_max=30,
            video_min_seconds=3, video_max_seconds=30 * 60, max_bytes=500 * _MB,
            aspect_note="1:2.4 to 2.4:1; vertical 9:16 is shown cropped in some feeds.",
        ),
        review_note=(
            "Posting as yourself works once the app has the Share on LinkedIn product. "
            "Posting as a company page needs LinkedIn's Community Management API approval."
        ),
        docs_url="https://learn.microsoft.com/linkedin/marketing/community-management/shares/posts-api",
    ),
    X: PlatformSpec(
        key=X,
        label="X",
        auth=AUTH_OAUTH2,
        target_kind=TARGET_SELF,
        authorize_url="https://x.com/i/oauth2/authorize",
        token_url="https://api.x.com/2/oauth2/token",
        scopes="tweet.read tweet.write users.read media.write offline.access",
        pkce=True,
        rules=FormatRules(
            caption_max=280, hashtags_max=5,
            video_min_seconds=0.5, video_max_seconds=140, max_bytes=512 * _MB,
            aspect_note="1:3 to 3:1; 9:16 vertical is supported.",
        ),
        cost_note=(
            "X charges for API access. Posting from Menivor stays off until the operator "
            "turns on a paid X API plan for the Menivor app."
        ),
        docs_url="https://docs.x.com/x-api/posts/create-post",
    ),
    THREADS: PlatformSpec(
        key=THREADS,
        label="Threads",
        auth=AUTH_OAUTH2,
        target_kind=TARGET_SELF,
        authorize_url="https://threads.net/oauth/authorize",
        token_url="https://graph.threads.net/oauth/access_token",
        scopes=(
            "threads_basic,threads_content_publish,threads_read_replies,threads_manage_replies,"
            "threads_manage_insights"
        ),
        scope_separator=",",
        rules=FormatRules(
            caption_max=500, hashtags_max=1,
            video_min_seconds=0, video_max_seconds=5 * 60, max_bytes=1024 * _MB,
            aspect_note="Up to 9:16 vertical.",
        ),
        review_note=(
            "Meta must approve threads_content_publish (App Review) before accounts outside "
            "the Menivor developer app can connect."
        ),
        docs_url="https://developers.facebook.com/docs/threads/posts",
    ),
    PINTEREST: PlatformSpec(
        key=PINTEREST,
        label="Pinterest",
        auth=AUTH_OAUTH2,
        target_kind=TARGET_BOARD,
        authorize_url="https://www.pinterest.com/oauth/",
        token_url="https://api.pinterest.com/v5/oauth/token",
        scopes="boards:read,pins:read,pins:write,user_accounts:read",
        scope_separator=",",
        rules=FormatRules(
            caption_max=500, title_max=100, hashtags_max=20,
            video_min_seconds=4, video_max_seconds=15 * 60, max_bytes=2 * 1024 * _MB,
            aspect_note="9:16 or 2:3 vertical is recommended.",
        ),
        review_note=(
            "Pinterest apps start on Trial access: Pins you create are visible only to you "
            "until Pinterest grants Standard access."
        ),
        docs_url="https://developers.pinterest.com/docs/api/v5/pins-create",
    ),
    BLUESKY: PlatformSpec(
        key=BLUESKY,
        label="Bluesky",
        auth=AUTH_APP_PASSWORD,
        target_kind=TARGET_SELF,
        rules=FormatRules(
            caption_max=300, hashtags_max=8,
            video_min_seconds=0, video_max_seconds=3 * 60, max_bytes=100 * _MB,
            aspect_note="Any ratio; 9:16 vertical is supported.",
            counts_graphemes=True,
        ),
        docs_url="https://docs.bsky.app/docs/advanced-guides/posts",
    ),
}

# Platforms whose publish needs the MP4 bytes locally (vs. a public URL ingest).
BYTE_UPLOAD: frozenset[str] = frozenset({LINKEDIN, X, PINTEREST, BLUESKY})
URL_INGEST: frozenset[str] = frozenset({FACEBOOK, THREADS})

# X plan values that allow posting. Anything else (unset, "free", "none") keeps X off.
_X_PAID_PLANS = frozenset({"basic", "pro", "enterprise", "pay_per_use", "paid"})


def spec_for(platform: str) -> PlatformSpec | None:
    key = str(platform or "").strip().lower()
    return SPECS.get(key) or CHANNEL_SPECS.get(key)


def is_extended(platform: str) -> bool:
    return str(platform or "").strip().lower() in SPECS


def _setting(name: str) -> str:
    """Env ``NAME`` wins over ``config.app['name']`` (``""`` when unset)."""
    env = os.getenv(name.upper(), "").strip()
    if env:
        return env
    try:
        return str(config.app.get(name.lower(), "") or "").strip()
    except Exception:  # pragma: no cover - config is always bound in practice
        return ""


def client_id(platform: str) -> str:
    return _setting(f"{platform}_client_id")


def client_secret(platform: str) -> str:
    return _setting(f"{platform}_client_secret")


def redirect_uri(platform: str) -> str:
    """Where the provider sends the browser back (the web Connections page).

    ``<PLATFORM>_REDIRECT_URI`` wins; else ``publishing_oauth_redirect_url``
    (one URL shared by every extended platform - the state row says which
    platform it was); else ``web_base_url`` + ``/connections``.
    """
    explicit = _setting(f"{platform}_redirect_uri")
    if explicit:
        return explicit
    shared = _setting("publishing_oauth_redirect_url")
    if shared:
        return shared
    web = _setting("web_base_url")
    return f"{web.rstrip('/')}/connections" if web else ""


def x_api_plan() -> str:
    return _setting("x_api_plan").lower()


def x_posting_enabled() -> bool:
    return x_api_plan() in _X_PAID_PLANS


def x_monthly_post_cap() -> int:
    """Operator guard on X spend: posts per calendar month across all creators (0 = no cap)."""
    raw = _setting("x_monthly_post_cap")
    try:
        return max(0, int(raw)) if raw else 0
    except ValueError:
        return 0


def pinterest_api_base() -> str:
    """Pinterest production vs. sandbox host (Trial apps may only write to sandbox)."""
    return _setting("pinterest_api_base") or "https://api.pinterest.com"


# Server availability states (before any creator connects).
AVAILABLE = "available"
NOT_CONFIGURED = "not_configured"   # the operator has not set up the developer app
PLAN_REQUIRED = "plan_required"     # X: no paid API plan declared


def server_availability(platform: str) -> tuple[str, str]:
    """``(state, note)`` describing whether this server can connect ``platform`` at all."""
    spec = spec_for(platform)
    if spec is None:
        return NOT_CONFIGURED, "Unknown platform."
    if spec.key == X and not x_posting_enabled():
        return PLAN_REQUIRED, spec.cost_note
    if spec.uses_oauth:
        missing = not client_id(spec.key) or not client_secret(spec.key) or not redirect_uri(spec.key)
        if missing:
            return NOT_CONFIGURED, (
                f"{spec.label} is not set up on this server yet. The operator needs to register a "
                f"{spec.label} developer app and add its client id, secret and redirect URL."
            )
    return AVAILABLE, ""


# --------------------------------------------------------------------------- #
# Credential channels: Telegram, Discord, Mastodon
# --------------------------------------------------------------------------- #
# Free APIs with no platform review. They are NOT in ``SPECS`` /
# ``EXTENDED_PLATFORMS`` because they do not use the OAuth connection table:
# the creator pastes a credential and it is stored per channel in
# ``social_channel_credentials`` (see :mod:`.channel_models` / :mod:`.channels`).
# ``spec_for`` still resolves them so format fitting and post records work.
TELEGRAM = "telegram"
DISCORD = "discord"
MASTODON = "mastodon"
CHANNEL_PLATFORMS: tuple[str, ...] = (TELEGRAM, DISCORD, MASTODON)

AUTH_BOT_TOKEN = "bot_token"
AUTH_WEBHOOK = "webhook"
AUTH_ACCESS_TOKEN = "access_token"
TARGET_CHANNEL = "channel"

CHANNEL_SPECS: dict[str, PlatformSpec] = {
    TELEGRAM: PlatformSpec(
        key=TELEGRAM,
        label="Telegram",
        auth=AUTH_BOT_TOKEN,
        target_kind=TARGET_CHANNEL,
        rules=FormatRules(
            # 1024 is the Bot API limit for a media caption (plain messages allow 4096).
            caption_max=1024, hashtags_max=30,
            video_min_seconds=0, video_max_seconds=0, max_bytes=50 * _MB,
            aspect_note="Any ratio. Bots can upload videos up to 50 MB.",
        ),
        docs_url="https://core.telegram.org/bots/api#sendvideo",
    ),
    DISCORD: PlatformSpec(
        key=DISCORD,
        label="Discord",
        auth=AUTH_WEBHOOK,
        target_kind=TARGET_CHANNEL,
        rules=FormatRules(
            caption_max=2000, hashtags_max=30,
            video_min_seconds=0, video_max_seconds=0, max_bytes=10 * _MB,
            aspect_note="Any ratio. Servers without boosts accept uploads up to 10 MB.",
        ),
        docs_url="https://discord.com/developers/docs/resources/webhook#execute-webhook",
    ),
    MASTODON: PlatformSpec(
        key=MASTODON,
        label="Mastodon",
        auth=AUTH_ACCESS_TOKEN,
        target_kind=TARGET_SELF,
        rules=FormatRules(
            # 500 is the Mastodon default; some instances allow more.
            caption_max=500, hashtags_max=10,
            video_min_seconds=0, video_max_seconds=0, max_bytes=99 * _MB,
            aspect_note="Any ratio. Default instance limit is 99 MB per video.",
        ),
        docs_url="https://docs.joinmastodon.org/methods/statuses/#create",
    ),
}

# Channel posts upload the MP4 bytes themselves (no public-URL ingest).
BYTE_UPLOAD = BYTE_UPLOAD | frozenset(CHANNEL_PLATFORMS)


def is_channel(platform: str) -> bool:
    return str(platform or "").strip().lower() in CHANNEL_SPECS
