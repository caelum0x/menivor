"""What each platform lets a connected app do with comments and DMs.

This is the single place that decides, per connected account, whether Menivor
can **read** and **reply to** comments and direct messages, and what the
creator must do when it cannot. Three honest outcomes exist for every action:

* ``yes``              - the platform offers it and the account's grant covers it
                         (or the grant is unknown, in which case the call is tried
                         and a permission error downgrades the post).
* ``needs_permission`` - the platform offers it, but this connection was made
                         without the required scope. Reconnect with
                         :func:`reconnect_scopes`.
* ``not_offered``      - the platform's public API does not offer it to apps
                         like ours at all. The inbox shows the post with an
                         "open in app" link instead of pretending.

Platform facts encoded here (as of the v21 Graph API / YouTube Data API v3 /
TikTok Content Posting + Display APIs):

* **YouTube** - ``commentThreads.list`` reads comments (``youtube.readonly`` or
  ``youtube.force-ssl``); ``comments.insert`` replies (``youtube.force-ssl``,
  50 quota units per reply). YouTube has no direct messages.
* **Instagram** - ``/{media-id}/comments`` + ``/{comment-id}/replies``
  (``instagram_business_manage_comments``); conversations + messages
  (``instagram_business_manage_messages``, replies only inside the 24-hour
  messaging window). Both require Meta app review for accounts outside the app.
* **TikTok** - the public APIs available to this app expose a post's comment
  *count* (Display API ``video.list``) but no endpoint to list or reply to
  comments, and no DM API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import config

YES = "yes"
NEEDS_PERMISSION = "needs_permission"
NOT_OFFERED = "not_offered"

PLATFORMS: tuple[str, ...] = (
    "youtube", "instagram", "tiktok", "facebook", "threads", "bluesky", "linkedin", "x", "pinterest",
    "telegram", "discord", "mastodon",
)

PLATFORM_LABELS: dict[str, str] = {
    "youtube": "YouTube",
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "facebook": "Facebook",
    "threads": "Threads",
    "bluesky": "Bluesky",
    "linkedin": "LinkedIn",
    "x": "X",
    "pinterest": "Pinterest",
    "telegram": "Telegram",
    "discord": "Discord",
    "mastodon": "Mastodon",
}

# Credential channels (``social_channel_credentials``), read through their own
# clients via :mod:`.channel_inbox`.
CHANNEL_INBOX_PLATFORMS: frozenset[str] = frozenset({"telegram", "discord", "mastodon"})

# Platforms whose connection lives in the extended publishing domain
# (``publishing_platform_connections``) rather than ``social_accounts``.
EXTENDED_INBOX_PLATFORMS: frozenset[str] = frozenset({"facebook", "threads", "bluesky"})
EXTENDED_PLATFORMS: frozenset[str] = EXTENDED_INBOX_PLATFORMS | {"linkedin", "x", "pinterest"}

# Scope tokens (the last path segment for Google URL scopes) that grant each action.
_YT_READ = frozenset({"youtube", "youtube.force-ssl", "youtube.readonly"})
_YT_WRITE = frozenset({"youtube", "youtube.force-ssl"})
_IG_COMMENTS = frozenset({"instagram_manage_comments", "instagram_business_manage_comments"})
_IG_MESSAGES = frozenset({"instagram_manage_messages", "instagram_business_manage_messages"})
_FB_READ = frozenset({"pages_read_user_content", "pages_read_engagement"})
_FB_WRITE = frozenset({"pages_manage_engagement"})
_TH_READ = frozenset({"threads_read_replies"})
_TH_WRITE = frozenset({"threads_manage_replies"})

_DEFAULT_RECONNECT_SCOPES: dict[str, str] = {
    "youtube": (
        "https://www.googleapis.com/auth/youtube.upload "
        "https://www.googleapis.com/auth/youtube.force-ssl"
    ),
    "instagram": (
        "instagram_business_basic,instagram_business_content_publish,"
        "instagram_business_manage_comments,instagram_business_manage_messages"
    ),
}

_NOT_OFFERED_NOTES: dict[tuple[str, str], str] = {
    ("tiktok", "comments"): (
        "TikTok does not let apps read or reply to comments. Open the post in TikTok to reply."
    ),
    ("tiktok", "dms"): "TikTok does not let apps read or send direct messages.",
    ("youtube", "dms"): "YouTube has no direct messages.",
    ("facebook", "dms"): "Facebook Page messages go through Messenger, which Menivor does not connect yet.",
    ("threads", "dms"): "Threads has no direct messages API.",
    ("bluesky", "dms"): "Menivor does not read Bluesky direct messages.",
    ("linkedin", "comments"): (
        "Reading LinkedIn comments needs LinkedIn's Community Management API approval, which Menivor "
        "does not have yet. Open the post in LinkedIn to reply."
    ),
    ("linkedin", "dms"): "LinkedIn does not offer messaging to apps like Menivor.",
    ("x", "comments"): "Reading replies on X is not included yet. Open the post on X to reply.",
    ("x", "dms"): "Menivor does not read X direct messages.",
    ("pinterest", "comments"): "Pinterest has no API for Pin comments. Open the Pin to reply.",
    ("pinterest", "dms"): "Pinterest has no messaging API.",
    ("discord", "dms"): "Menivor reads replies in your Discord channel, not direct messages.",
}


@dataclass(frozen=True)
class Access:
    """Read + reply availability for one kind of conversation (comments or DMs)."""

    read: str
    reply: str
    note: str = ""

    def to_record(self) -> dict:
        return {"read": self.read, "reply": self.reply, "note": self.note}


@dataclass(frozen=True)
class PlatformCapabilities:
    platform: str
    connected: bool
    comments: Access
    dms: Access
    reconnect_scopes: str = ""

    @property
    def needs_reconnect(self) -> bool:
        return self.connected and NEEDS_PERMISSION in (
            self.comments.read, self.comments.reply, self.dms.read, self.dms.reply
        )

    def to_record(self) -> dict:
        return {
            "platform": self.platform,
            "label": PLATFORM_LABELS.get(self.platform, self.platform),
            "connected": self.connected,
            "comments": self.comments.to_record(),
            "dms": self.dms.to_record(),
            "needs_reconnect": self.needs_reconnect,
            "reconnect_scopes": self.reconnect_scopes if self.needs_reconnect else "",
        }


def scope_tokens(raw: str) -> frozenset[str]:
    """Normalize a granted-scope string (space or comma separated, Google URL form)."""
    out: set[str] = set()
    for part in re.split(r"[\s,]+", str(raw or "")):
        token = part.strip()
        if not token:
            continue
        out.add(token.rsplit("/", 1)[-1].lower())
    return frozenset(out)


def _grant(tokens: frozenset[str], required: frozenset[str]) -> str:
    """``yes`` when granted or the grant is unknown (empty); else ``needs_permission``."""
    if not tokens:
        return YES
    return YES if tokens & required else NEEDS_PERMISSION


def reconnect_scopes(platform: str) -> str:
    """The scopes to request when reconnecting ``platform`` for inbox access."""
    override = str(config.app.get(f"social_inbox_{platform}_scopes", "") or "").strip()
    return override or _DEFAULT_RECONNECT_SCOPES.get(platform, "")


def _not_offered(platform: str, kind: str) -> Access:
    return Access(read=NOT_OFFERED, reply=NOT_OFFERED, note=_NOT_OFFERED_NOTES.get((platform, kind), ""))


def capabilities_for(platform: str, *, connected: bool, scopes: str = "") -> PlatformCapabilities:
    """Compute read/reply availability for one platform connection."""
    plat = str(platform or "").strip().lower()
    tokens = scope_tokens(scopes)
    if plat == "youtube":
        read = _grant(tokens, _YT_READ)
        reply = _grant(tokens, _YT_WRITE)
        note = ""
        if read == NEEDS_PERMISSION or reply == NEEDS_PERMISSION:
            note = "Reconnect YouTube and allow managing comments to read and reply here."
        comments = Access(read=read, reply=reply, note=note)
        dms = _not_offered(plat, "dms")
    elif plat == "instagram":
        c = _grant(tokens, _IG_COMMENTS)
        m = _grant(tokens, _IG_MESSAGES)
        comments = Access(
            read=c, reply=c,
            note="" if c == YES else "Reconnect Instagram and allow comment management to read and reply here.",
        )
        dms = Access(
            read=m, reply=m,
            note=(
                "Replies are allowed within 24 hours of the person's last message."
                if m == YES
                else "Reconnect Instagram and allow messages to see direct messages here."
            ),
        )
    elif plat == "tiktok":
        comments = _not_offered(plat, "comments")
        dms = _not_offered(plat, "dms")
    elif plat == "facebook":
        read, reply = _grant(tokens, _FB_READ), _grant(tokens, _FB_WRITE)
        comments = Access(read=read, reply=reply, note="" if YES == read == reply else (
            "Reconnect Facebook and allow reading and managing engagement on your Page."))
        dms = _not_offered(plat, "dms")
    elif plat == "threads":
        read, reply = _grant(tokens, _TH_READ), _grant(tokens, _TH_WRITE)
        comments = Access(read=read, reply=reply, note="" if YES == read == reply else (
            "Reconnect Threads and allow reading and managing replies."))
        dms = _not_offered(plat, "dms")
    elif plat == "bluesky":
        comments = Access(read=YES, reply=YES)
        dms = _not_offered(plat, "dms")
    elif plat in ("telegram", "mastodon"):
        # Bot / access-token credentials carry every permission these need.
        comments = Access(read=YES, reply=YES)
        dms = Access(read=YES, reply=YES)
    elif plat == "discord":
        comments = Access(read=YES, reply=YES, note="Needs the optional bot token on the channel.")
        dms = _not_offered(plat, "dms")
    elif plat in ("linkedin", "x", "pinterest"):
        comments = _not_offered(plat, "comments")
        dms = _not_offered(plat, "dms")
    else:
        comments = Access(read=NOT_OFFERED, reply=NOT_OFFERED, note=f"{plat} is not supported.")
        dms = Access(read=NOT_OFFERED, reply=NOT_OFFERED)

    if not connected:
        return PlatformCapabilities(platform=plat, connected=False, comments=comments, dms=dms)
    return PlatformCapabilities(
        platform=plat, connected=True, comments=comments, dms=dms, reconnect_scopes=reconnect_scopes(plat)
    )
