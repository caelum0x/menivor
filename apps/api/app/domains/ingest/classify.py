"""Classify any pasted URL for Menivor's single input box (pure, no network).

``classify_url`` answers "what did the user paste?" -- a website, an app-store
listing, a social post, or a social profile -- plus the platform, a quiet
one-line label for the UI, the normalized URL and the handle when the URL
carries one. Store-link parsing is reused from :mod:`app.domains.capture.sources`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import parse_qs, urlparse, urlunparse

from app.domains.capture.sources import apple_ref, play_ref

KIND_WEBSITE = "website"
KIND_APP_STORE = "app_store"
KIND_PLAY_STORE = "play_store"
KIND_SOCIAL_POST = "social_post"
KIND_SOCIAL_PROFILE = "social_profile"
KINDS = frozenset({KIND_WEBSITE, KIND_APP_STORE, KIND_PLAY_STORE, KIND_SOCIAL_POST, KIND_SOCIAL_PROFILE})

PLATFORM_NAMES = {
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "x": "X",
    "youtube": "YouTube",
    "facebook": "Facebook",
    "threads": "Threads",
    "pinterest": "Pinterest",
    "linkedin": "LinkedIn",
}

_HOST_PREFIXES = ("www.", "m.", "mobile.", "music.", "web.", "mbasic.")
_PINTEREST_HOST = re.compile(r"^(?:[a-z]{2}\.)?pinterest\.(?:com|[a-z]{2}|co\.[a-z]{2}|com\.[a-z]{2})$")
_BARE_DOMAIN = re.compile(r"^[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:[/?#:].*)?$", re.IGNORECASE)
_IG_USER = re.compile(r"^[A-Za-z0-9._]{1,30}$")
_X_USER = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_GENERIC_USER = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_DIGITS = re.compile(r"^\d{1,25}$")

_IG_RESERVED = frozenset({
    "explore", "accounts", "about", "developer", "legal", "direct", "stories", "web", "api",
    "challenge", "emails", "privacy", "terms", "session", "login", "signup", "p", "reel",
    "reels", "tv", "static", "oauth", "nametag", "directory",
})
_X_RESERVED = frozenset({
    "home", "search", "explore", "i", "intent", "notifications", "messages", "settings",
    "login", "signup", "tos", "privacy", "compose", "hashtag", "share", "account", "logout",
    "jobs", "about", "download", "following", "followers",
})
_FB_RESERVED = frozenset({
    "login", "help", "groups", "events", "marketplace", "gaming", "pages", "policies",
    "privacy", "settings", "watch", "home.php", "search", "hashtag", "business", "ads",
    "notifications", "messages", "friends", "bookmarks", "stories", "l.php", "dialog",
    "sharer", "sharer.php", "reel", "share", "photo", "photo.php", "story.php",
    "permalink.php", "video.php", "profile.php", "recover", "legal", "terms",
})
_PIN_RESERVED = frozenset({
    "search", "ideas", "today", "business", "settings", "categories", "explore", "_",
    "login", "pin", "resource", "about", "topics", "shopping", "news_hub", "videos",
    "password", "signup", "homefeed",
})


@dataclass(frozen=True)
class UrlKind:
    kind: str
    platform: str | None
    label: str
    url: str
    handle: str | None = None
    post_id: str | None = None
    subtype: str | None = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "platform": self.platform,
            "label": self.label,
            "url": self.url,
            "handle": self.handle,
        }


class UrlClassifyError(ValueError):
    """The input is not an http(s) URL we can work with."""


def normalize_input_url(raw: str) -> str:
    """Trim, add ``https://`` to bare domains, lowercase scheme/host, drop fragment."""
    text = (raw or "").strip()
    if not text:
        raise UrlClassifyError("Paste a link to get started")
    if "://" not in text and _BARE_DOMAIN.match(text):
        text = f"https://{text}"
    parsed = urlparse(text)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise UrlClassifyError("That does not look like a web link")
    netloc = parsed.netloc.lower() if "@" not in parsed.netloc else parsed.netloc
    return urlunparse(parsed._replace(scheme=scheme, netloc=netloc, fragment=""))


def _bare_host(host: str) -> str:
    host = host.lower().rstrip(".")
    for prefix in _HOST_PREFIXES:
        if host.startswith(prefix):
            return host[len(prefix):]
    return host


def _segments(path: str) -> list[str]:
    return [seg for seg in path.split("/") if seg]


def _post(platform: str, url: str, label: str, handle=None, post_id=None, subtype=None) -> UrlKind:
    return UrlKind(KIND_SOCIAL_POST, platform, label, url, handle, post_id, subtype)


