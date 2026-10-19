"""Turn a pasted post link into ``(platform, post id)``.

Only links on the platforms' own hosts are accepted. Short links (``vm.tiktok.com``,
``fb.watch`` ...) are expanded by following redirects one hop at a time, and every
hop must stay on a known platform host, so a pasted link can never make the
server fetch an arbitrary address.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import parse_qs, urlparse

MAX_URL_LENGTH = 2048
_MAX_REDIRECTS = 5
_REDIRECT_TIMEOUT_S = 8.0

_TIKTOK_HOSTS = frozenset({"tiktok.com", "www.tiktok.com", "m.tiktok.com"})
_TIKTOK_SHORT = frozenset({"vm.tiktok.com", "vt.tiktok.com"})
_YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"})
_INSTAGRAM_HOSTS = frozenset({"instagram.com", "www.instagram.com", "m.instagram.com"})
_FACEBOOK_HOSTS = frozenset({"facebook.com", "www.facebook.com", "m.facebook.com", "web.facebook.com"})
_FACEBOOK_SHORT = frozenset({"fb.watch"})
_X_HOSTS = frozenset({"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com",
                      "mobile.x.com"})
_THREADS_HOSTS = frozenset({"threads.net", "www.threads.net", "threads.com", "www.threads.com"})
_BLUESKY_HOSTS = frozenset({"bsky.app", "www.bsky.app"})

#: Every host a redirect chain may pass through.
ALLOWED_HOSTS: frozenset[str] = (
    _TIKTOK_HOSTS | _TIKTOK_SHORT | _YOUTUBE_HOSTS | {"youtu.be"} | _INSTAGRAM_HOSTS
    | _FACEBOOK_HOSTS | _FACEBOOK_SHORT | _X_HOSTS | _THREADS_HOSTS | _BLUESKY_HOSTS
)

_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_DIGITS = re.compile(r"^\d{5,25}$")
_CODE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


class LinkError(ValueError):
    """The link is not a post on a supported platform (message is user-facing)."""


@dataclass(frozen=True)
class PostLink:
    platform: str
    external_id: str   # the platform's post id (Instagram/Threads: the shortcode)
    url: str           # a clean canonical link to the post
    id_kind: str = "id"  # "id" | "shortcode" | "handle_rkey" (Bluesky)


def _clean(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        raise LinkError("Paste the link to your post.")
    if len(text) > MAX_URL_LENGTH:
        raise LinkError("That link is too long.")
    if not re.match(r"^https?://", text, re.IGNORECASE):
        text = f"https://{text}"
    return text


def _parts(url: str) -> tuple[str, list[str], dict[str, list[str]]]:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https"):
        raise LinkError("That does not look like a post link.")
    host = (parsed.hostname or "").lower()
    segments = [s for s in parsed.path.split("/") if s]
    return host, segments, parse_qs(parsed.query)


def is_short_link(url: str) -> bool:
    try:
        host, segments, _ = _parts(_clean(url))
    except LinkError:
        return False
    if host in _TIKTOK_SHORT or host in _FACEBOOK_SHORT:
        return True
    if host in _TIKTOK_HOSTS and segments[:1] == ["t"]:
        return True
    return host in _FACEBOOK_HOSTS and segments[:1] == ["share"]


def _tiktok(segments: list[str]) -> PostLink | None:
    for i, seg in enumerate(segments[:-1]):
        if seg in ("video", "photo") and _DIGITS.match(segments[i + 1]):
            vid = segments[i + 1]
            user = segments[0] if segments[0].startswith("@") else ""
            url = f"https://www.tiktok.com/{user}/video/{vid}" if user else f"https://www.tiktok.com/video/{vid}"
            return PostLink("tiktok", vid, url)
    return None


def _youtube(host: str, segments: list[str], query: dict[str, list[str]]) -> PostLink | None:
    candidate = ""
    if host == "youtu.be":
        candidate = segments[0] if segments else ""
    elif segments[:1] in (["shorts"], ["live"], ["embed"]) and len(segments) > 1:
        candidate = segments[1]
    elif segments[:1] == ["watch"]:
        candidate = (query.get("v") or [""])[0]
    if _YT_ID.match(candidate):
        return PostLink("youtube", candidate, f"https://www.youtube.com/shorts/{candidate}")
    return None


def _instagram(segments: list[str]) -> PostLink | None:
    for i, seg in enumerate(segments[:-1]):
        if seg in ("reel", "reels", "p", "tv") and _CODE.match(segments[i + 1]):
            code = segments[i + 1]
            return PostLink("instagram", code, f"https://www.instagram.com/reel/{code}/", "shortcode")
    return None


def _facebook(segments: list[str], query: dict[str, list[str]]) -> PostLink | None:
    for i, seg in enumerate(segments[:-1]):
        if seg in ("reel", "videos", "posts") and _DIGITS.match(segments[i + 1]):
            vid = segments[i + 1]
            return PostLink("facebook", vid, f"https://www.facebook.com/reel/{vid}")
    if segments[:1] == ["watch"]:
        vid = (query.get("v") or [""])[0]
        if _DIGITS.match(vid):
            return PostLink("facebook", vid, f"https://www.facebook.com/reel/{vid}")
    return None


def _x(segments: list[str]) -> PostLink | None:
    for i, seg in enumerate(segments[:-1]):
        if seg in ("status", "statuses") and _DIGITS.match(segments[i + 1]):
            pid = segments[i + 1]
            return PostLink("x", pid, f"https://x.com/i/web/status/{pid}")
    return None


def _threads(segments: list[str]) -> PostLink | None:
    for i, seg in enumerate(segments[:-1]):
        if seg in ("post", "t") and _CODE.match(segments[i + 1]):
            code = segments[i + 1]
            user = segments[0] if segments[0].startswith("@") else ""
            url = f"https://www.threads.net/{user}/post/{code}" if user else f"https://www.threads.net/t/{code}"
            return PostLink("threads", code, url, "shortcode")
    return None


def _bluesky(segments: list[str]) -> PostLink | None:
    if len(segments) >= 4 and segments[0] == "profile" and segments[2] == "post":
        actor, rkey = segments[1], segments[3]
        if re.match(r"^[A-Za-z0-9.:_-]{3,253}$", actor) and _CODE.match(rkey):
            return PostLink("bluesky", f"{actor}/{rkey}", f"https://bsky.app/profile/{actor}/post/{rkey}",
                            "handle_rkey")
    return None


def parse_post_link(raw: str) -> PostLink:
    """Parse an already-expanded post link, or raise :class:`LinkError`."""
    host, segments, query = _parts(_clean(raw))
    found: PostLink | None = None
    if host in _TIKTOK_HOSTS:
        found = _tiktok(segments)
    elif host in _YOUTUBE_HOSTS or host == "youtu.be":
        found = _youtube(host, segments, query)
    elif host in _INSTAGRAM_HOSTS:
        found = _instagram(segments)
    elif host in _FACEBOOK_HOSTS:
        found = _facebook(segments, query)
    elif host in _X_HOSTS:
        found = _x(segments)
    elif host in _THREADS_HOSTS:
        found = _threads(segments)
    elif host in _BLUESKY_HOSTS:
        found = _bluesky(segments)
    else:
        raise LinkError(
            "Paste a link from TikTok, YouTube, Instagram, Facebook, X, Threads or Bluesky."
        )
    if found is None:
        raise LinkError("That link does not point to a single post. Open the post and copy its link.")
    return found


RedirectFn = Callable[[str], str]


def _next_location(url: str) -> str:
    """One redirect hop without following it (``""`` when there is none)."""
    import requests

    resp = requests.get(url, allow_redirects=False, timeout=_REDIRECT_TIMEOUT_S,
                        headers={"User-Agent": "Mozilla/5.0 (compatible; MenivorBot/1.0)"}, stream=True)
    try:
        if resp.status_code in (301, 302, 303, 307, 308):
            return str(resp.headers.get("Location") or "")
        return ""
    finally:
        resp.close()


def expand_short_link(raw: str, *, next_location: RedirectFn | None = None) -> str:
    """Follow a short link hop by hop, staying on known platform hosts."""
    hop = next_location or _next_location
    url = _clean(raw)
    for _ in range(_MAX_REDIRECTS):
        if not is_short_link(url):
            return url
        try:
            location = hop(url)
        except Exception as exc:  # noqa: BLE001 - network failure is a user-facing retry
            raise LinkError("That short link could not be opened. Paste the full post link instead.") from exc
        if not location:
            break
        if location.startswith("/"):
            parsed = urlparse(url)
            location = f"{parsed.scheme}://{parsed.netloc}{location}"
        host = (urlparse(location).hostname or "").lower()
        if host not in ALLOWED_HOSTS:
            raise LinkError("That short link leads off the platform. Paste the full post link instead.")
        url = location
    if is_short_link(url):
        raise LinkError("That short link could not be opened. Paste the full post link instead.")
    return url


def resolve_post_link(raw: str, *, next_location: RedirectFn | None = None) -> PostLink:
    """Expand (if short) and parse a pasted link."""
    url = _clean(raw)
    if is_short_link(url):
        url = expand_short_link(url, next_location=next_location)
    return parse_post_link(url)


__all__ = [
    "ALLOWED_HOSTS",
    "LinkError",
    "MAX_URL_LENGTH",
    "PostLink",
    "expand_short_link",
    "is_short_link",
    "parse_post_link",
    "resolve_post_link",
]
