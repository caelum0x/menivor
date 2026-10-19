"""Resolve social posts/profiles through FREE public endpoints.

* TikTok / YouTube / X posts: public oEmbed (no token).
* Instagram / Facebook posts: oEmbed needs an app token, so we read the public
  OpenGraph preview instead and say so in ``note``.
* Threads / Pinterest / LinkedIn posts and every profile: OpenGraph/twitter
  meta tags from the page itself.

All HTTP goes through an injectable ``http(url) -> (status, text)`` seam
(default: the allowlisted SSRF-safe :func:`social_http_get`), so tests mock it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import quote

from app.domains.ingest.classify import KIND_SOCIAL_POST, PLATFORM_NAMES, UrlKind
from app.domains.ingest.errors import IngestError
from app.domains.ingest.meta import (
    clean_text, first_line_hook, niche_from, parse_duration, parse_meta, topic_from, voice_from,
)
from app.domains.ingest.safe_fetch import HttpGet

_OEMBED = {
    "tiktok": "https://www.tiktok.com/oembed?url={url}",
    "youtube": "https://www.youtube.com/oembed?url={url}&format=json",
    "x": "https://publish.twitter.com/oembed?url={url}&omit_script=1&dnt=true",
}
_TOKEN_NOTE = "{name} hides post details without an app token, so we used the public preview"
_PROFILE_NOTE = "{name} hides profile details from previews, so we used the handle"
_TWEET_P = re.compile(r"<p[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
_IG_QUOTED = re.compile(r':\s*["“](.*)["”]\s*\.?\s*$', re.DOTALL)
_NAME_SUFFIX = re.compile(
    r"\s+(?:\(@|[•|·]\s|[-–—]\s+(?:YouTube|TikTok|LinkedIn|Facebook)"
    r"|on (?:Instagram|Pinterest|TikTok|X|Threads|Facebook|LinkedIn)\b).*$",
    re.IGNORECASE | re.DOTALL,
)
_HASHTAGS = re.compile(r"#[A-Za-z][A-Za-z0-9_]{1,40}")
_MISSING = (400, 401, 403, 404, 410)


@dataclass(frozen=True)
class SocialResult:
    content: dict
    inspiration: dict | None = None
    brand: dict | None = None
    note: str | None = None


def _name(kind: UrlKind) -> str:
    return PLATFORM_NAMES.get(kind.platform or "", "That platform")


def _gone(kind: UrlKind) -> IngestError:
    noun = "video" if kind.platform == "youtube" else "post"
    return IngestError(404, f"That {_name(kind)} {noun} is private or deleted")


def _check_status(kind: UrlKind, status: int) -> None:
    if status >= 500 or status == 429:
        raise IngestError(502, f"{_name(kind)} did not respond. Try again in a moment")


def _oembed(kind: UrlKind, http: HttpGet, target: str) -> dict:
    status, text = http(_OEMBED[kind.platform].format(url=quote(target, safe="")))
    if status in _MISSING:
        raise _gone(kind)
    _check_status(kind, status)
    try:
        data = json.loads(text or "")
    except ValueError as exc:
        raise IngestError(502, f"{_name(kind)} sent an unreadable preview") from exc
    if not isinstance(data, dict):
        raise IngestError(502, f"{_name(kind)} sent an unreadable preview")
    return data


def _page_meta(kind: UrlKind, http: HttpGet, url: str) -> tuple[int, dict]:
    status, text = http(url)
    if status in _MISSING:
        return status, {}
    _check_status(kind, status)
    return status, parse_meta(text)


def _post_format(kind: UrlKind, og_type: str = "") -> str:
    is_video = og_type.startswith("video")
    table = {
        "tiktok": "photo carousel" if kind.subtype == "photo" else "short video",
        "youtube": {"short": "short video", "live": "live video"}.get(kind.subtype or "", "video"),
        "x": "text post",
        "threads": "text post",
        "linkedin": "video post" if is_video else "text post",
        "pinterest": "video pin" if is_video else "image pin",
        "instagram": "short video" if kind.subtype in {"reel", "reels", "tv"} or is_video else "image post",
        "facebook": {"reel": "short video", "video": "video"}.get(kind.subtype or "", "video" if is_video else "post"),
    }
    return table.get(kind.platform or "", "post")


def _inspiration(caption: str, fmt: str, *, author=None, thumb=None, duration=None) -> dict:
    caption = (caption or "").strip()
    return {
        "caption": caption,
        "hook": first_line_hook(caption),
        "topic": topic_from(caption),
        "format": fmt,
        "duration_s": duration,
        "author_name": author or None,
        "thumbnail_url": thumb or None,
    }


def _post_content(kind: UrlKind, inspiration: dict) -> dict:
    caption = inspiration["caption"]
    title = inspiration["hook"] or f"{_name(kind)} {inspiration['format']}"
    tags = list(dict.fromkeys(_HASHTAGS.findall(caption)))[:6]
    return {"title": title, "description": caption[:500], "features": tags, "url": kind.url}


def _youtube_duration(http: HttpGet, watch_url: str) -> int | None:
    try:
        status, text = http(watch_url)
    except IngestError:
        return None
    if status >= 400:
        return None
    meta = parse_meta(text)
    return parse_duration(meta.get("duration") or meta.get("og:video:duration"))


def _resolve_oembed_post(kind: UrlKind, http: HttpGet) -> SocialResult:
    target = kind.url
    if kind.platform == "youtube" and kind.post_id:
        target = f"https://www.youtube.com/watch?v={quote(kind.post_id, safe='')}"
    data = _oembed(kind, http, target)
    caption = str(data.get("title") or "")
    if kind.platform == "x":
        match = _TWEET_P.search(str(data.get("html") or ""))
        caption = clean_text(match.group(1)) if match else ""
    if not caption.strip():
        raise _gone(kind)
    duration = _youtube_duration(http, target) if kind.platform == "youtube" else None
    fmt = _post_format(kind)
    if kind.platform == "x" and "pic.twitter.com" in str(data.get("html") or ""):
        fmt = "image post"
    insp = _inspiration(caption, fmt, author=data.get("author_name"),
                        thumb=data.get("thumbnail_url"), duration=duration)
    return SocialResult(_post_content(kind, insp), inspiration=insp)


def _og_caption(kind: UrlKind, meta: dict) -> str:
    raw = meta.get("og:description") or meta.get("twitter:description") or meta.get("description") or ""
    if kind.platform == "instagram":
        match = _IG_QUOTED.search(raw)
        raw = match.group(1) if match else raw
    return raw.strip() or (meta.get("og:title") or meta.get("twitter:title") or "").strip()


def _author_from_title(title: str) -> str | None:
    name = _NAME_SUFFIX.sub("", title or "").strip()
    return name[:80] or None


def _resolve_og_post(kind: UrlKind, http: HttpGet) -> SocialResult:
    status, meta = _page_meta(kind, http, kind.url)
    if status == 404:
        raise _gone(kind)
    if status in _MISSING:
        raise IngestError(424, f"{_name(kind)} would not share this post's preview. Paste the caption instead")
    caption = _og_caption(kind, meta)
    if not caption:
        raise _gone(kind)
    duration = parse_duration(meta.get("og:video:duration") or meta.get("video:duration") or meta.get("duration"))
    insp = _inspiration(
        caption, _post_format(kind, meta.get("og:type", "")),
        author=kind.handle or _author_from_title(meta.get("og:title", "")),
        thumb=meta.get("og:image") or meta.get("twitter:image"), duration=duration,
    )
    note = _TOKEN_NOTE.format(name=_name(kind)) if kind.platform in {"instagram", "facebook"} else None
    return SocialResult(_post_content(kind, insp), inspiration=insp, note=note)


def _brand(kind: UrlKind, meta: dict) -> dict:
    name = _author_from_title(meta.get("og:title") or meta.get("twitter:title") or meta.get("title") or "")
    bio = (meta.get("og:description") or meta.get("twitter:description") or meta.get("description") or "").strip()
    name = name or kind.handle or _name(kind)
    return {
        "name": name,
        "handle": kind.handle,
        "bio": bio,
        "avatar_url": meta.get("og:image") or meta.get("twitter:image") or None,
        "niche": niche_from(bio, name),
        "voice": voice_from(bio),
    }


def _resolve_profile(kind: UrlKind, http: HttpGet) -> SocialResult:
    status, meta = _page_meta(kind, http, kind.url)
    if status == 404:
        raise IngestError(404, f"That {_name(kind)} profile does not exist")
    has_details = bool(meta.get("og:title") or meta.get("og:description"))
    brand = _brand(kind, meta if has_details else {})
    note = None if has_details else _PROFILE_NOTE.format(name=_name(kind))
    if not has_details and not kind.handle:
        raise IngestError(424, f"{_name(kind)} would not share this profile's preview")
    content = {"title": brand["name"], "description": brand["bio"], "features": [], "url": kind.url}
    return SocialResult(content, brand=brand, note=note)


def resolve_social(kind: UrlKind, http: HttpGet) -> SocialResult:
    """Resolve a classified social post/profile via ``http`` (mockable)."""
    if kind.kind != KIND_SOCIAL_POST:
        return _resolve_profile(kind, http)
    if kind.platform in _OEMBED:
        return _resolve_oembed_post(kind, http)
    return _resolve_og_post(kind, http)


__all__ = ["SocialResult", "resolve_social"]