def _profile(platform: str, url: str, label: str, handle: str | None) -> UrlKind:
    return UrlKind(KIND_SOCIAL_PROFILE, platform, label, url, handle)


def _tiktok(host: str, segs: list[str], query: dict, url: str) -> UrlKind | None:
    if host in {"vm.tiktok.com", "vt.tiktok.com"}:
        return _post("tiktok", url, "TikTok post detected", subtype="video")
    if len(segs) >= 2 and segs[0] == "t":
        return _post("tiktok", url, "TikTok post detected", subtype="video")
    if not segs or not segs[0].startswith("@") or len(segs[0]) < 2:
        return None
    handle = segs[0][1:]
    if len(segs) >= 3 and segs[1] in {"video", "photo"}:
        return _post("tiktok", url, "TikTok post detected", handle, segs[2], segs[1])
    if len(segs) == 1:
        return _profile("tiktok", url, "TikTok profile detected", handle)
    return None


_IG_POST_LABELS = {"p": "Instagram post detected", "reel": "Instagram reel detected",
                   "reels": "Instagram reel detected", "tv": "Instagram video detected"}


def _instagram(host: str, segs: list[str], query: dict, url: str) -> UrlKind | None:
    if len(segs) >= 2 and segs[0] in _IG_POST_LABELS:
        return _post("instagram", url, _IG_POST_LABELS[segs[0]], None, segs[1], segs[0])
    if len(segs) >= 3 and segs[1] in _IG_POST_LABELS and _IG_USER.match(segs[0]):
        return _post("instagram", url, _IG_POST_LABELS[segs[1]], segs[0], segs[2], segs[1])
    if len(segs) == 1 and segs[0].lower() not in _IG_RESERVED and _IG_USER.match(segs[0]):
        return _profile("instagram", url, "Instagram profile detected", segs[0])
    return None


def _x(host: str, segs: list[str], query: dict, url: str) -> UrlKind | None:
    if len(segs) >= 4 and segs[:3] == ["i", "web", "status"] and _DIGITS.match(segs[3]):
        return _post("x", url, "X post detected", None, segs[3], "text")
    if not segs or segs[0].lower() in _X_RESERVED or not _X_USER.match(segs[0]):
        return None
    if len(segs) >= 3 and segs[1] == "status" and _DIGITS.match(segs[2]):
        return _post("x", url, "X post detected", segs[0], segs[2], "text")
    if len(segs) == 1:
        return _profile("x", url, "X profile detected", segs[0])
    return None


def _youtube(host: str, segs: list[str], query: dict, url: str) -> UrlKind | None:
    if host == "youtu.be" and segs:
        return _post("youtube", url, "YouTube video detected", None, segs[0], "video")
    if not segs:
        return None
    head = segs[0]
    if head == "watch" and query.get("v"):
        return _post("youtube", url, "YouTube video detected", None, query["v"][0], "video")
    if head in {"shorts", "live", "embed"} and len(segs) >= 2:
        labels = {"shorts": "YouTube Short detected", "live": "YouTube live video detected",
                  "embed": "YouTube video detected"}
        subtype = {"shorts": "short", "live": "live", "embed": "video"}[head]
        return _post("youtube", url, labels[head], None, segs[1], subtype)
    if head.startswith("@") and len(head) > 1:
        return _profile("youtube", url, "YouTube channel detected", head[1:])
    if head in {"channel", "c", "user"} and len(segs) >= 2:
        return _profile("youtube", url, "YouTube channel detected", segs[1])
    return None


def _facebook(host: str, segs: list[str], query: dict, url: str) -> UrlKind | None:
    if host == "fb.watch" and segs:
        return _post("facebook", url, "Facebook video detected", None, segs[0], "video")
    if not segs:
        return None
    head = segs[0].lower()
    if head == "watch" and query.get("v"):
        return _post("facebook", url, "Facebook video detected", None, query["v"][0], "video")
    if head == "reel" and len(segs) >= 2:
        return _post("facebook", url, "Facebook reel detected", None, segs[1], "reel")
    if head == "share" and len(segs) >= 2:
        return _post("facebook", url, "Facebook post detected", None, segs[-1], "post")
    if head in {"story.php", "permalink.php", "photo.php", "photo", "video.php"}:
        return _post("facebook", url, "Facebook post detected", None, None, "post")
    if head == "profile.php" and query.get("id"):
        return _profile("facebook", url, "Facebook page detected", query["id"][0])
    if head in _FB_RESERVED or not _GENERIC_USER.match(segs[0]):
        return None
    if len(segs) >= 3 and segs[1] in {"videos", "posts", "photos"}:
        subtype = "video" if segs[1] == "videos" else "post"
        label = "Facebook video detected" if subtype == "video" else "Facebook post detected"
        return _post("facebook", url, label, segs[0], segs[2], subtype)
    if len(segs) == 1:
        return _profile("facebook", url, "Facebook page detected", segs[0])
    return None


def _threads(host: str, segs: list[str], query: dict, url: str) -> UrlKind | None:
    if not segs or not segs[0].startswith("@") or len(segs[0]) < 2:
        return None
    handle = segs[0][1:]
    if len(segs) >= 3 and segs[1] == "post":
        return _post("threads", url, "Threads post detected", handle, segs[2], "text")
    if len(segs) == 1:
        return _profile("threads", url, "Threads profile detected", handle)
    return None


def _pinterest(host: str, segs: list[str], query: dict, url: str) -> UrlKind | None:
    if host == "pin.it" and segs:
        return _post("pinterest", url, "Pinterest pin detected", None, segs[0], "pin")
    if len(segs) >= 2 and segs[0] == "pin":
        return _post("pinterest", url, "Pinterest pin detected", None, segs[1], "pin")
    if 1 <= len(segs) <= 2 and segs[0].lower() not in _PIN_RESERVED and _GENERIC_USER.match(segs[0]):
        return _profile("pinterest", url, "Pinterest profile detected", segs[0])
    return None


def _linkedin(host: str, segs: list[str], query: dict, url: str) -> UrlKind | None:
    if len(segs) >= 2 and segs[0] == "posts":
        return _post("linkedin", url, "LinkedIn post detected", None, segs[1], "text")
    if len(segs) >= 3 and segs[:2] == ["feed", "update"]:
        return _post("linkedin", url, "LinkedIn post detected", None, segs[2], "text")
    if len(segs) >= 2 and segs[0] == "in":
        return _profile("linkedin", url, "LinkedIn profile detected", segs[1])
    if len(segs) >= 2 and segs[0] in {"company", "school", "showcase"}:
        return _profile("linkedin", url, "LinkedIn company page detected", segs[1])
    return None


_Matcher = Callable[[str, list, dict, str], "UrlKind | None"]
_PLATFORM_HOSTS: dict[str, tuple[str, _Matcher]] = {
    "tiktok.com": ("tiktok", _tiktok),
    "vm.tiktok.com": ("tiktok", _tiktok),
    "vt.tiktok.com": ("tiktok", _tiktok),
    "instagram.com": ("instagram", _instagram),
    "x.com": ("x", _x),
    "twitter.com": ("x", _x),
    "youtube.com": ("youtube", _youtube),
    "youtu.be": ("youtube", _youtube),
    "facebook.com": ("facebook", _facebook),
    "fb.com": ("facebook", _facebook),
    "fb.watch": ("facebook", _facebook),
    "threads.net": ("threads", _threads),
    "threads.com": ("threads", _threads),
    "pin.it": ("pinterest", _pinterest),
    "linkedin.com": ("linkedin", _linkedin),
}


def platform_for_host(host: str) -> str | None:
    """Return the platform key for ``host`` (any subdomain form), or ``None``."""
    bare = _bare_host(host or "")
    if bare in _PLATFORM_HOSTS:
        return _PLATFORM_HOSTS[bare][0]
    if _PINTEREST_HOST.match(bare):
        return "pinterest"
    return None


def _matcher_for(host: str) -> _Matcher | None:
    bare = _bare_host(host)
    if bare in _PLATFORM_HOSTS:
        return _PLATFORM_HOSTS[bare][1]
    if _PINTEREST_HOST.match(bare):
        return _pinterest
    return None


def _store_kind(url: str) -> UrlKind | None:
    if apple_ref(url) is not None:
        return UrlKind(KIND_APP_STORE, None, "App Store app detected", url)
    if play_ref(url) is not None:
        return UrlKind(KIND_PLAY_STORE, None, "Google Play app detected", url)
    return None


def classify_url(raw_url: str) -> UrlKind:
    """Classify ``raw_url``; raises :class:`UrlClassifyError` when it is not a link."""
    url = normalize_input_url(raw_url)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    store = _store_kind(url)
    if store is not None:
        return store
    matcher = _matcher_for(host)
    if matcher is not None:
        found = matcher(_bare_host(host), _segments(parsed.path), parse_qs(parsed.query), url)
        if found is not None:
            return found
    return UrlKind(KIND_WEBSITE, None, "Website detected", url)


__all__ = [
    "KINDS", "KIND_APP_STORE", "KIND_PLAY_STORE", "KIND_SOCIAL_POST", "KIND_SOCIAL_PROFILE",
    "KIND_WEBSITE", "PLATFORM_NAMES", "UrlClassifyError", "UrlKind", "classify_url",
    "normalize_input_url", "platform_for_host",
]
